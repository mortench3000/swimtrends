import aws_cdk as core
import aws_cdk.assertions as assertions

from swimtrends_app.swimtrends_app_stack import SwimtrendsAppStack

# example tests. To run these tests, uncomment this file along with the example
# resource in swimtrends_app/swimtrends_app_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = SwimtrendsAppStack(app, "swimtrends-app")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
