import aws_cdk as core
import aws_cdk.assertions as assertions

from swimtrends_app.swimtrends_app_stack import SwimtrendsAppStack


def _template():
    app = core.App()
    stack = SwimtrendsAppStack(app, "swimtrends-app")
    return assertions.Template.from_stack(stack)


def test_data_bucket_retained():
    template = _template()
    template.has_resource_properties("AWS::S3::Bucket", {
        "BucketName": "swimtrends-meet-data",
        "VersioningConfiguration": {"Status": "Enabled"},
    })
    template.has_resource("AWS::S3::Bucket", {"DeletionPolicy": "Retain"})


def test_only_the_bucket_remains():
    template = _template()
    template.resource_count_is("AWS::S3::Bucket", 1)
    # The legacy Glue/Athena analytics path was retired — assert it's gone.
    for dead in ("AWS::Glue::Database", "AWS::Glue::Crawler",
                 "AWS::Athena::WorkGroup", "AWS::IAM::Role"):
        template.resource_count_is(dead, 0)
