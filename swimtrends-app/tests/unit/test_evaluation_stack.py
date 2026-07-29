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


def _guardrail_properties(t):
    guardrails = t.find_resources("AWS::Bedrock::Guardrail")
    assert guardrails, "no guardrail in the template"
    return next(iter(guardrails.values()))["Properties"]


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


def test_grounding_is_the_only_contextual_filter():
    """GROUNDING only, and at a threshold a truthful section actually reaches.

    Measured against the deployed v3 (threshold 0.85, whole report as one
    block): every one of six real reports was blocked on GROUNDING alone, at
    0.40-0.81. Scoring the same reports one section at a time gave 0.63-0.95,
    and a red team of deliberately ungrounded sections against the same digest
    scored 0.00-0.34 (invented number 0.10, causal claim 0.00, inferred
    geography 0.34) against 0.97 for plain recitation. So the check works per
    section and 0.5 sits in the middle of a wide measured gap; 0.85 on a
    four-section concatenation is unreachable regardless of content.

    RELEVANCE is removed rather than lowered because it carries no signal here:
    the physique-violation probe scored 0.70 relevance — higher than the
    *honest* "Discipliner i bevægelse" section at 0.36-0.43. With one generic
    query for every meet it measures "does this answer the question", which
    every section does about equally, so any threshold blocks honest prose for
    a reason unrelated to the policy.
    """
    filters = _guardrail_properties(
        _template())["ContextualGroundingPolicyConfig"]["FiltersConfig"]
    assert filters == [{"Type": "GROUNDING", "Threshold": 0.5}]


def test_talent_projection_is_scoped_to_an_individual_and_excludes_aggregates():
    """The original definition ("a named athlete's future performance") read as
    statistical projection to Bedrock and blocked a real report on prose about
    the *field*: "Elitens median var 1 procent højere end i 2025." next to
    "Der deltog 581 svømmere fordelt på 42 øvelser." fired TalentProjection,
    deterministically, with no named swimmer's future anywhere in the text.
    Neither sentence fires alone — only the pair.

    Measured against a scratch guardrail on all 12 sections of three real
    reports: the old definition gave 1 false positive, this one gives 0, and
    the violation battery (talent projection, physique, criticism, personal
    details) is unchanged. So the definition must name an individual and put
    meet-level statistics out of scope explicitly.
    """
    definition = next(t["definition"] for t in mod.DENIED_TOPICS
                      if t["name"] == "TalentProjection")
    assert "named individual swimmer" in definition
    assert "not in scope" in definition


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


# The fingerprint below is computed from the module constants, and the guardrail
# resource is synthesized from those same constants -- but nothing tied the two
# together, so a mistake in the *wiring* changed the DRAFT, left the fingerprint
# where it was, published no new version, and let the batch job's pinned version
# keep serving the old policy while cdk deploy reported success. Three synth-site
# mutations survived the whole suite: dropping a topic's examples, forcing every
# content filter's output strength to NONE, and replacing the blocked-output
# message. The three tests below compare the synthesized template to the
# constants field by field, so the two cannot diverge.
def test_every_denied_topic_reaches_the_template_field_by_field():
    topics = _guardrail_properties(_template())["TopicPolicyConfig"]["TopicsConfig"]
    assert topics == [
        {"Name": t["name"], "Type": "DENY", "Definition": t["definition"],
         "Examples": t["examples"]}
        for t in mod.DENIED_TOPICS
    ]


def test_every_content_filter_reaches_the_template_field_by_field():
    filters = _guardrail_properties(_template())["ContentPolicyConfig"]["FiltersConfig"]
    assert filters == [
        {"Type": f["type"], "InputStrength": f["input_strength"],
         "OutputStrength": f["output_strength"]}
        for f in mod.CONTENT_FILTERS
    ]


def test_both_blocked_messages_reach_the_template():
    props = _guardrail_properties(_template())
    assert props["BlockedInputMessaging"] == mod.BLOCKED_INPUT_MESSAGE
    assert props["BlockedOutputsMessaging"] == mod.BLOCKED_OUTPUT_MESSAGE


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
