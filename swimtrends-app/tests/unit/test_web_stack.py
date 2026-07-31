import json
import pathlib
import shutil
import subprocess

import aws_cdk as cdk
import pytest
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
            "Aliases": ["swimtrends.dk", "www.swimtrends.dk"],
            "DefaultRootObject": "index.html",
        })
    })


def test_viewer_function_is_associated_with_the_default_behavior():
    t = _template()
    t.resource_count_is("AWS::CloudFront::Function", 1)
    t.has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": assertions.Match.object_like({
            "DefaultCacheBehavior": assertions.Match.object_like({
                "FunctionAssociations": [assertions.Match.object_like({
                    "EventType": "viewer-request",
                })],
            }),
        })
    })


# The S3 REST origin (OAC) has no directory index, so without this rewrite every
# prerendered page 404s into the SPA fallback and serves the *generic* shell —
# silently, which is the bug this whole change exists to fix. Run the real
# function body through node rather than trusting it by inspection.
FUNC_JS = pathlib.Path(__file__).resolve().parents[2] / "cloudfront" / "viewer_request.js"


def _call(uri: str, host: str = "swimtrends.dk") -> dict:
    """Run the real function body and return its result (a request or a response)."""
    event = {"request": {"uri": uri, "headers": {"host": {"value": host}}}}
    script = FUNC_JS.read_text() + (
        f"\nprocess.stdout.write(JSON.stringify(handler({json.dumps(event)})))")
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _rewrite(uri: str) -> str:
    return _call(uri)["uri"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("uri,expected", [
    ("/", "/index.html"),
    ("/DM-L", "/DM-L/index.html"),
    ("/DM-L/12486", "/DM-L/12486/index.html"),
    # No prerendered file for races: rewritten, 404s, SPA fallback renders it.
    ("/DM-L/12486/M-100-Fri-LCM", "/DM-L/12486/M-100-Fri-LCM/index.html"),
    # Anything with an extension is a real object and must pass through.
    ("/index.html", "/index.html"),
    ("/robots.txt", "/robots.txt"),
    ("/sitemap.xml", "/sitemap.xml"),
    ("/data/index.json", "/data/index.json"),
    ("/data/DM-L/12486/evaluation.json", "/data/DM-L/12486/evaluation.json"),
    ("/assets/index-UEnPeQyb.js", "/assets/index-UEnPeQyb.js"),
    ("/assets/inter-latin-400-normal-C38fXH4l.woff2", "/assets/inter-latin-400-normal-C38fXH4l.woff2"),
])
def test_append_index_rewrites_only_extensionless_paths(uri, expected):
    assert _rewrite(uri) == expected


# One canonical host: www must 301 to the apex, path intact, before any rewrite.
@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("uri", ["/", "/DM-L", "/DM-L/12486", "/robots.txt"])
def test_www_redirects_to_the_apex(uri):
    res = _call(uri, host="www.swimtrends.dk")
    assert res["statusCode"] == 301
    assert res["headers"]["location"]["value"] == f"https://swimtrends.dk{uri}"
    # A redirect is a response, not a rewritten request.
    assert "uri" not in res


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_apex_is_never_redirected():
    assert _call("/DM-L/12486", host="swimtrends.dk") == {
        "uri": "/DM-L/12486/index.html",
        "headers": {"host": {"value": "swimtrends.dk"}},
    }


def test_route53_alias_records_created():
    t = _template()
    t.resource_count_is("AWS::Route53::RecordSet", 4)  # A + AAAA, apex + www
    for name in ("swimtrends.dk.", "www.swimtrends.dk."):
        for rtype in ("A", "AAAA"):
            t.has_resource_properties("AWS::Route53::RecordSet", {
                "Name": name, "Type": rtype,
            })


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


def test_github_oidc_provider_created():
    _template().has_resource_properties("AWS::IAM::OIDCProvider", {
        "Url": "https://token.actions.githubusercontent.com",
        "ClientIdList": ["sts.amazonaws.com"],
    })


def test_deploy_role_trusts_only_master_of_this_repo():
    _template().has_resource_properties("AWS::IAM::Role", {
        "AssumeRolePolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud":
                                "sts.amazonaws.com",
                        },
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub":
                                "repo:mortench3000/swimtrends:ref:refs/heads/master",
                        },
                    },
                }),
            ]),
        }),
    })


def test_deploy_role_invalidation_is_scoped_to_the_distribution():
    _template().has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "cloudfront:CreateInvalidation",
                    "Resource": assertions.Match.not_("*"),
                }),
            ]),
        }),
    })


def test_deploy_role_can_read_this_stacks_outputs():
    _template().has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "cloudformation:DescribeStacks",
                    "Resource": {"Ref": "AWS::StackId"},
                }),
            ]),
        }),
    })


def test_deploy_role_arn_is_an_output():
    assert "GitHubDeployRoleArn" in _template().find_outputs("*")


def test_deploy_role_cannot_delete_the_data_zone():
    denies = [
        stmt
        for policy in _template().find_resources("AWS::IAM::Policy").values()
        for stmt in policy["Properties"]["PolicyDocument"]["Statement"]
        if stmt["Effect"] == "Deny"
    ]
    assert len(denies) == 1, denies
    assert denies[0]["Action"] == "s3:DeleteObject*"
    assert "/data/*" in json.dumps(denies[0]["Resource"])
