import json

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_athena as athena
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


class SwimtrendsAppStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create an S3 bucket
        swimtrends_meet_data_bucket = s3.Bucket(
            self, "swimtrends-meet-data-bucket",
            bucket_name="swimtrends-meet-data",
            versioned=True,
            public_read_access=False,
            removal_policy=RemovalPolicy.RETAIN
        )   

        ##############################################################
        # Create the Glue database and table
        ##############################################################

        glue_db_name = "swimtrends_meet_db"
        # Create the Glue database (needed for Athena)
        swimtrends_meet_data_glue_database = glue.CfnDatabase(
            self, "SwimtrendsMeetGlueDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=glue_db_name,
                description="Database for Swimtrends meet data analysis"
            )
        )

        # Create an IAM role for the Glue Crawler
        crawler_role = iam.Role(
            self, "GlueCrawlerRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSGlueServiceRole")
            ]
        )

        # Add S3 permissions to the role
        crawler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:ListBucket"],
                resources=[
                    f"arn:aws:s3:::{swimtrends_meet_data_bucket.bucket_name}",
                    f"arn:aws:s3:::{swimtrends_meet_data_bucket.bucket_name}/*"
                ]
            )
        )
        
        # Create the Glue Crawler
        glue_crawler = glue.CfnCrawler(
            self, "SwimtrendsGlueCrawler",
            name="Swimtrends-meet-data-crawler",
            role=crawler_role.role_arn,
            database_name=glue_db_name,
             # Set table prefix to control naming
            table_prefix="swimtrends_",  # This will create "Swimtrends_meet" or similar
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{swimtrends_meet_data_bucket.bucket_name}/swimtrends-meets/"
                    ),
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{swimtrends_meet_data_bucket.bucket_name}/swimtrends-races/"
                    ),
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{swimtrends_meet_data_bucket.bucket_name}/swimtrends-results/"
                    )
                ]
            ),
            schema_change_policy=glue.CfnCrawler.SchemaChangePolicyProperty(
                update_behavior="UPDATE_IN_DATABASE",
                delete_behavior="LOG"
            ),
            configuration=json.dumps({
                "Version": 1.0,
                "CrawlerOutput": {
                    "Tables": {
                        "AddOrUpdateBehavior": "MergeNewColumns"
                    }
                }
            }),
            recrawl_policy=glue.CfnCrawler.RecrawlPolicyProperty(
                recrawl_behavior="CRAWL_EVERYTHING"
            ),
            schedule=glue.CfnCrawler.ScheduleProperty(
                schedule_expression="cron(0 0 * * ? *)"  # Run at midnight every day
            )
        )
        
        # Add depends on for the database
        glue_crawler.add_dependency(swimtrends_meet_data_glue_database)
        
        # Set up Athena workgroup for query execution
        athena_workgroup_name = "swimtrends_meet_data_workgroup"
        athena.CfnWorkGroup(
            self, "SwimtrendsMeetDataWorkgroup",
            name=athena_workgroup_name,
            description="Workgroup for Swimtrends Meet Data analysis",
            state="ENABLED",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{swimtrends_meet_data_bucket.bucket_name}/athena-results/",
                    # encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                    #     encryption_option="SSE-S3",
                    # )
                ),
                execution_role=crawler_role.role_arn,
                engine_version=athena.CfnWorkGroup.EngineVersionProperty(
                    selected_engine_version="Athena engine version 3"
                )
            )
        )

        # Create IAM policy for Athena access
        iam.ManagedPolicy(
            self, "SwimtrendsMeetDataAthenaPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "athena:StartQueryExecution",
                        "athena:GetQueryExecution",
                        "athena:GetQueryResults",
                        "athena:StopQueryExecution",
                        "athena:GetWorkGroup",
                        "athena:ListQueryExecutions"
                    ],
                    resources=[f"arn:aws:athena:{self.region}:{self.account}:workgroup/{athena_workgroup_name}"]
                ),
                iam.PolicyStatement(
                    actions=[
                        "s3:GetBucketLocation",
                        "s3:GetObject",
                        "s3:ListBucket",
                        "s3:ListBucketMultipartUploads",
                        "s3:ListMultipartUploadParts",
                        "s3:AbortMultipartUpload",
                        "s3:PutObject"
                    ],
                    resources=[
                        f"arn:aws:s3:::{swimtrends_meet_data_bucket.bucket_name}",
                        f"arn:aws:s3:::{swimtrends_meet_data_bucket.bucket_name}/*"
                    ]
                ),
                iam.PolicyStatement(
                    actions=[
                        "glue:GetTable",
                        "glue:GetTables",
                        "glue:GetDatabase",
                        "glue:GetDatabases",
                        "glue:GetPartitions",
                        "glue:BatchGetPartition"
                    ],
                    resources=[
                        f"arn:aws:glue:{self.region}:{self.account}:catalog",
                        f"arn:aws:glue:{self.region}:{self.account}:database/{glue_db_name}",
                        f"arn:aws:glue:{self.region}:{self.account}:table/{glue_db_name}/*"
                    ]
                )
            ]
        )

        # -------------------------------------------------------------------------------------------------


