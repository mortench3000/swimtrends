"""Synth assertions for the curated stack: overrides table, curate task,
trigger Lambda, Glue database + tables. VPC context is stubbed so from_lookup
does not require AWS credentials."""
import aws_cdk as cdk
from aws_cdk import assertions

from swimtrends_app.swimtrends_curated_stack import SwimtrendsCuratedStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")

_VPC_CONTEXT = {
    "vpc-provider:account=179537025528:filter.isDefault=true:region=eu-west-1:returnAsymmetricSubnets=true": {
        "vpcId": "vpc-12345",
        "vpcCidrBlock": "10.0.0.0/16",
        "availabilityZones": [],
        "subnetGroups": [{
            "name": "Public",
            "type": "Public",
            "subnets": [
                {"subnetId": "subnet-1", "availabilityZone": "eu-west-1a",
                 "routeTableId": "rtb-1", "cidr": "10.0.0.0/24"},
                {"subnetId": "subnet-2", "availabilityZone": "eu-west-1b",
                 "routeTableId": "rtb-2", "cidr": "10.0.1.0/24"},
            ],
        }],
    }
}


def _template():
    app = cdk.App(context=_VPC_CONTEXT)
    stack = SwimtrendsCuratedStack(app, "TestCurated", alert_email=None, env=ENV)
    return assertions.Template.from_stack(stack)


def test_overrides_table_has_composite_key():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "swimtrends-class-overrides",
        "KeySchema": [
            {"AttributeName": "meet_id", "KeyType": "HASH"},
            {"AttributeName": "race_id", "KeyType": "RANGE"},
        ],
    })


def test_glue_database_and_five_tables():
    t = _template()
    t.resource_count_is("AWS::Glue::Database", 1)
    t.resource_count_is("AWS::Glue::Table", 5)


def test_trigger_lambda_exists():
    t = _template()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "curate_trigger.lambda_handler",
    })
