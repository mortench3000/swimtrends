import aws_cdk as cdk
from aws_cdk import assertions

from swimtrends_app.swimtrends_evaluation_stack import SwimtrendsEvaluationStack


def _template():
    app = cdk.App()
    stack = SwimtrendsEvaluationStack(app, "TestEval")
    return assertions.Template.from_stack(stack)


def test_guardrail_blocks_the_four_denied_topics():
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
                assertions.Match.object_like({"Name": "PersonalDetails",
                                              "Type": "DENY"}),
            ])
        }
    })


def test_guardrail_has_grounding_and_relevance_thresholds():
    _template().has_resource_properties("AWS::Bedrock::Guardrail", {
        "ContextualGroundingPolicyConfig": {
            "FiltersConfig": assertions.Match.array_with([
                {"Type": "GROUNDING", "Threshold": 0.85},
                {"Type": "RELEVANCE", "Threshold": 0.5},
            ])
        }
    })


def test_a_numbered_version_is_published():
    t = _template()
    t.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)


def test_version_description_embeds_the_grounding_threshold():
    """A published guardrail VERSION is immutable — CloudFormation only
    replaces it (publishing a new version) when its OWN properties change.
    The threshold value must live in the version's description, or a future
    threshold change would silently keep the batch job on the old value."""
    t = _template()
    versions = t.find_resources("AWS::Bedrock::GuardrailVersion")
    assert versions, "no guardrail version in the template"
    for res in versions.values():
        assert "0.85" in res["Properties"]["Description"]


def test_outputs_expose_the_id_and_version():
    t = _template()
    outputs = t.find_outputs("*")
    assert outputs["GuardrailId"]["Value"] == {
        "Fn::GetAtt": ["EvaluationGuardrail", "GuardrailId"],
    }
    assert outputs["GuardrailVersion"]["Value"] == {
        "Fn::GetAtt": ["EvaluationGuardrailVersion", "Version"],
    }


def test_guardrail_strings_stay_within_the_conservative_documented_limits():
    """Neither cdk synth nor cfn-lint validates these lengths, and the AWS API
    reference (200 for a topic definition) disagrees with the CloudFormation
    reference (1000). Assert the conservative limit so a future topic can't
    ship a string that only fails at deploy time."""
    t = _template()
    guardrails = t.find_resources("AWS::Bedrock::Guardrail")
    assert guardrails, "no guardrail in the template"
    for res in guardrails.values():
        props = res["Properties"]
        assert len(props["Description"]) <= 200
        for topic in props["TopicPolicyConfig"]["TopicsConfig"]:
            assert len(topic["Definition"]) <= 200, topic["Name"]
            for example in topic.get("Examples", []):
                assert len(example) <= 100, topic["Name"]
