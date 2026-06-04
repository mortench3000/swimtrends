#!/usr/bin/env python3

import aws_cdk as cdk

from swimtrends_app.swimtrends_app_stack import SwimtrendsAppStack
from swimtrends_app.swimtrends_curated_stack import SwimtrendsCuratedStack
from swimtrends_app.swimtrends_ingestion_stack import SwimtrendsIngestionStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")

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

app.synth()
