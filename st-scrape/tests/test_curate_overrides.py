"""Class-overrides table: set/list/get-for-meet."""
import boto3
import pytest

from curate.overrides import ClassOverrides

REGION = "eu-west-1"
TABLE = "swimtrends-class-overrides-test"


@pytest.fixture
def overrides_table(mocked_aws):
    ddb = boto3.resource("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "meet_id", "KeyType": "HASH"},
                   {"AttributeName": "race_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "meet_id", "AttributeType": "S"},
                              {"AttributeName": "race_id", "AttributeType": "N"}],
        BillingMode="PAY_PER_REQUEST",
    )
    yield ddb.Table(TABLE)


def test_set_then_get_for_meet_returns_race_id_to_class(overrides_table):
    ov = ClassOverrides(TABLE, region=REGION)
    ov.set_override("8609", 213, "para", reason="para-only event")
    ov.set_override("8609", 99, "open", reason="false positive")
    ov.set_override("9999", 1, "para", reason="other meet")
    assert ov.get_for_meet("8609") == {213: "para", 99: "open"}


def test_get_for_meet_empty_when_none(overrides_table):
    ov = ClassOverrides(TABLE, region=REGION)
    assert ov.get_for_meet("8609") == {}
