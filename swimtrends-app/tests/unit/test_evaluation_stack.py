import copy

import aws_cdk as cdk
import pytest
from aws_cdk import assertions

from swimtrends_app import swimtrends_evaluation_stack as mod
from swimtrends_app.swimtrends_evaluation_stack import SwimtrendsEvaluationStack


def _template():
    app = cdk.App()
    stack = SwimtrendsEvaluationStack(app, "TestEval")
    return assertions.Template.from_stack(stack)


def _version_description(t):
    versions = t.find_resources("AWS::Bedrock::GuardrailVersion")
    assert versions, "no guardrail version in the template"
    return next(iter(versions.values()))["Properties"]["Description"]


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


def test_guardrail_configures_content_filters():
    """There is no such thing as content filters "at service defaults": omitting
    the block means a guardrail with no content filters at all, which is what
    the deployed v2 had."""
    t = _template()
    guardrails = t.find_resources("AWS::Bedrock::Guardrail")
    props = next(iter(guardrails.values()))["Properties"]
    filters = props["ContentPolicyConfig"]["FiltersConfig"]
    assert {f["Type"] for f in filters} == {
        "HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT", "PROMPT_ATTACK"}


def test_prompt_attack_detection_is_input_only():
    """Bedrock only supports PROMPT_ATTACK on the input; an output strength
    other than NONE is rejected at deploy time, not at synth."""
    t = _template()
    guardrails = t.find_resources("AWS::Bedrock::Guardrail")
    filters = next(iter(guardrails.values()))["Properties"][
        "ContentPolicyConfig"]["FiltersConfig"]
    attack = next(f for f in filters if f["Type"] == "PROMPT_ATTACK")
    assert attack["OutputStrength"] == "NONE"
    assert attack["InputStrength"] != "NONE"


def test_a_numbered_version_is_published():
    t = _template()
    t.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)


def _tighten_a_topic_definition(monkeypatch):
    topics = copy.deepcopy(mod.DENIED_TOPICS)
    topics[0]["definition"] += " Including hypothetical future performance."
    monkeypatch.setattr(mod, "DENIED_TOPICS", topics)


def _add_a_denied_topic(monkeypatch):
    topics = copy.deepcopy(mod.DENIED_TOPICS) + [
        {"name": "SomethingElse", "definition": "A newly denied topic.",
         "examples": ["Et eksempel."]}]
    monkeypatch.setattr(mod, "DENIED_TOPICS", topics)


def _weaken_a_content_filter(monkeypatch):
    filters = copy.deepcopy(mod.CONTENT_FILTERS)
    filters[0]["output_strength"] = "LOW"
    monkeypatch.setattr(mod, "CONTENT_FILTERS", filters)


def _lower_the_grounding_threshold(monkeypatch):
    monkeypatch.setattr(mod, "GROUNDING_THRESHOLD", 0.7)


def _change_the_block_message(monkeypatch):
    monkeypatch.setattr(mod, "BLOCKED_OUTPUT_MESSAGE", "Nope.")


@pytest.mark.parametrize("mutate", [
    _tighten_a_topic_definition,
    _add_a_denied_topic,
    _weaken_a_content_filter,
    _lower_the_grounding_threshold,
    _change_the_block_message,
], ids=lambda f: f.__name__.strip("_"))
def test_version_description_tracks_every_part_of_the_policy(monkeypatch, mutate):
    """A published guardrail VERSION is immutable, and CfnGuardrailVersion has
    exactly two properties — the guardrail id (stable) and the description — so
    the description is the only lever that republishes it. Embedding just the
    two thresholds left it blind to the more dangerous field: a topic
    definition, the set of topics, or the content policy could change, update
    the DRAFT, and leave the published version serving the old policy while
    every test passed and cdk deploy reported success. Thresholds are a dial;
    topics are the policy. So the description carries a fingerprint of the
    whole config, and every part of it has to move the fingerprint."""
    before = _version_description(_template())
    mutate(monkeypatch)
    assert _version_description(_template()) != before


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
