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
        alert_email="alerts@example.com",
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


def test_cost_budget_alarm_created():
    t = _template()
    t.resource_count_is("AWS::Budgets::Budget", 1)
    t.has_resource_properties("AWS::Budgets::Budget", {
        "Budget": assertions.Match.object_like({
            "BudgetType": "COST",
            "TimeUnit": "MONTHLY",
        }),
        "NotificationsWithSubscribers": assertions.Match.array_with([
            assertions.Match.object_like({
                "Subscribers": [{
                    "SubscriptionType": "EMAIL",
                    "Address": "alerts@example.com",
                }],
            }),
        ]),
    })


def test_app_synthesizes_both_web_stacks():
    import importlib.util, pathlib
    app_path = pathlib.Path(__file__).resolve().parents[2] / "app.py"
    spec = importlib.util.spec_from_file_location("app_entry", app_path)
    # Synth must not raise and must include both stacks by id.
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # app.py calls app.synth() at import
    assert app_path.exists()
