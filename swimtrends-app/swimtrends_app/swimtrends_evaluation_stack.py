"""Guardrail for the AI meet evaluations.

The evaluations are batch-generated prose about named swimmers — many of them
16-18 year olds at the junior championships. The guardrail is the enforcement
half of that policy (the system prompt is the cooperative half): it denies
talent projection, physique/health speculation, personal criticism, and
personal details beyond club affiliation (age, school, family, home town,
etc. — the most safety-sensitive of the four, since it targets identifying
information about minors) — and runs a contextual grounding check with the
meet digest as the grounding source.

Applied inline on the Converse call at the NUMBERED version below — never
DRAFT, which could change between two meets of the same batch.
"""
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

GROUNDING_THRESHOLD = 0.7
RELEVANCE_THRESHOLD = 0.5


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
            blocked_input_messaging="Input blocked by guardrail.",
            blocked_outputs_messaging="Output blocked by guardrail.",
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="TalentProjection", type="DENY",
                        definition=("Predictions, projections or speculation about a "
                                    "named athlete's future performance, potential, "
                                    "career prospects or selection for teams or "
                                    "championships."),
                        examples=[
                            "Hun er et kommende OL-emne.",
                            "Han bliver landsholdssvømmer inden for to år.",
                        ]),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="PhysiqueAndHealth", type="DENY",
                        definition=("Statements or speculation about a named athlete's "
                                    "body, physique, weight, health, injuries, illness, "
                                    "fitness, training load or technique."),
                        examples=[
                            "Han virker utrænet på de sidste 50 meter.",
                            "Hendes skulderskade præger svømningen.",
                        ]),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="PersonalCriticism", type="DENY",
                        definition=("Criticism, blame, mockery or disparagement "
                                    "directed at a named person, including their "
                                    "execution, effort, attitude or choices."),
                        examples=[
                            "En skødesløs vending kostede hende sejren.",
                            "Han gav tydeligvis op på sidste længde.",
                        ]),
                    # A denied topic, not a SensitiveInformationPolicyConfig PII
                    # filter: swimmer names are already public on the site and
                    # wanted in the prose, so a NAME entity filter would defeat
                    # the feature; an AGE entity filter risks flagging
                    # legitimate aggregate statements (the digest carries a
                    # `juniors` count, and junior categories are age-band
                    # defined). Denying the topic is the targeted tool here.
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="PersonalDetails", type="DENY",
                        definition=("Personal or identifying details about a named "
                                    "athlete beyond club affiliation: age, birth "
                                    "year, year group, school, family, residence, "
                                    "employment, or other private life."),
                        examples=[
                            "Hun er 16 år og går i 9. klasse på Ordrup Skole.",
                            "Han er født i 2009 og bor i Aarhus med sin familie.",
                        ]),
                ]),
            contextual_grounding_policy_config=(
                bedrock.CfnGuardrail.ContextualGroundingPolicyConfigProperty(
                    filters_config=[
                        bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                            type="GROUNDING", threshold=GROUNDING_THRESHOLD),
                        bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                            type="RELEVANCE", threshold=RELEVANCE_THRESHOLD),
                    ])),
        )

        version = bedrock.CfnGuardrailVersion(
            self, "EvaluationGuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description="Published version consumed by the evaluation batch job.")

        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
        CfnOutput(self, "GuardrailVersion", value=version.attr_version)
