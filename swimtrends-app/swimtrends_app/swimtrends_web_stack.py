"""Swimtrends public web app hosting: private S3 + CloudFront (OAC) + Route53
alias for swimtrends.dk. Static SPA + precomputed /data/*.json are pushed by
the deploy/refresh script (see docs/superpowers/deploy-web.md), not by CDK."""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_iam as iam
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct

DOMAIN = "swimtrends.dk"
HOSTED_ZONE_ID = "Z05943842L8KIUA914B4J"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_REPO = "mortench3000/swimtrends"


class SwimtrendsWebStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 certificate: acm.ICertificate, alert_email: str | None = None,
                 **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self, "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # Kept for the routes that are *not* prerendered (races, unknown paths):
        # the SPA reads location.pathname and renders them client-side.
        spa_fallback = [
            cloudfront.ErrorResponse(
                http_status=code, response_http_status=200,
                response_page_path="/index.html", ttl=Duration.minutes(5))
            for code in (403, 404)
        ]

        # Without this, the prerendered pages (web/prerender.mjs) are unreachable
        # — see cloudfront/append_index.js.
        append_index = cloudfront.Function(
            self, "AppendIndex",
            code=cloudfront.FunctionCode.from_file(
                file_path=str(Path(__file__).parents[1] / "cloudfront" / "append_index.js")),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            comment="Append /index.html to extensionless paths (S3 OAC has no directory index)",
        )

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_root_object="index.html",
            domain_names=[DOMAIN],
            certificate=certificate,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[cloudfront.FunctionAssociation(
                    function=append_index,
                    event_type=cloudfront.FunctionEventType.VIEWER_REQUEST)],
            ),
            error_responses=spa_fallback,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=HOSTED_ZONE_ID, zone_name=DOMAIN)
        alias = route53.RecordTarget.from_alias(
            targets.CloudFrontTarget(distribution))
        route53.ARecord(self, "AliasA", zone=zone, target=alias, record_name=DOMAIN)
        route53.AaaaRecord(self, "AliasAAAA", zone=zone, target=alias, record_name=DOMAIN)

        # GitHub Actions deploys the SPA on merge to master. OIDC, so no
        # long-lived access keys live in GitHub. The sub condition is the
        # security boundary: only master-branch runs of this repo can assume
        # the role — a fork's PR cannot, and PR runs never ask for credentials.
        # The OIDC provider is an account-level singleton, not scoped to this
        # stack: a second stack adding its own would fail with
        # EntityAlreadyExists, and destroying this stack would delete it out
        # from under any other role trusting it.
        oidc = iam.CfnOIDCProvider(
            self, "GitHubOidcProvider",
            url=GITHUB_OIDC_URL,
            client_id_list=["sts.amazonaws.com"],
        )
        issuer = GITHUB_OIDC_URL.removeprefix("https://")
        deploy_role = iam.Role(
            self, "GitHubDeployRole",
            assumed_by=iam.FederatedPrincipal(
                oidc.attr_arn,
                conditions={
                    "StringEquals": {f"{issuer}:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        f"{issuer}:sub": f"repo:{GITHUB_REPO}:ref:refs/heads/master"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            description="GitHub Actions: build + publish the SPA to the site bucket",
        )
        # `aws s3 sync --delete` needs list, put and delete on the bucket.
        bucket.grant_read_write(deploy_role)
        # The bucket also serves /data/*.json (~1698 files, ~50 min to
        # rebuild) and has versioning off. The only thing keeping the SPA
        # sync's `--delete` from wiping that zone today is the Makefile's
        # `--exclude "data/*"` flag — a shell flag, not a permission. This
        # explicit Deny is a second, independent guard: an IAM Deny always
        # wins over the Allow from grant_read_write above, so a recipe that
        # ever loses the exclude flag fails closed with AccessDenied instead
        # of deleting the data zone.
        deploy_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.DENY,
            actions=["s3:DeleteObject*"],
            resources=[bucket.arn_for_objects("data/*")],
        ))
        deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation"],
            resources=[distribution.distribution_arn],
        ))
        # The Makefile resolves the bucket name and distribution id from this
        # stack's outputs at deploy time, so CI needs to read them.
        deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudformation:DescribeStacks"],
            resources=[self.stack_id],
        ))

        # Account-wide monthly cost budget: early warning if a bot flood (or
        # anything else) pushes AWS spend past normal — the site normally costs
        # cents/month. Budgets can't cap spend, only alert; email rides on the
        # same -c alert_email the other stacks use, so omitting it drops this
        # notification too. 50%/100% of a low limit catches anomalies fast.
        if alert_email:
            thresholds = [
                ("ACTUAL", 50), ("ACTUAL", 100), ("FORECASTED", 100),
            ]
            budgets.CfnBudget(
                self, "MonthlyCostBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_type="COST", time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(
                        amount=20, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            notification_type=ntype,
                            comparison_operator="GREATER_THAN", threshold=pct),
                        subscribers=[budgets.CfnBudget.SubscriberProperty(
                            subscription_type="EMAIL", address=alert_email)],
                    )
                    for ntype, pct in thresholds
                ],
            )

        CfnOutput(self, "SiteBucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SiteUrl", value=f"https://{DOMAIN}")
        CfnOutput(self, "GitHubDeployRoleArn", value=deploy_role.role_arn)
