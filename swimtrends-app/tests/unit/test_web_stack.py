import aws_cdk as cdk
from aws_cdk import assertions
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack
from swimtrends_app.swimtrends_web_stack import SwimtrendsWebStack

ACC = "179537025528"


def _template():
    app = cdk.App()
    cert = SwimtrendsCertStack(
        app, "TestCert",
        env=cdk.Environment(account=ACC, region="us-east-1"),
        cross_region_references=True)
    web = SwimtrendsWebStack(
        app, "TestWeb", certificate=cert.certificate,
        env=cdk.Environment(account=ACC, region="eu-west-1"),
        cross_region_references=True)
    return assertions.Template.from_stack(web)


def test_site_bucket_blocks_public_access():
    _template().has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        }
    })


def test_distribution_has_domain_and_spa_fallback():
    t = _template()
    t.has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": assertions.Match.object_like({
            "Aliases": ["swimtrends.dk"],
            "DefaultRootObject": "index.html",
        })
    })


def test_route53_alias_record_created():
    _template().resource_count_is("AWS::Route53::RecordSet", 2)  # A + AAAA
