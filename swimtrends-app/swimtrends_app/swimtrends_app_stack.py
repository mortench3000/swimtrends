from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_s3 as s3
from constructs import Construct


class SwimtrendsAppStack(Stack):
    """Owns the central data bucket. The old Glue/Athena analytics path this
    stack used to define was retired (curated Parquet + swimtrends_curated Glue
    DB in SwimtrendsCuratedStack, local DuckDB for querying); only the bucket
    remains. Keep the logical ID and bucket name stable — it is RETAIN'd and
    imported by name elsewhere."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        s3.Bucket(
            self, "swimtrends-meet-data-bucket",
            bucket_name="swimtrends-meet-data",
            versioned=True,
            public_read_access=False,
            removal_policy=RemovalPolicy.RETAIN,
        )
