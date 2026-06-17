"""Assertion tests for the ingestion stack. VPC context is stubbed so
from_lookup does not require AWS credentials."""
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from swimtrends_app.swimtrends_ingestion_stack import SwimtrendsIngestionStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")


def _synth():
    app = cdk.App(context={
        # Stub the default-VPC lookup with a minimal 2-AZ VPC.
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
    })
    stack = SwimtrendsIngestionStack(app, "TestIngestionStack",
                                     alert_email="ops@example.com", env=ENV)
    return Template.from_stack(stack)


def test_registry_table_created():
    t = _synth()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "swimtrends-meet-registry",
        "KeySchema": [{"AttributeName": "meet_id", "KeyType": "HASH"}],
    })


def test_fargate_task_definition_sized():
    t = _synth()
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "512",
        "Memory": "1024",
        "RequiresCompatibilities": ["FARGATE"],
    })


def test_dispatcher_lambda_handler_and_timeout():
    t = _synth()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "ingestion.dispatcher.lambda_handler",
        "Runtime": "python3.12",
        "Timeout": 60,
    })


def test_hourly_schedule_rule():
    t = _synth()
    t.has_resource_properties("AWS::Events::Rule", {
        "ScheduleExpression": "rate(1 hour)",
    })


def test_sns_topic_and_email_subscription():
    t = _synth()
    t.resource_count_is("AWS::SNS::Topic", 1)
    t.has_resource_properties("AWS::SNS::Subscription", {
        "Protocol": "email",
        "Endpoint": "ops@example.com",
    })


def test_dispatcher_can_run_ecs_tasks():
    t = _synth()
    t.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({"Action": "ecs:RunTask"}),
            ]),
        },
    })


def test_dispatcher_has_raw_bucket_for_reaper():
    # The reaper reconciles orphaned meets from the raw zone, so the dispatcher
    # needs the bucket name and read access to raw/*.
    t = _synth()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "ingestion.dispatcher.lambda_handler",
        "Environment": {"Variables": Match.object_like({
            "RAW_BUCKET": "swimtrends-meet-data",
            "REAP_TTL_HOURS": "6",
        })},
    })
    t.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({
                    "Action": Match.array_with(
                        [Match.string_like_regexp("^s3:GetObject")]),
                }),
            ]),
        },
    })
