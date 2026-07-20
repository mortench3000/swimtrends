#!/usr/bin/env python3

import aws_cdk as cdk

from swimtrends_app.swimtrends_app_stack import SwimtrendsAppStack
from swimtrends_app.swimtrends_curated_stack import SwimtrendsCuratedStack
from swimtrends_app.swimtrends_ingestion_stack import SwimtrendsIngestionStack
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack
from swimtrends_app.swimtrends_web_stack import SwimtrendsWebStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")
ENV_US = cdk.Environment(account="179537025528", region="us-east-1")

app = cdk.App()

SwimtrendsAppStack(app, "SwimtrendsAppStack", env=ENV)

SwimtrendsIngestionStack(
    app, "SwimtrendsIngestionStack",
    alert_email=app.node.try_get_context("alert_email"),
    env=ENV,
)

SwimtrendsCuratedStack(
    app, "SwimtrendsCuratedStack",
    alert_email=app.node.try_get_context("alert_email"),
    env=ENV,
)

cert_stack = SwimtrendsCertStack(
    app, "SwimtrendsCertStack", env=ENV_US, cross_region_references=True)
SwimtrendsWebStack(
    app, "SwimtrendsWebStack", certificate=cert_stack.certificate,
    env=ENV, cross_region_references=True)

app.synth()
