import aws_cdk as cdk
from aws_cdk import assertions
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack

ENV_US = cdk.Environment(account="179537025528", region="us-east-1")


def _template():
    app = cdk.App()
    stack = SwimtrendsCertStack(app, "TestCert", env=ENV_US,
                                cross_region_references=True)
    return assertions.Template.from_stack(stack)


def test_cert_for_domain():
    _template().has_resource_properties("AWS::CertificateManager::Certificate", {
        "DomainName": "swimtrends.dk",
        "ValidationMethod": "DNS",
    })


# CloudFront will only serve an alias its viewer certificate covers, so the www
# alias on the distribution is only valid while this SAN exists.
def test_cert_covers_www():
    _template().has_resource_properties("AWS::CertificateManager::Certificate", {
        "SubjectAlternativeNames": ["www.swimtrends.dk"],
    })
