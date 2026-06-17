"""Swimtrends ingestion platform (Spec 1 of 3).

DynamoDB meet registry, ECR image + Fargate task running the st-scrape scraper,
a dispatcher Lambda triggered hourly by EventBridge (and on demand by the CLI),
and an SNS topic for alerts. Reuses the existing swimtrends-meet-data S3 bucket.
"""
import os

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

# st-scrape lives alongside swimtrends-app (this file is .../swimtrends_app/).
ST_SCRAPE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "st-scrape"))

CONTAINER_NAME = "scraper"
RAW_BUCKET_NAME = "swimtrends-meet-data"


class SwimtrendsIngestionStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 alert_email: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Reused raw data bucket ---
        raw_bucket = s3.Bucket.from_bucket_name(
            self, "RawBucket", RAW_BUCKET_NAME)

        # --- Meet registry ---
        registry = dynamodb.Table(
            self, "MeetRegistry",
            table_name="swimtrends-meet-registry",
            partition_key=dynamodb.Attribute(
                name="meet_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # --- Alerts ---
        topic = sns.Topic(self, "AlertTopic", display_name="Swimtrends ingestion alerts")
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))

        # --- Networking: default VPC, public subnets, egress-only SG (no NAT) ---
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        scrape_sg = ec2.SecurityGroup(
            self, "ScrapeTaskSG", vpc=vpc, allow_all_outbound=True,
            description="Egress-only SG for the Fargate scrape task")

        # --- ECS cluster + Fargate task definition ---
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc,
                              cluster_name="swimtrends-ingestion")

        task_def = ecs.FargateTaskDefinition(
            self, "ScrapeTaskDef", cpu=512, memory_limit_mib=1024)

        scraper_image = ecs.ContainerImage.from_asset(ST_SCRAPE_DIR)
        task_def.add_container(
            CONTAINER_NAME,
            image=scraper_image,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="scrape",
                log_retention=logs.RetentionDays.ONE_MONTH),
            environment={
                "RAW_BUCKET": RAW_BUCKET_NAME,
                "REGISTRY_TABLE": registry.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
            },
        )

        # Task role: write raw objects, update registry, publish alerts.
        raw_bucket.grant_put(task_def.task_role, objects_key_pattern="raw/*")
        registry.grant_write_data(task_def.task_role)
        topic.grant_publish(task_def.task_role)

        # --- Dispatcher Lambda (bundles scraper + ingestion + deps) ---
        dispatcher_fn = lambda_.Function(
            self, "Dispatcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="ingestion.dispatcher.lambda_handler",
            timeout=Duration.minutes(1),
            memory_size=256,
            code=lambda_.Code.from_asset(
                ST_SCRAPE_DIR,
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash", "-c",
                        "pip install requests beautifulsoup4 tzdata -t /asset-output && "
                        "cp scrape_races.py /asset-output/ && "
                        "cp -r ingestion /asset-output/",
                    ],
                },
            ),
            environment={
                "REGISTRY_TABLE": registry.table_name,
                "RAW_BUCKET": RAW_BUCKET_NAME,
                "SNS_TOPIC_ARN": topic.topic_arn,
                "ECS_CLUSTER": cluster.cluster_arn,
                "TASK_DEFINITION": task_def.task_definition_arn,
                "CONTAINER_NAME": CONTAINER_NAME,
                "SUBNET_IDS": ",".join(
                    s.subnet_id for s in vpc.public_subnets),
                "SECURITY_GROUP_ID": scrape_sg.security_group_id,
                "REFERENCE_TZ": "Europe/Copenhagen",
                "MAX_ATTEMPTS": "3",
                "REAP_TTL_HOURS": "6",
            },
        )

        # Dispatcher permissions: read/update registry, launch tasks, alert,
        # and read raw objects to reconcile meets orphaned in 'scraping'.
        registry.grant_read_write_data(dispatcher_fn)
        raw_bucket.grant_read(dispatcher_fn, objects_key_pattern="raw/*")
        topic.grant_publish(dispatcher_fn)
        dispatcher_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ecs:RunTask"],
            resources=[task_def.task_definition_arn]))
        dispatcher_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[task_def.task_role.role_arn,
                       task_def.obtain_execution_role().role_arn]))

        # --- Hourly schedule ---
        events.Rule(
            self, "HourlySchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(dispatcher_fn)],
        )
