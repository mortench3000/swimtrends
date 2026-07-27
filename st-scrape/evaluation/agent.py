"""The evaluation agent: one digest in, one Danish coach report out.

A single Strands agent, a single Converse call per meet, no tools and no
memory — the digest is the agent's entire world, which is what makes both the
guardrail's grounding check and the deterministic number check meaningful.

PROMPT_VERSION / SCHEMA_VERSION are part of the cache key: bump either and
every meet regenerates on the next run. Do that deliberately.
"""
from pydantic import BaseModel, field_validator
from strands import Agent
from strands.models import BedrockModel

from evaluation.check import check_numbers

PROMPT_VERSION = "1"
SCHEMA_VERSION = "1"

REGION = "eu-west-1"
MAX_TOKENS = 1200

HEADINGS = (
    "Samlet niveau",
    "Bredde",
    "Fremhævede svømninger",
    "Discipliner i bevægelse",
)

# Human-readable label shown in the page footer next to the generation date.
# Extend as models are added; unmapped ids fall back to the raw id.
MODEL_LABELS: dict[str, str] = {}

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
   percentage change, use only the precomputed values in digest.derived. If a
   number you want does not exist in the digest, describe the direction in
   words instead ("højere end", "under de seneste sæsoners niveau").
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


def build_agent(*, model_id: str, guardrail_id: str, guardrail_version: str) -> Agent:
    """A Converse-API agent with the guardrail applied inline at a numbered
    version. DRAFT is refused: a draft guardrail can change under us between
    two meets in the same batch."""
    if not guardrail_version or guardrail_version.upper() == "DRAFT":
        raise ValueError("guardrail_version must be a numbered version, not DRAFT")
    model = BedrockModel(
        model_id=model_id,
        region_name=REGION,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        max_tokens=MAX_TOKENS,
        cache_prompt="default",
    )
    return Agent(model=model, system_prompt=SYSTEM_PROMPT)


def _prompt(digest_json: str, offenders: set[str] | None = None) -> str:
    if not offenders:
        return f"<digest>{digest_json}</digest>"
    bad = ", ".join(sorted(offenders))
    return (f"<digest>{digest_json}</digest>\n"
            f"Your previous answer contained numbers that are not in the digest: "
            f"{bad}. Rewrite the evaluation using only numbers from the digest.")


def evaluate(digest: dict, *, agent, retries: int = 1) -> list[dict]:
    """digest -> [{heading, body}, ...]. Raises EvaluationError if the number
    check still fails after `retries` rewrites."""
    from evaluation.cache import canonical_json      # local: avoids a cycle

    digest_json = canonical_json(digest)
    offenders: set[str] = set()
    for attempt in range(retries + 1):
        result = agent(_prompt(digest_json, offenders if attempt else None),
                       structured_output_model=MeetEvaluation)
        report = result.structured_output
        text = "\n".join(s.body for s in report.sections)
        offenders = check_numbers(text, digest)
        if not offenders:
            return [{"heading": s.heading, "body": s.body} for s in report.sections]
    raise EvaluationError(
        f"numbers not in digest after {retries} retry: {sorted(offenders)}")
