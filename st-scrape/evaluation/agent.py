"""The evaluation agent: one digest in, one Danish coach report out.

A single Strands agent, a single Converse call per meet, no tools and no
memory — the digest is the agent's entire world, which is what makes both the
guardrail's grounding check and the deterministic number check meaningful.

Two guardrail applications, deliberately: the Converse call carries the
guardrail inline (which on this path only ever assesses the *input* — see
OutputGuard), and every report that survives the number check is put through
ApplyGuardrail before it is returned. That second call is the one that
enforces the four denied topics and contextual grounding on the text we
publish.

PROMPT_VERSION / SCHEMA_VERSION are part of the cache key: bump either and
every meet regenerates on the next run. Do that deliberately.
"""
import logging

from pydantic import BaseModel, field_validator
from strands import Agent
from strands.models import BedrockModel

from evaluation.cache import canonical_json
from evaluation.check import check_numbers

log = logging.getLogger("evaluation")

PROMPT_VERSION = "6"
SCHEMA_VERSION = "1"

REGION = "eu-west-1"
MAX_TOKENS = 1200

# The instruction the report answers, sent to ApplyGuardrail tagged `query` so
# the RELEVANCE half of the contextual grounding filter has something to
# compare the report against.
GUARD_QUERY = "Skriv en trænervurdering af stævnet."

HEADINGS = (
    "Samlet niveau",
    "Bredde",
    "Fremhævede svømninger",
    "Discipliner i bevægelse",
)

# Human-readable label shown in the page footer next to the generation date.
# Extend as models are added; unmapped ids fall back to the raw id.
MODEL_LABELS: dict[str, str] = {
    "eu.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
    "eu.anthropic.claude-sonnet-4-6": "Claude Sonnet 4.6",
}

SYSTEM_PROMPT = f"""\
You are an experienced Danish swimming coach writing a short evaluation of a
national championship meet for a public analytics site. You write in DANISH.

You will be given a <digest> containing every fact you may use. Write about
250 words total, split into exactly these four sections, in this order, with
these headings verbatim:

{chr(10).join('  - ' + h for h in HEADINGS)}

Rules — these are absolute:

1. NUMBERS. Use only numbers that appear literally in the digest. Never
   calculate, estimate, round or infer a number. If you want to express a
   percentage change, use only the precomputed values in digest.derived. A
   stroke's movement vs. the prior seasons is digest.by_stroke[].delta —
   never subtract two medians yourself. If a number you want does not exist
   in the digest, describe the direction in words instead ("højere end",
   "under de seneste sæsoners niveau").
2. COMPARISONS. Compare against the seasons in digest.season_history only.
   If there is little or no history, say so plainly rather than implying a
   trend.
3. NAMED SWIMMERS. You may name swimmers from digest.top_swims and state their
   time, points, placement and event. Nothing else. Never write about a
   swimmer's potential or future, their technique, body, health, injuries, age,
   training or schooling, and never phrase anything as criticism of a named
   person. Many of these swimmers are minors.
4. TONE. Informed, sober, specific. No hype, no exclamation marks, no emoji.
   Write as an analyst who respects the reader's knowledge of the sport.
5. Danish stroke names are used in the data and in your text: Fri, Ryg, Bryst,
   Fly, IM, HM.
6. QUALITATIVE CLAIMS. The digest bounds non-numeric claims too, not just
   numbers. Never state or imply geography (club names are not locations),
   causes or explanations (why participation rose, what a trend means for
   the sport), or anything else the digest does not contain. In particular,
   never infer geography, regional spread, representation or reach from a
   club or participant count — a count is a count, nothing more. Never
   editorialise: state what the numbers show, don't opine on what they imply,
   and never pose a rhetorical question.
   Report, never explain. The digest records what happened, never why, so no
   sentence may give a reason for a figure or connect two figures as cause and
   effect. Constructions like "dette skyldes …", "en væsentlig forklarende
   faktor", "når flere deltager, påvirkes medianen …", "denne sammensætning
   indikerer …" or "det afspejler …" are forbidden however plausible they are:
   more entrants and a lower median are two facts, not one explanation. If two
   figures moved, report both movements and stop.
7. CONSISTENCY. Never describe the same figure as both unchanged and changed
   (e.g. "uændret" and "en stigning på ..."). A non-zero delta is a change,
   however small — call it unchanged only when it is exactly 0. If your
   wording and a digest.derived percentage disagree, trust the digest.
8. PLAIN DANISH. Write natural Danish prose only — never a field name,
   camelCase identifier, or English technical token. Say "elitens median",
   not "elitens medianScore".
9. EVENT NAMES. digest.top_swims[].event carries a gender marker (e.g.
   "M 50m Ryg (LCM)", "F 50m Ryg (LCM)") because men's and women's events
   share the same name otherwise. Always carry that gender into your text —
   "herrernes 50m Ryg" / "damernes 50m Ryg", or M/F as the digest does.
   "50m Ryg" alone is ambiguous between two different swimmers.

Output the four sections through the provided structure. Do not add sections,
headings, preambles or closing remarks.
"""


class EvaluationError(Exception):
    """The model produced a report we refuse to publish."""


class Section(BaseModel):
    heading: str
    body: str

    @field_validator("heading")
    @classmethod
    def known_heading(cls, v: str) -> str:
        if v not in HEADINGS:
            raise ValueError(f"unknown heading: {v!r}")
        return v


class MeetEvaluation(BaseModel):
    sections: list[Section]

    @field_validator("sections")
    @classmethod
    def all_four_in_order(cls, v: list[Section]) -> list[Section]:
        if tuple(s.heading for s in v) != HEADINGS:
            raise ValueError(f"sections must be exactly {HEADINGS} in order")
        return v


def model_label(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)


def _numbered_guardrail(guardrail_id: str, guardrail_version: str) -> tuple[str, str]:
    """Validate the (id, version) pair both enforcement paths depend on.

    DRAFT is refused because a draft guardrail can change under us between two
    meets of the same batch. The id is validated because the failure modes are
    asymmetric in the wrong direction: BedrockModel gates the whole
    guardrailConfig on both values being truthy, so a bad *version* fails
    loudly at Bedrock while a blank *id* silently produces a completely
    unguarded call."""
    gid = (guardrail_id or "").strip()
    version = (guardrail_version or "").strip()
    if not gid:
        raise ValueError("guardrail_id must be a non-empty guardrail id")
    if not version or version.upper() == "DRAFT":
        raise ValueError("guardrail_version must be a numbered version, not DRAFT")
    return gid, version


def build_agent(*, model_id: str, guardrail_id: str, guardrail_version: str) -> Agent:
    """A Converse-API agent with the guardrail applied inline at a numbered
    version.

    The inline guardrail only assesses the *input* on this path — the prose
    comes back inside a forced tool call, so OutputGuard below is what actually
    enforces the policy on the generated text."""
    guardrail_id, guardrail_version = _numbered_guardrail(guardrail_id, guardrail_version)
    model = BedrockModel(
        model_id=model_id,
        region_name=REGION,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        max_tokens=MAX_TOKENS,
    )
    return Agent(model=model, system_prompt=SYSTEM_PROMPT)


class OutputGuard:
    """The guardrail applied to the generated text, explicitly, section by section.

    The inline guardrailConfig on the Converse call does not do this job here.
    `structured_output_model` is a forced tool call in strands, so the Danish
    prose arrives inside `toolUse.input` rather than a text block, and a traced
    production call came back with `modelOutput: []` and no `outputAssessments`
    key at all — the four denied topics only ever assessed the input, i.e. our
    own system prompt and digest. Contextual grounding never ran either: it
    needs the grounding source and the query tagged with `qualifiers`, and
    Converse cannot receive those through a plain string prompt.

    ApplyGuardrail is text-based and does take those qualifiers, so this is
    where both halves of the policy actually get enforced. One call per
    *section* of a generated meet, none on a cache hit.

    One call per section rather than one for the whole report, because
    concatenation destroys the grounding score. Measured against six real
    reports: 0.40-0.81 for the whole report, 0.63-0.95 for those same reports'
    individual sections. Deliberately ungrounded sections scored 0.00-0.34, so
    per section the threshold has a wide margin to sit in and a block can say
    which section was wrong. See the stack's GROUNDING_THRESHOLD.
    """

    def __init__(self, *, guardrail_id: str, guardrail_version: str, client) -> None:
        self.guardrail_id, self.guardrail_version = _numbered_guardrail(
            guardrail_id, guardrail_version)
        self.client = client

    def check(self, sections: list[dict], digest_json: str) -> str | None:
        """The heading of the first section the guardrail intervened on, or None.

        Stops at the first blocked section: the report is already unpublishable,
        and the remaining calls cost money to confirm it. Returns rather than
        raises so `evaluate` can retry a block the same way it retries a
        fabricated number — both are one section drifting off the digest.
        """
        for section in sections:
            response = self.client.apply_guardrail(
                guardrailIdentifier=self.guardrail_id,
                guardrailVersion=self.guardrail_version,
                source="OUTPUT",
                content=[
                    {"text": {"text": digest_json,
                              "qualifiers": ["grounding_source"]}},
                    # Required even with no RELEVANCE filter reading it:
                    # ApplyGuardrail rejects the request with a
                    # ValidationException when a contextual grounding policy is
                    # configured and the query block is absent.
                    {"text": {"text": GUARD_QUERY, "qualifiers": ["query"]}},
                    {"text": {"text": section["body"]}},   # unqualified: guard this
                ])
            if response.get("action") == "GUARDRAIL_INTERVENED":
                log.info("the guardrail blocked the section %r: %s",
                         section["heading"], response.get("assessments"))
                return section["heading"]
        return None


def _prompt(digest_json: str, offenders: set[str] | None = None,
            blocked: str | None = None) -> str:
    head = f"<digest>{digest_json}</digest>"
    if offenders:
        bad = ", ".join(sorted(offenders))
        return (f"{head}\n"
                f"Your previous answer contained numbers that are not in the digest: "
                f"{bad}. Rewrite the evaluation using only numbers from the digest.")
    if blocked:
        # The model cannot see the guardrail's verdict, so name the section and
        # the offence. Grounding is what fails here in practice: a section that
        # explains or interprets rather than reports scores far below the
        # threshold even when every number in it is real.
        return (f"{head}\n"
                f"Your previous answer failed the automatic grounding check in the "
                f"section {blocked!r}: it contained claims that do not follow from "
                f"the digest. Rewrite the whole evaluation. In every section, state "
                f"only what the digest shows. Do not explain or interpret why a "
                f"figure moved, do not link two figures as cause and effect, and do "
                f"not draw conclusions about what the numbers mean.")
    return head


def evaluate(digest: dict, *, agent, guard: OutputGuard, retries: int = 1) -> list[dict]:
    """digest -> [{heading, body}, ...]. Raises EvaluationError if the number
    check still fails after `retries` rewrites, or if the guardrail intervenes.

    `guard` is required, not optional: a caller that reaches here without one
    would publish unguarded prose about named minors, which is a bug in the
    caller rather than a mode this function supports."""
    if guard is None:
        raise ValueError("evaluate() requires an OutputGuard, not None")

    # The docstring's "the digest is the agent's entire world" has to be
    # enforced here, not assumed: a batch caller reusing one Agent across
    # meets would otherwise carry meet A's history into meet B's prompt, and
    # check_numbers screens numbers only — a leaked name would pass.
    messages = getattr(agent, "messages", None)
    if messages is not None:
        messages.clear()

    digest_json = canonical_json(digest)
    offenders: set[str] = set()
    blocked: str | None = None
    for attempt in range(retries + 1):
        result = agent(_prompt(digest_json,
                               offenders if attempt else None,
                               blocked if attempt else None),
                       structured_output_model=MeetEvaluation)
        # A block is a failure, not a fallback — and it must be detected
        # explicitly. Strands leaves guardrail_redact_output False and does not
        # raise, so without these two checks a block surfaced only as an
        # incidental AttributeError on report.sections (a blocked response has
        # no tool-use block), which run() logged as an unexplained traceback.
        if getattr(result, "stop_reason", None) == "guardrail_intervened":
            raise EvaluationError("the guardrail blocked the Converse call")
        report = result.structured_output
        if report is None:
            raise EvaluationError("the model returned no structured output")
        text = "\n".join(s.body for s in report.sections)
        offenders = check_numbers(text, digest)
        if not offenders:
            sections = [{"heading": s.heading, "body": s.body}
                        for s in report.sections]
            # Last gate before the caller caches and publishes this text.
            blocked = guard.check(sections, digest_json)
            if blocked is None:
                return sections
    if blocked:
        raise EvaluationError(
            f"the guardrail blocked the section {blocked!r} after "
            f"{retries} retry")
    raise EvaluationError(
        f"numbers not in digest after {retries} retry: {sorted(offenders)}")
