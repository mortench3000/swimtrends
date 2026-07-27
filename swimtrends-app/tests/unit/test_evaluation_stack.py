import aws_cdk as cdk
from aws_cdk import assertions

from swimtrends_app.swimtrends_evaluation_stack import SwimtrendsEvaluationStack


def _template():
    app = cdk.App()
    stack = SwimtrendsEvaluationStack(app, "TestEval")
    return assertions.Template.from_stack(stack)


def test_guardrail_blocks_the_three_denied_topics():
    t = _template()
    t.has_resource_properties("AWS::Bedrock::Guardrail", {
        "TopicPolicyConfig": {
            "TopicsConfig": assertions.Match.array_with([
                assertions.Match.object_like({"Name": "TalentProjection",
                                              "Type": "DENY"}),
                assertions.Match.object_like({"Name": "PhysiqueAndHealth",
                                              "Type": "DENY"}),
                assertions.Match.object_like({"Name": "PersonalCriticism",
                                              "Type": "DENY"}),
            ])
        }
    })


def test_guardrail_has_grounding_and_relevance_thresholds():
    _template().has_resource_properties("AWS::Bedrock::Guardrail", {
        "ContextualGroundingPolicyConfig": {
            "FiltersConfig": assertions.Match.array_with([
                {"Type": "GROUNDING", "Threshold": 0.7},
                {"Type": "RELEVANCE", "Threshold": 0.5},
            ])
        }
    })


def test_a_numbered_version_is_published():
    t = _template()
    t.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)


def test_outputs_expose_the_id_and_version():
    t = _template()
    outputs = t.find_outputs("*")
    assert "GuardrailId" in outputs
    assert "GuardrailVersion" in outputs
