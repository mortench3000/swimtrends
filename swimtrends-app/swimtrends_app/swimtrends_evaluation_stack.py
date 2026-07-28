"""Guardrail for the AI meet evaluations.

The evaluations are batch-generated prose about named swimmers — many of them
16-18 year olds at the junior championships. The guardrail is the enforcement
half of that policy (the system prompt is the cooperative half): it denies
talent projection, physique/health speculation, personal criticism, and
personal details beyond club affiliation (age, school, family, home town,
etc. — the most safety-sensitive of the four, since it targets identifying
information about minors) — plus standard content filters, and a contextual
grounding check with the meet digest as the grounding source.

The batch job applies this at the NUMBERED version below — never DRAFT, which
could change between two meets of the same batch. It applies it twice: inline
on the Converse call (which only reaches the input, because the report comes
back inside a forced tool call) and explicitly with ApplyGuardrail on the
generated text, which is what supplies the grounding-source and query
qualifiers the contextual grounding filter needs.

The policy lives in the module-level constants below rather than inline in the
stack, because the version description has to be a fingerprint of all of it —
see POLICY_FINGERPRINT.
"""
import hashlib
import json

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

# Measured, not guessed — see test_grounding_is_the_only_contextual_filter.
# The report is checked ONE SECTION AT A TIME (evaluation/agent.py OutputGuard),
# because a four-section concatenation scores far below its own sections and no
# threshold separates good from bad on the whole blob. Per section, real reports
# scored 0.63-0.95 and deliberately ungrounded ones 0.00-0.34, so 0.5 sits in
# the middle of a wide measured gap. Raising this without re-measuring per
# section will block every meet.
GROUNDING_THRESHOLD = 0.5

# No RELEVANCE filter. It measures "does this text answer the query", and with
# one generic query per meet every section answers it about equally: the
# physique-violation probe scored 0.70 while the honest per-stroke section
# scored 0.36. Any threshold blocks honest prose for a reason unrelated to the
# policy, so the filter is absent rather than lowered.

BLOCKED_INPUT_MESSAGE = "Input blocked by guardrail."
BLOCKED_OUTPUT_MESSAGE = "Output blocked by guardrail."

DENIED_TOPICS: list[dict] = [
    {"name": "TalentProjection",
     "definition": ("Predictions, projections or speculation about a named "
                    "athlete's future performance, potential, career prospects "
                    "or selection for teams or championships."),
     "examples": ["Hun er et kommende OL-emne.",
                  "Han bliver landsholdssvømmer inden for to år."]},
    {"name": "PhysiqueAndHealth",
     "definition": ("Statements or speculation about a named athlete's body, "
                    "physique, weight, health, injuries, illness, fitness, "
                    "training load or technique."),
     "examples": ["Han virker utrænet på de sidste 50 meter.",
                  "Hendes skulderskade præger svømningen."]},
    {"name": "PersonalCriticism",
     "definition": ("Criticism, blame, mockery or disparagement directed at a "
                    "named person, including their execution, effort, attitude "
                    "or choices."),
     "examples": ["En skødesløs vending kostede hende sejren.",
                  "Han gav tydeligvis op på sidste længde."]},
    # A denied topic, not a SensitiveInformationPolicyConfig PII filter:
    # swimmer names are already public on the site and wanted in the prose, so
    # a NAME entity filter would defeat the feature; an AGE entity filter risks
    # flagging legitimate aggregate statements (the digest carries a `juniors`
    # count, and junior categories are age-band defined). Denying the topic is
    # the targeted tool here.
    {"name": "PersonalDetails",
     "definition": ("Personal or identifying details about a named athlete "
                    "beyond club affiliation: age, birth year, year group, "
                    "school, family, residence, employment, or other private "
                    "life."),
     "examples": ["Hun er 16 år og går i 9. klasse på Ordrup Skole.",
                  "Han er født i 2009 og bor i Aarhus med sin familie."]},
]

# Output strengths are the ones that matter: the input is our own system prompt
# and a numeric digest, the output is what gets published about named minors.
# HIGH on the three that would be seriously damaging next to a swimmer's name;
# MEDIUM on violence and misconduct, where sports idiom ("knuste feltet") is a
# plausible false positive and the realistic risk is low.
#
# PROMPT_ATTACK is input-only (Bedrock rejects any other output strength) and
# deliberately MEDIUM rather than HIGH: it guards against an injection payload
# arriving inside a scraped club or swimmer name, but Bedrock evaluates the
# whole untagged input — including our instruction-dense system prompt — so
# HIGH risks flagging our own prompt on every call and taking the feature down.
CONTENT_FILTERS: list[dict] = [
    {"type": "HATE", "input_strength": "MEDIUM", "output_strength": "HIGH"},
    {"type": "INSULTS", "input_strength": "MEDIUM", "output_strength": "HIGH"},
    {"type": "SEXUAL", "input_strength": "MEDIUM", "output_strength": "HIGH"},
    {"type": "VIOLENCE", "input_strength": "MEDIUM", "output_strength": "MEDIUM"},
    {"type": "MISCONDUCT", "input_strength": "MEDIUM", "output_strength": "MEDIUM"},
    {"type": "PROMPT_ATTACK", "input_strength": "MEDIUM", "output_strength": "NONE"},
]


def policy_fingerprint() -> str:
    """Short hash of everything the guardrail actually enforces.

    This is what goes in the published version's description. See the comment
    at CfnGuardrailVersion below for why the description is the only lever
    available, and why fingerprinting the whole policy rather than listing the
    two thresholds is the difference between a working mechanism and one that
    silently fails on the field that matters most.
    """
    material = json.dumps({
        "topics": DENIED_TOPICS,
        "content_filters": CONTENT_FILTERS,
        "grounding": GROUNDING_THRESHOLD,
        "blocked_input": BLOCKED_INPUT_MESSAGE,
        "blocked_output": BLOCKED_OUTPUT_MESSAGE,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


class SwimtrendsEvaluationStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        guardrail = bedrock.CfnGuardrail(
            self, "EvaluationGuardrail",
            name="swimtrends-meet-evaluation",
            # Kept under CloudFormation's 200-char limit for this field.
            description=("Guardrail for batch-generated Danish coach evaluations of "
                         "swim meets. Denies projection, health/body, criticism and "
                         "personal details about named swimmers; grounds claims in "
                         "the meet digest."),
            blocked_input_messaging=BLOCKED_INPUT_MESSAGE,
            blocked_outputs_messaging=BLOCKED_OUTPUT_MESSAGE,
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name=topic["name"], type="DENY",
                        definition=topic["definition"],
                        examples=topic["examples"])
                    for topic in DENIED_TOPICS
                ]),
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type=f["type"], input_strength=f["input_strength"],
                        output_strength=f["output_strength"])
                    for f in CONTENT_FILTERS
                ]),
            contextual_grounding_policy_config=(
                bedrock.CfnGuardrail.ContextualGroundingPolicyConfigProperty(
                    filters_config=[
                        bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                            type="GROUNDING", threshold=GROUNDING_THRESHOLD),
                    ])),
        )

        # A published guardrail VERSION is immutable: editing the guardrail's
        # properties above only updates the DRAFT. CfnGuardrailVersion is a
        # separate resource that CloudFormation only replaces (publishing a new
        # version) when ITS OWN properties change — and it has exactly two,
        # the guardrail id (stable) and this description. So the description is
        # the only lever, and it must move whenever ANY part of the policy
        # moves: a changed topic definition, an added or removed topic, a
        # content filter strength, a threshold. Embedding a fingerprint of the
        # whole policy is what makes that true. Do not "tidy" this into a
        # static string, or the batch job's pinned version will silently keep
        # serving the old policy forever while cdk deploy reports success.
        version = bedrock.CfnGuardrailVersion(
            self, "EvaluationGuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description=("Published version consumed by the evaluation batch job "
                         f"(policy={policy_fingerprint()})."))

        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
        CfnOutput(self, "GuardrailVersion", value=version.attr_version)
