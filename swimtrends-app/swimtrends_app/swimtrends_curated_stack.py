"""Swimtrends curated zone (Spec 2 of 3).

A class-overrides DynamoDB table, a Fargate task that runs the curated transform,
an S3-event trigger Lambda (raw results.jsonl -> RunTask), a Glue database with
one table per curated dataset, and SNS alerts. Reuses the swimtrends-meet-data
bucket and the ingestion ECS cluster by name."""
import os
import sys

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

ST_SCRAPE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "st-scrape"))
sys.path.insert(0, ST_SCRAPE_DIR)
from curate import catalog  # noqa: E402  (import after path insert)

CONTAINER_NAME = "curate"
BUCKET_NAME = "swimtrends-meet-data"
CURATED_TABLES = ["dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"]


class SwimtrendsCuratedStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 alert_email: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket.from_bucket_name(self, "DataBucket", BUCKET_NAME)

        overrides = dynamodb.Table(
            self, "ClassOverrides",
            table_name="swimtrends-class-overrides",
            partition_key=dynamodb.Attribute(
                name="meet_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(
                name="race_id", type=dynamodb.AttributeType.NUMBER),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        topic = sns.Topic(self, "CurateAlertTopic",
                          display_name="Swimtrends curate alerts")
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))

        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        sg = ec2.SecurityGroup(self, "CurateTaskSG", vpc=vpc,
                               allow_all_outbound=True,
                               description="Egress-only SG for the curate task")
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster", cluster_name="swimtrends-ingestion",
            vpc=vpc, security_groups=[])

        task_def = ecs.FargateTaskDefinition(
            self, "CurateTaskDef", cpu=512, memory_limit_mib=1024)
        task_def.add_container(
            CONTAINER_NAME,
            image=ecs.ContainerImage.from_asset(
                ST_SCRAPE_DIR, file="Dockerfile.curate"),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="curate",
                log_retention=logs.RetentionDays.ONE_MONTH),
            environment={
                "CURATED_BUCKET": BUCKET_NAME,
                "OVERRIDES_TABLE": overrides.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
            },
        )
        bucket.grant_read(task_def.task_role, objects_key_pattern="raw/*")
        bucket.grant_read(task_def.task_role, objects_key_pattern="reference/*")
        bucket.grant_put(task_def.task_role, objects_key_pattern="curated/*")
        overrides.grant_read_data(task_def.task_role)
        topic.grant_publish(task_def.task_role)

        # --- S3-event trigger Lambda: raw results.jsonl lands -> RunTask ---
        trigger_fn = lambda_.Function(
            self, "CurateTrigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="curate_trigger.lambda_handler",
            timeout=Duration.minutes(1),
            memory_size=256,
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "lambda_curate_trigger")),
            environment={
                "ECS_CLUSTER": cluster.cluster_arn,
                "TASK_DEFINITION": task_def.task_definition_arn,
                "CONTAINER_NAME": CONTAINER_NAME,
                "SUBNET_IDS": ",".join(s.subnet_id for s in vpc.public_subnets),
                "SECURITY_GROUP_ID": sg.security_group_id,
            },
        )
        trigger_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ecs:RunTask"], resources=[task_def.task_definition_arn]))
        trigger_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[task_def.task_role.role_arn,
                       task_def.obtain_execution_role().role_arn]))

        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(trigger_fn),
            s3.NotificationKeyFilter(prefix="raw/", suffix="results.jsonl"))

        # --- Glue catalog ---
        db = glue.CfnDatabase(
            self, "CuratedDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="swimtrends_curated"))
        for name in CURATED_TABLES:
            location = f"s3://{BUCKET_NAME}/curated/{name}/"
            ti = catalog.table_input(name, location)
            tbl = glue.CfnTable(
                self, f"Table{name}",
                catalog_id=self.account,
                database_name="swimtrends_curated",
                table_input=glue.CfnTable.TableInputProperty(
                    name=ti["Name"],
                    table_type=ti["TableType"],
                    parameters=ti["Parameters"],
                    partition_keys=[
                        glue.CfnTable.ColumnProperty(name=c["Name"], type=c["Type"])
                        for c in ti["PartitionKeys"]],
                    storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                        columns=[glue.CfnTable.ColumnProperty(
                            name=c["Name"], type=c["Type"])
                            for c in ti["StorageDescriptor"]["Columns"]],
                        location=location,
                        input_format=ti["StorageDescriptor"]["InputFormat"],
                        output_format=ti["StorageDescriptor"]["OutputFormat"],
                        serde_info=glue.CfnTable.SerdeInfoProperty(
                            serialization_library=ti["StorageDescriptor"]
                            ["SerdeInfo"]["SerializationLibrary"]))))
            tbl.add_dependency(db)
