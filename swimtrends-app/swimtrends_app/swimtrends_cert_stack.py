"""ACM certificate for swimtrends.dk, in us-east-1 for CloudFront.

Separate stack because CloudFront viewer certificates MUST live in us-east-1;
the web stack (eu-west-1) consumes .certificate via cross-region references."""
from aws_cdk import Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_route53 as route53
from constructs import Construct

DOMAIN = "swimtrends.dk"
HOSTED_ZONE_ID = "Z05943842L8KIUA914B4J"


class SwimtrendsCertStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=HOSTED_ZONE_ID, zone_name=DOMAIN)
        self.certificate = acm.Certificate(
            self, "SiteCert",
            domain_name=DOMAIN,
            validation=acm.CertificateValidation.from_dns(zone),
        )
