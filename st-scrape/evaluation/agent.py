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
import re
from typing import Literal

from pydantic import BaseModel, field_validator
from strands import Agent
from strands.models import BedrockModel

from evaluation.cache import canonical_json
from evaluation.check import (check_attribution, check_genders, check_language,
                              check_numbers)

log = logging.getLogger("evaluation")

PROMPT_VERSION = "7"
SCHEMA_VERSION = "3"

REGION = "eu-west-1"
# 4000, not 1200: Haiku's five sections fit in 1200, Sonnet 4.6's do not — it
# spends ~2000 on the same 300-word brief, and every one of 41 meets died on
# MaxTokensReachedException (which strands raises instead of returning the
# partial report, so the meet is skipped and its published page is dropped).
# The real length control is the word budget in SYSTEM_PROMPT; this is only the
# ceiling. It is in the cache key, so raising it regenerates every meet.
MAX_TOKENS = 4000

# The spend ceiling for one meet, passed to every agent invocation. A healthy
# meet takes one turn of ~3k input + ~700 output tokens, and the retry path adds
# at most one more — so 40k/6 leaves an order of magnitude of headroom while
# capping what a runaway costs.
#
# It exists because a rejected structured-output field makes strands re-call the
# tool with the whole conversation *plus every prior rejection* resent, so input
# grows per call and the total grows quadratically. One misspelled heading cost
# 105 calls and ~1.4M input tokens on a single meet, and the day's batch billed
# ~28M input tokens ($30.87) against an expected ~0.2M ($0.29). strands does not
# bound this on its own: its MAX_ATTEMPTS=6 governs *throttle* retries, not the
# agentic loop, which recurses as long as the model keeps calling the tool.
# `limits` is per-invocation, not per-agent — an agent(...) call without it is an
# uncapped meet.
LIMITS = {"turns": 6, "total_tokens": 40_000}

# The instruction the report answers, sent to ApplyGuardrail tagged `query` so
# the RELEVANCE half of the contextual grounding filter has something to
# compare the report against.
GUARD_QUERY = "Skriv en trænervurdering af stævnet."

HEADINGS = (
    "Samlet niveau",
    "Bredde",
    "Fremhævede svømninger",
    "Discipliner i bevægelse",
    "Klubberne",
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
300 words total, split into exactly these five sections, in this order, with
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
3. NAMED SWIMMERS. You may name swimmers from digest.top_swims and from
   digest.multi_title_swimmers, and state their time, points, placement and
   event. Nothing else. A swimmer's title count is
   digest.multi_title_swimmers[].titles — quote it, never count the wins
   yourself. Never write about a swimmer's potential or future, their
   technique, body, health, injuries, age, training or schooling, and never
   phrase anything as criticism of a named person. Many of these swimmers are
   minors.
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
9. EVENT NAMES. Every event in digest.top_swims and in
   digest.multi_title_swimmers[].wins carries a gender marker (e.g.
   "M 50m Ryg (LCM)", "F 50m Ryg (LCM)") because men's and women's events
   share the same name otherwise. Always carry that gender into your text —
   "herrernes 50m Ryg" / "damernes 50m Ryg", or M/F as the digest does.
   "50m Ryg" alone is ambiguous between two different swimmers.
10. CLUBS. digest.clubs is this meet's club table, already ordered: rank 1 is
    the club with the most titles. The section "Klubberne" reports that order
    and the figures in it — titles, podiums and
    the number of the club's swimmers the digest counted. Say a club led
    the meet only if it is rank 1. Never rank a club that is not in
    digest.clubs, never characterise the clubs that are absent from it
    (the meet had more clubs than the table shows), and never judge a
    club or explain its position. Clubs are organisations, so rule 3
    does not apply to them — rule 6 still does: a club name is not a
    place, and a title count is not a statement about a region.

Output the five sections through the provided structure. Do not add sections,
headings, preambles or closing remarks.
"""


class EvaluationError(Exception):
    """The model produced a report we refuse to publish."""


class Section(BaseModel):
    # A Literal, not a str with a validator: this puts the five legal strings in
    # the tool schema the model reads *before* it answers, and pydantic's own
    # rejection message lists them. With only a validator, one misspelled heading
    # ("Fremhævede svømminger") sent Haiku into 105 tool calls on a single meet —
    # it could see that its heading was rejected but never what the alternatives
    # were, and concluded the tool "accepts a limited set of predefined headings"
    # it had not been told.
    heading: Literal[HEADINGS]
    body: str


class MeetEvaluation(BaseModel):
    sections: list[Section]

    @field_validator("sections")
    @classmethod
    def all_sections_in_order(cls, v: list[Section]) -> list[Section]:
        if tuple(s.heading for s in v) != HEADINGS:
            raise ValueError(f"sections must be exactly {HEADINGS} in order")
        return v


def model_label(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)


# --- publish-time prose ------------------------------------------------------
# Wording the checks cannot judge: the numbers are real, the words are Danish
# and the sentence is grounded, so only the phrasing is wrong. Fixed here rather
# than in the prompt because that keeps the cached text (and the
# number/gender/attribution verdicts that ran on it) untouched, needs no
# PROMPT_VERSION bump, and cleans up every already-generated report on the next
# cache-hit run.
#
# The digest indexes events as "M 100m Fri (LCM)" — gender marker plus course —
# and rule 9 makes the model carry the gender through, which it often does by
# copying the marker verbatim. That reads as machine output in Danish prose.
# Rewriting it here rather than tightening the prompt leaves the cached text (and
# the number/gender/attribution checks that ran on it) untouched, so every
# already-generated report is cleaned up without a regeneration.
_MARKER = re.compile(r"\b([MFX]) (?=[\dx]+m\s+(?:Fri|Ryg|Bryst|Fly|IM|HM)\b)")
_COURSE = re.compile(r" \((?:LCM|SCM)\)")
# X is the mixed relay: only one event of its kind, so dropping the marker
# loses nothing that needs a Danish word.
_GENDER_WORD = {"M": "herrernes", "F": "damernes", "X": ""}
# "31 tællende svømmere" (DM-L/10334). digest.clubs[].swimmers is simply how many
# of the club's swimmers competed, but rule 10 calls it "the swimmers the digest
# counted" and the model reached for the Danish idiom for counting toward a
# standing ("tællende kampe"), which implies an eligibility filter that does not
# exist. The same section already writes the plain form ("fra 7 svømmere").
# ponytail: drop the word, don't re-case — the model writes this after a numeral,
# never sentence-initially. Rule 10's wording is the cause and is worth fixing on
# the next PROMPT_VERSION bump.
# tællende / tællede / tælle- : the same idiom in three spellings across two
# rounds. Requiring "svømmere" immediately after keeps the legitimate verb safe —
# "Stævnet tæller 265 juniorer" always has a count next, never the noun.
_COUNTED = re.compile(r"\btæll[a-zæøå]*\s*(svømmere)", re.IGNORECASE)
# Em- and en-dashes become a plain hyphen. The en-dash is not only typography:
# the model writes club names with it ("GTI – Greve") where the digest — and so
# the page, and check_attribution's masking — has "GTI - Greve".
_DASHES = str.maketrans({"—": "-", "–": "-"})
# The podium vocabulary, which this model cannot spell and cannot be taught to:
# podieplacerigner, podieplacerringer, podieplaceriger, podieplaceriner,
# podieplaceringe, podieplacerninger, plus a whole "pokal" (trophy) branch —
# pokaler, pokalpladser, pokaliepladser, pokalieplaceringer, pokaljepladser. A
# new spelling every round, so gating it burned all four attempts (DM-K/6042
# answered a rejection with a *fresh* misspelling, twice).
#
# Repairing it is safe rather than a guess: every single occurrence sat in the
# club table's podiums slot ("6 titler, 12 pokaler og 16 svømmere"), so they all
# mean podiepladser. ponytail: always plural, because the model only ever writes
# this after a count — a mangled singular would need agreement, and none exists.
# palle-/pallads- need the plads/placer continuation: bare "Palle" is a Danish
# first name, and this runs case-insensitively.
_PODIUM = re.compile(r"\bpodieplacer(?!ing(?:er|en|erne)?\b)[a-zæøå]*"
                     r"|\bpokal[a-zæøå]*"
                     r"|\b(?:palle|pallads)(?:plads|placer)[a-zæøå]*", re.IGNORECASE)
# English terms with exactly one Danish word each, so swapping is a repair and
# not a guess. Same reason as the podium family: DM-K/10976 answered four
# rejections with "46 events" every time, and a gate that only rejects cannot
# teach vocabulary. "digest"/"derived" are deliberately NOT here — they arrive
# inside a phrase ("digest.derived angiver 0 procent") where dropping the token
# leaves broken prose, so those stay gated and get rewritten by the model.
_DANISH_FOR = {
    "events": "discipliner", "event": "disciplin",
    "strokes": "stilarter", "stroke": "stilart",
    "strokearter": "stilarter", "stroketyper": "stilarter",
    "slagarter": "stilarter", "podiums": "podiepladser",
    # "stroke" translated a word at a time: a slag is a blow, not a swimming
    # style. Danish spells the plural the same, and all four live occurrences
    # were plural ("på tværs af slag", "de enkelte slag"), so plural it is.
    "slag": "stilarter", "slagene": "stilarterne",
    "deltas": "forskelle", "deltaer": "forskelle",
    # A Danish compound the model drops an s from. Same operation, same map.
    "femårsnit": "femårssnit", "femårsnittet": "femårssnittet",
}
_ENGLISH = re.compile(
    r"\b(" + "|".join(sorted(_DANISH_FOR, key=len, reverse=True)) + r")\b",
    re.IGNORECASE)


def plain_prose(text: str) -> str:
    """Digest labels and jargon as Danish prose.

    "M 100m Fri (LCM)" -> "herrernes 100m Fri"; "31 tællende svømmere" -> "31
    svømmere".
    """
    def sub(m):
        word = _GENDER_WORD[m.group(1)]
        if not word:
            return ""
        head = text[:m.start()].rstrip()
        # Sentence-initial: "M 100m Fri blev vundet af" -> "Herrernes …".
        if not head or head[-1] in ".:!?":
            word = word.capitalize()
        return f"{word} "
    out = _COUNTED.sub(r"\1", _COURSE.sub("", _MARKER.sub(sub, text)))
    out = _PODIUM.sub("podiepladser", out)

    def danish(m):
        word = _DANISH_FOR[m.group(1).lower()]
        return word.capitalize() if m.group(1)[0].isupper() else word
    return _ENGLISH.sub(danish, out).translate(_DASHES)


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
    # callback_handler=None: the default PrintingCallbackHandler streams every
    # tool call ("Tool #17: MeetEvaluation") and every text block to stdout,
    # including the model's mid-retry apologies to itself. Across a 41-meet batch
    # that is most of the output and none of it is a signal — the per-meet
    # refused/failed lines and the closing summary are.
    return Agent(model=model, system_prompt=SYSTEM_PROMPT, callback_handler=None)


def _why(assessments) -> str:
    """The reasons an ApplyGuardrail response intervened, one short line.

    The raw assessments dict is ~700 characters of invocationMetrics, coverage
    counts and the guardrail ARN. Several blocks per meet buried the line saying
    which meet was refused. What is actionable is the policy and, for grounding,
    score vs threshold: 0.13 is prose the digest cannot support, 0.49 a near miss.
    """
    reasons = []
    for a in assessments or []:
        for f in a.get("contextualGroundingPolicy", {}).get("filters", []):
            if f.get("action") == "BLOCKED":
                reasons.append(f"{f.get('type')} {f.get('score')} "
                               f"< threshold {f.get('threshold')}")
        for t in a.get("topicPolicy", {}).get("topics", []) if isinstance(
                a.get("topicPolicy"), dict) else []:
            reasons.append(f"topic {t.get('name')}")
        for c in a.get("contentPolicy", {}).get("filters", []) if isinstance(
                a.get("contentPolicy"), dict) else []:
            reasons.append(f"content {c.get('type')} {c.get('confidence')}")
    # Nothing recognised is itself the signal: a policy fired that this summary
    # doesn't model, and the DEBUG line beside it has the detail.
    return "; ".join(reasons) or "see the DEBUG assessment"


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
                assessments = response.get("assessments")
                log.info("the guardrail blocked the section %r: %s",
                         section["heading"], _why(assessments))
                # The summary keeps only what the four configured policies can
                # say; the raw dict stays reachable for anything else that fires.
                log.debug("full assessment for %r: %s", section["heading"], assessments)
                return section["heading"]
        return None


def _prompt(digest_json: str, offenders: set[str] | None = None,
            blocked: str | None = None, wrong_gender: set[str] | None = None,
            misattributed: set[str] | None = None,
            foreign: set[str] | None = None) -> str:
    head = f"<digest>{digest_json}</digest>"
    if offenders:
        bad = ", ".join(sorted(offenders))
        return (f"{head}\n"
                f"Your previous answer contained numbers that are not in the digest: "
                f"{bad}. Rewrite the evaluation using only numbers from the digest.")
    if wrong_gender:
        # Name the offending phrase: the model wrote the opposite of a marker it
        # was given, so pointing at the event alone would not show it the flip.
        bad = ", ".join(sorted(wrong_gender))
        return (f"{head}\n"
                f"Your previous answer described these events with the wrong "
                f"gender: {bad}. Every event in digest.top_swims and in "
                f"digest.multi_title_swimmers[].wins carries its "
                f"gender as the first character (\"F 50m Ryg (LCM)\" is a "
                f"women's race, \"M 50m Ryg (LCM)\" a men's). Rewrite the "
                f"evaluation and take each event's gender from that marker.")
    if misattributed:
        # Quote the pairing, not just the number: the figure itself is real and
        # in the digest, so "N is wrong" would read as a contradiction.
        bad = ", ".join(sorted(misattributed))
        return (f"{head}\n"
                f"Your previous answer credited the wrong swimmer with these "
                f"results ({bad}). Each entry in digest.top_swims and in "
                f"digest.multi_title_swimmers[].wins binds one name to one "
                f"event, time and points — never move a figure from one "
                f"swimmer to another. A swimmer's title count is "
                f"digest.multi_title_swimmers[].titles; take it from there "
                f"rather than counting wins yourself. Rewrite the evaluation.")
    if foreign:
        # Quote the words themselves: rule 8 already asked for plain Danish, so
        # repeating the rule teaches nothing — the model cannot see which word
        # of its own prose was not Danish.
        bad = ", ".join(sorted(foreign))
        return (f"{head}\n"
                f"Your previous answer used words that are not correct Danish, "
                f"or are field names from the digest: {bad}. Rewrite the "
                f"evaluation in plain Danish prose. Every word must be a real, "
                f"correctly inflected Danish word — never Norwegian or Swedish, "
                f"never English, and never a name from the digest's structure "
                f"(\"digest\", \"derived\", \"deltas\", \"events\").")
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


def evaluate(digest: dict, *, agent, guard: OutputGuard, retries: int = 3) -> list[dict]:
    """digest -> [{heading, body}, ...]. Raises EvaluationError if the number
    check still fails after `retries` rewrites, or if the guardrail intervenes.

    `retries` is 3 because the grounding verdict is not a property of the meet:
    the same digest's sections scored 0.38 and 0.83 on two runs, and two 11-meet
    batches lost a *different* pair of meets each. At one retry a batch left
    ~5% of meets with no report, and the meets it dropped were not the ones with
    thin data — they were the unlucky ones. Re-rolling is the cheap fix (an
    attempt is ~4k tokens; prompt wording is not, and tightening it to fight the
    threshold made things worse: a stricter section split scored *better* on the
    section it targeted and pushed the block onto a neighbouring section, 4
    refusals in 11 meets).

    `guard` is required, not optional: a caller that reaches here without one
    would publish unguarded prose about named minors, which is a bug in the
    caller rather than a mode this function supports."""
    if guard is None:
        raise ValueError("evaluate() requires an OutputGuard, not None")

    # The docstring's "the digest is the agent's entire world" has to be
    # enforced here, not assumed: a batch caller reusing one Agent across
    # meets would otherwise carry meet A's history into meet B's prompt, and
    # check_numbers screens numbers only — a leaked name would pass.
    #
    # Cleared before *every* attempt, not once per meet: strands appends each
    # answer to agent.messages, so a retry would otherwise resend the rejected
    # prose as input, where the Converse call's inline guardrail assesses it and
    # blocks the whole meet — a failure evaluate() does not retry. That cost 5
    # meets of a 41-meet batch, all of them meets that only needed a re-roll.
    # `_prompt` restates the digest and the complaint, so an empty conversation
    # loses nothing (and keeps input cost flat across attempts).
    messages = getattr(agent, "messages", None)

    digest_json = canonical_json(digest)
    offenders: set[str] = set()
    wrong_gender: set[str] = set()
    misattributed: set[str] = set()
    blocked: str | None = None
    for attempt in range(retries + 1):
        if messages is not None:
            messages.clear()
        result = agent(_prompt(digest_json,
                               offenders if attempt else None,
                               blocked if attempt else None,
                               wrong_gender if attempt else None,
                               misattributed if attempt else None,
                               foreign if attempt else None),
                       structured_output_model=MeetEvaluation,
                       limits=LIMITS)
        # A block is a failure, not a fallback — and it must be detected
        # explicitly. Strands leaves guardrail_redact_output False and does not
        # raise, so without these two checks a block surfaced only as an
        # incidental AttributeError on report.sections (a blocked response has
        # no tool-use block), which run() logged as an unexplained traceback.
        stop_reason = getattr(result, "stop_reason", None)
        if stop_reason == "guardrail_intervened":
            raise EvaluationError("the guardrail blocked the Converse call")
        # Same shape as a block — no structured output, no exception — so name it
        # rather than let it read as an empty answer. Not retried: a trip means
        # the model already burned the meet's whole allowance.
        if str(stop_reason).startswith("limit_"):
            raise EvaluationError(
                f"the token budget stopped the tool loop ({stop_reason}, "
                f"limits={LIMITS})")
        report = result.structured_output
        if report is None:
            raise EvaluationError("the model returned no structured output")
        text = "\n".join(s.body for s in report.sections)
        offenders = check_numbers(text, digest)
        # Checked before the guardrail for the same reason the number check is:
        # a rewrite is cheaper than an ApplyGuardrail call per section, and the
        # guardrail would pass this text anyway (0.88 grounding on the real
        # DM-L/9775 sentence, four hundredths below the corrected version).
        wrong_gender = check_genders(text, digest)
        # Same class as the gender flip: a real figure bound to the wrong
        # athlete, invisible to both the number check and the guardrail.
        misattributed = check_attribution(text, digest)
        # The fourth class, invisible to the three above and to grounding: the
        # prose is not Danish ("Klubben førtede medaljeantallet").
        foreign = check_language(text, digest)
        if not offenders and not wrong_gender and not misattributed and not foreign:
            sections = [{"heading": s.heading, "body": s.body}
                        for s in report.sections]
            # Last gate before the caller caches and publishes this text.
            blocked = guard.check(sections, digest_json)
            if blocked is None:
                return sections
    if misattributed:
        raise EvaluationError(
            f"misattributed results {sorted(misattributed)} after "
            f"{retries + 1} attempts")
    if wrong_gender:
        raise EvaluationError(
            f"wrong gender on {sorted(wrong_gender)} after "
            f"{retries + 1} attempts")
    if foreign:
        raise EvaluationError(
            f"words that are not Danish after {retries + 1} attempts: "
            f"{sorted(foreign)}")
    if blocked:
        raise EvaluationError(
            f"the guardrail blocked the section {blocked!r} after "
            f"{retries + 1} attempts")
    raise EvaluationError(
        f"numbers not in digest after {retries + 1} attempts: {sorted(offenders)}")
