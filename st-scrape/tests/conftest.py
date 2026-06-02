"""Shared test fixtures: fake AWS credentials and region so moto/boto3 never
touch real AWS, and a DynamoDB registry table created in moto."""
import boto3
import pytest
from moto import mock_aws

REGION = "eu-west-1"
TABLE_NAME = "swimtrends-meet-registry-test"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Force fake credentials + region for every test."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture(autouse=True)
def mocked_aws(aws_env):
    """Activate moto for every test so no call ever reaches real AWS."""
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_table(mocked_aws):
    """Create the registry table in moto and yield the boto3 Table resource."""
    ddb = boto3.resource("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "meet_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "meet_id", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    yield ddb.Table(TABLE_NAME)
