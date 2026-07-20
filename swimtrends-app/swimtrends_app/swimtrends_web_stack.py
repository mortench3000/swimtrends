"""Swimtrends public web app hosting: private S3 + CloudFront (OAC) + Route53
alias for swimtrends.dk. Static SPA + precomputed /data/*.json are pushed by
the deploy/refresh script (see docs/superpowers/deploy-web.md), not by CDK."""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct

DOMAIN = "swimtrends.dk"
HOSTED_ZONE_ID = "Z05943842L8KIUA914B4J"


class SwimtrendsWebStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 certificate: acm.ICertificate, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self, "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        spa_fallback = [
            cloudfront.ErrorResponse(
                http_status=code, response_http_status=200,
                response_page_path="/index.html", ttl=Duration.minutes(5))
            for code in (403, 404)
        ]

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_root_object="index.html",
            domain_names=[DOMAIN],
            certificate=certificate,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
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

        CfnOutput(self, "SiteBucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SiteUrl", value=f"https://{DOMAIN}")
