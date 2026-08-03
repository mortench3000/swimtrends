import hashlib
import inspect
import json

import boto3
import pytest
from botocore.stub import Stubber

from evaluation import agent as ag

DIGEST = {
    "meet": {"season": 2026, "name": "DM 2026", "date": "2026-04-10",
             "category": "DM-L", "course": "LCM"},
    "facts": {"entrants": 412, "events": 38, "clubs": 58, "juniors": 61,
              "median_points": 612, "elite_median_points": 701, "top_points": 812},
    "season_history": [
        {"season": 2026, "entrants": 412, "clubs": 58, "median_points": 612,
         "elite_median_points": 701}],
    "top_swims": [], "by_stroke": [], "derived": {},
}


class FakeResult:
    def __init__(self, sections, stop_reason="tool_use"):
        self.structured_output = (None if sections is None
                                  else ag.MeetEvaluation(sections=sections))
        self.stop_reason = stop_reason


class FakeAgent:
    """Stands in for a Strands Agent: records prompts, returns canned reports.

    A report of None models an absent structured_output; pass a FakeResult
    directly to control stop_reason.
    """
    def __init__(self, *reports):
        self.reports = list(reports)
        self.prompts = []
        self.kwargs = []
        self.messages = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        self.kwargs.append(kwargs)
        report = self.reports.pop(0)
        return report if isinstance(report, FakeResult) else FakeResult(report)


def _sections(body):
    return [{"heading": h, "body": body} for h in ag.HEADINGS]


class FakeGuardrailClient:
    """Stands in for a bedrock-runtime client: records the ApplyGuardrail
    request and returns a canned action. No test may reach AWS."""
    def __init__(self, action="NONE"):
        self.action = action
        self.calls = []
        # Optional {section body substring -> action}, for intervening on one
        # section of a report while the others pass.
        self.action_for: dict[str, str] = {}

    def apply_guardrail(self, **kwargs):
        self.calls.append(kwargs)
        guarded = kwargs["content"][2]["text"]["text"]
        action = next((a for key, a in self.action_for.items() if key in guarded),
                      self.action)
        return {"action": action,
                "assessments": getattr(self, "assessments", [{"topicPolicy": "x"}])}


def _guard(action="NONE"):
    return ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3",
                          client=FakeGuardrailClient(action))


def test_evaluate_returns_the_sections_in_order():
    fake = FakeAgent(_sections("612 point og 412 deltagere."))
    out = ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert [s["heading"] for s in out] == list(ag.HEADINGS)


def test_evaluate_passes_the_digest_in_the_prompt():
    fake = FakeAgent(_sections("612 point."))
    ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert "<digest>" in fake.prompts[0]
    assert "412" in fake.prompts[0]


def test_evaluate_retries_once_when_a_number_is_fabricated():
    fake = FakeAgent(_sections("Median var 777 point."),      # bad
                     _sections("Median var 612 point."))      # good on retry
    out = ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert len(fake.prompts) == 2
    assert "777" in fake.prompts[1]           # the offending token is quoted back
    assert "612" in out[0]["body"]


def test_evaluate_raises_when_the_retry_also_fabricates():
    fake = FakeAgent(_sections("777 point."), _sections("888 point."))
    with pytest.raises(ag.EvaluationError) as e:
        ag.evaluate(DIGEST, agent=fake, guard=_guard(), retries=1)
    assert "888" in str(e.value)


def test_a_blocked_section_is_re_rolled_up_to_retries_times():
    """The guardrail's verdict on a correct report is not deterministic: the
    same meet's sections scored 0.38 and 0.83 on two runs, and a batch lost a
    different pair of meets each time. Re-rolling is what recovers them —
    measured, both meets a run had refused passed on a later attempt."""
    client = FakeGuardrailClient()
    client.action_for = {"tredje": "GUARDRAIL_INTERVENED"}
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3",
                           client=client)
    blocked = [{"heading": h, "body": b} for h, b in
               zip(ag.HEADINGS, ["612 point.", "612 point.",
                                 "612 point i tredje.", "612 point.",
                                 "612 point."])]
    fake = FakeAgent(blocked, [dict(s) for s in blocked], _sections("612 point."))
    out = ag.evaluate(DIGEST, agent=fake, guard=guard, retries=2)
    assert len(fake.prompts) == 3            # two blocks, then a clean one
    assert "612 point." in out[0]["body"]


def test_each_attempt_starts_from_an_empty_conversation():
    """A retry must not resend the previous attempt's prose as input.

    Strands appends each answer to agent.messages, so attempt 2 carries
    attempt 1's rejected text into the *input* of the next Converse call — where
    the inline guardrail assesses it and blocks the whole meet ("the guardrail
    blocked the Converse call"), which evaluate() does not retry. A 41-meet
    batch lost 5 meets that way, all of them meets that had merely needed a
    re-roll. `_prompt` already restates the digest and the complaint, so the
    history carries nothing but the liability — and the resent conversation is
    also what makes input cost grow per attempt.
    """
    seen = []

    class RecordingAgent(FakeAgent):
        def __call__(self, prompt, **kwargs):
            seen.append(list(self.messages))
            self.messages.append({"role": "assistant", "content": "previous answer"})
            return super().__call__(prompt, **kwargs)

    fake = RecordingAgent(_sections("777 point."), _sections("612 point."))
    ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert len(seen) == 2
    assert seen[1] == [], "the retry saw the previous attempt's conversation"


def test_evaluate_default_allows_more_than_one_re_roll():
    """A single retry left ~5% of meets unpublished per batch. Pinning the
    default here so it cannot silently drift back to one."""
    assert inspect.signature(ag.evaluate).parameters["retries"].default >= 2


def test_evaluate_does_not_carry_history_between_meets():
    """The digest must be the agent's entire world: a caller reusing one agent
    across meets would otherwise leak meet A's content into meet B's prompt,
    and the number check screens numbers only — a leaked name would pass."""
    fake = FakeAgent(_sections("612 point."), _sections("612 point."))
    fake.messages = [{"role": "user", "content": "an earlier meet's conversation"}]
    ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert fake.messages == []


def test_evaluate_raises_when_the_converse_call_was_blocked_by_the_guardrail():
    """A guardrail block is a failure, not a fallback: the meet is skipped and
    nothing is written. Before this check the block was caught only
    incidentally — a blocked response carries no tool-use block, so
    structured_output ended up absent and `report.sections` raised
    AttributeError, which run()'s generic except swallowed as "evaluation
    failed". That is an undocumented SDK path, and it told the operator
    nothing about why the meet was skipped."""
    fake = FakeAgent(FakeResult(None, stop_reason="guardrail_intervened"))
    with pytest.raises(ag.EvaluationError, match="guardrail"):
        ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert len(fake.prompts) == 1          # no retry: a block is not retried


def test_evaluate_raises_when_the_model_returns_no_structured_output():
    fake = FakeAgent(None)
    with pytest.raises(ag.EvaluationError, match="structured output"):
        ag.evaluate(DIGEST, agent=fake, guard=_guard())


def test_evaluate_applies_the_guardrail_to_the_report_before_returning():
    """The Converse-inline guardrail never sees the generated prose: structured
    output is a forced tool call, and a traced production call came back with
    modelOutput [] and no outputAssessments at all. ApplyGuardrail on the
    assembled text is where the four denied topics and the contextual grounding
    check actually run."""
    guard = _guard()
    fake = FakeAgent(_sections("612 point."))
    out = ag.evaluate(DIGEST, agent=fake, guard=guard)

    assert len(guard.client.calls) == len(out)
    call = guard.client.calls[0]
    assert call["guardrailIdentifier"] == "gr-1"
    assert call["guardrailVersion"] == "3"
    assert call["source"] == "OUTPUT"
    blocks = call["content"]
    # Contextual grounding needs the source and the query tagged; Converse
    # cannot receive either through a plain string prompt, which is why the
    # thresholds had never once been evaluated. The query block stays even
    # though no RELEVANCE filter reads it — ApplyGuardrail rejects the request
    # with a ValidationException when any grounding policy is configured and
    # the query is missing.
    assert blocks[0]["text"]["qualifiers"] == ["grounding_source"]
    assert "412" in blocks[0]["text"]["text"]              # the digest
    assert blocks[1]["text"]["qualifiers"] == ["query"]
    # Unqualified = the content to guard, i.e. what we are about to publish.
    assert "qualifiers" not in blocks[2]["text"]
    assert blocks[2]["text"]["text"] == out[0]["body"]


def test_the_guard_checks_each_section_separately():
    """One call per section, not one for the concatenation.

    Measured against the deployed v3: six real reports all scored 0.40-0.81 as
    one block, while their own sections scored 0.63-0.95. Concatenating four
    sections depresses the grounding score below anything a truthful report can
    reach, so the whole-report check could only ever be all-pass or all-fail.
    Per section the signal is sharp (ungrounded probes 0.00-0.34), and a block
    can name which section was wrong.
    """
    guard = _guard()
    bodies = [f"{n} point." for n in (612, 612, 612, 612, 612)]
    fake = FakeAgent([{"heading": h, "body": b}
                      for h, b in zip(ag.HEADINGS, bodies)])
    ag.evaluate(DIGEST, agent=fake, guard=guard)

    guarded = [c["content"][2]["text"]["text"] for c in guard.client.calls]
    assert guarded == bodies
    # Every call carries the full digest as its grounding source: a section is
    # judged against all the facts, not only the ones it happens to quote.
    for call in guard.client.calls:
        assert "412" in call["content"][0]["text"]["text"]


def test_a_block_logs_the_score_and_threshold_not_the_raw_assessment(caplog):
    """The raw assessments dict is ~700 characters of invocationMetrics and ARNs
    per block, several per meet -- it pushed the one line that says which meet was
    refused off the screen. Score vs threshold is the whole actionable content:
    0.13 is prose the digest cannot support, 0.49 is a near miss."""
    client = FakeGuardrailClient()
    client.action_for = {"tredje": "GUARDRAIL_INTERVENED"}
    client.assessments = [{"contextualGroundingPolicy": {"filters": [
        {"type": "GROUNDING", "threshold": 0.5, "score": 0.13,
         "action": "BLOCKED", "detected": True}]}}]
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3", client=client)
    sections = [{"heading": h, "body": b} for h, b in
                zip(ag.HEADINGS, ["a.", "b.", "c i tredje.", "d.", "e."])]

    with caplog.at_level("DEBUG", logger="evaluation"):
        assert guard.check(sections, "{}") == ag.HEADINGS[2]

    line = next(r.getMessage() for r in caplog.records if r.levelname == "INFO")
    assert ag.HEADINGS[2] in line and "GROUNDING" in line
    assert "0.13" in line and "0.5" in line
    assert "invocationMetrics" not in line            # not the raw dict
    # Still recoverable when an unrecognised policy fires: the full assessment
    # goes to DEBUG rather than nowhere.
    debug = "\n".join(r.getMessage() for r in caplog.records if r.levelname == "DEBUG")
    assert "contextualGroundingPolicy" in debug


def test_a_block_names_the_offending_section():
    """The operator's only signal is the log line, and "the guardrail blocked
    the report" for a four-section report leaves them re-deriving which part."""
    client = FakeGuardrailClient()
    client.action_for = {"tredje": "GUARDRAIL_INTERVENED"}
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3",
                           client=client)
    bodies = ["612 point.", "612 point.", "612 point i tredje.", "612 point.",
              "612 point."]
    report = [{"heading": h, "body": b} for h, b in zip(ag.HEADINGS, bodies)]
    fake = FakeAgent(report, [dict(s) for s in report])   # the retry offends too
    with pytest.raises(ag.EvaluationError, match=ag.HEADINGS[2]):
        ag.evaluate(DIGEST, agent=fake, guard=guard, retries=1)
    # Each attempt stops at the first blocked section rather than paying for
    # the rest: 3 calls, then the retry's 3.
    assert len(client.calls) == 6


def test_evaluate_raises_when_the_output_guardrail_intervenes():
    guard = _guard("GUARDRAIL_INTERVENED")
    fake = FakeAgent(_sections("612 point."), _sections("612 point."))
    with pytest.raises(ag.EvaluationError, match="guardrail"):
        ag.evaluate(DIGEST, agent=fake, guard=guard, retries=1)


def test_a_guardrail_block_is_retried_like_a_bad_number():
    """A grounding block is the same class of failure as a fabricated number —
    one section drifted off the digest — and it costs the whole meet's section
    on the page. Measured on the first real run against a working guardrail: 2
    of 3 meets were blocked, each on a single section carrying a causal claim
    ("dette skyldes …", "er således en væsentlig forklarende faktor"), which
    SYSTEM_PROMPT rule 6 already forbids. The retry that already exists for
    numbers recovers those; without it, a compliant report on the second
    attempt is thrown away unread.
    """
    client = FakeGuardrailClient()
    client.action_for = {"skyldes": "GUARDRAIL_INTERVENED"}
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3", client=client)
    fake = FakeAgent(_sections("612 point. Dette skyldes flere deltagere."),
                     _sections("612 point."))
    out = ag.evaluate(DIGEST, agent=fake, guard=guard)
    assert len(fake.prompts) == 2
    assert "612 point." == out[0]["body"]
    # The rewrite instruction has to name the offence, or the model has nothing
    # to correct — it cannot see the guardrail's verdict.
    assert "grounding" in fake.prompts[1].lower() or "digest" in fake.prompts[1]


def test_a_guardrail_retry_names_the_blocked_section():
    client = FakeGuardrailClient()
    client.action_for = {"tredje": "GUARDRAIL_INTERVENED"}
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3", client=client)
    bodies = ["612 point.", "612 point.", "612 point i tredje.", "612 point.",
              "612 point."]
    fake = FakeAgent([{"heading": h, "body": b}
                      for h, b in zip(ag.HEADINGS, bodies)],
                     _sections("612 point."))
    ag.evaluate(DIGEST, agent=fake, guard=guard)
    assert ag.HEADINGS[2] in fake.prompts[1]


def test_evaluate_guards_only_the_report_it_is_about_to_return():
    """No point paying for an ApplyGuardrail call on a report the number check
    already rejected — and the retry's replacement text must be guarded too."""
    guard = _guard()
    fake = FakeAgent(_sections("Median var 777 point."),      # rejected
                     _sections("Median var 612 point."))      # returned
    out = ag.evaluate(DIGEST, agent=fake, guard=guard)
    guarded = [c["content"][2]["text"]["text"] for c in guard.client.calls]
    assert guarded == [s["body"] for s in out]      # the retry's text, once each
    assert not any("777" in g for g in guarded)


def test_evaluate_never_guards_a_report_that_fails_the_number_check():
    guard = _guard()
    fake = FakeAgent(_sections("777 point."), _sections("888 point."))
    with pytest.raises(ag.EvaluationError):
        ag.evaluate(DIGEST, agent=fake, guard=guard, retries=1)
    assert guard.client.calls == []


def test_evaluate_refuses_to_run_without_a_guard():
    """Not a fallback: reaching evaluate() with no guardrail is a bug in the
    caller, and the whole point of this wave is that the published text is
    never unguarded."""
    fake = FakeAgent(_sections("612 point."))
    with pytest.raises(ValueError, match="OutputGuard"):
        ag.evaluate(DIGEST, agent=fake, guard=None)


def test_output_guard_request_is_valid_against_the_real_bedrock_api():
    """botocore's Stubber validates the request against the real service model
    without any network call, so a misspelled key or an unsupported qualifier
    can't reach production — the alternative is finding out mid-batch."""
    client = boto3.client("bedrock-runtime", region_name=ag.REGION)
    guard = ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3", client=client)
    with Stubber(client) as stub:
        stub.add_response(
            "apply_guardrail",
            {"usage": dict.fromkeys(
                ["topicPolicyUnits", "contentPolicyUnits", "wordPolicyUnits",
                 "sensitiveInformationPolicyUnits",
                 "sensitiveInformationPolicyFreeUnits",
                 "contextualGroundingPolicyUnits"], 0),
             "action": "NONE", "outputs": [], "assessments": []},
            {"guardrailIdentifier": "gr-1", "guardrailVersion": "3",
             "source": "OUTPUT",
             "content": [
                 {"text": {"text": "{}", "qualifiers": ["grounding_source"]}},
                 {"text": {"text": ag.GUARD_QUERY, "qualifiers": ["query"]}},
                 {"text": {"text": "rapporten"}},
             ]})
        guard.check([{"heading": ag.HEADINGS[0], "body": "rapporten"}], "{}")
        stub.assert_no_pending_responses()


def test_output_guard_refuses_a_draft_or_blank_guardrail():
    client = FakeGuardrailClient()
    with pytest.raises(ValueError, match="guardrail_version"):
        ag.OutputGuard(guardrail_id="gr-1", guardrail_version="DRAFT", client=client)
    with pytest.raises(ValueError, match="guardrail_id"):
        ag.OutputGuard(guardrail_id="", guardrail_version="3", client=client)


def test_schema_rejects_a_wrong_heading_set():
    with pytest.raises(Exception):
        ag.MeetEvaluation(sections=[{"heading": "Noget andet", "body": "x"}])


def test_schema_rejects_the_right_headings_in_the_wrong_order():
    """Section identity and order are a guarantee the frontend leans on: it
    keys its {#each} on s.heading, so a reordered or short section list changes
    what the page renders where. Only the per-Section heading validator was
    tested, which leaves MeetEvaluation.all_four_in_order free to be a no-op."""
    reordered = list(reversed(ag.HEADINGS))
    with pytest.raises(Exception, match="in order"):
        ag.MeetEvaluation(
            sections=[{"heading": h, "body": "x"} for h in reordered])


def test_schema_rejects_a_missing_section():
    with pytest.raises(Exception, match="in order"):
        ag.MeetEvaluation(
            sections=[{"heading": h, "body": "x"} for h in ag.HEADINGS[:-1]])


def test_build_agent_wires_region_model_and_a_numbered_guardrail(monkeypatch):
    seen = {}

    class RecordingModel:
        # strands.Agent.__init__ reads model.stateful (a Model base-class
        # property, default False) before this fake ever gets used as a model;
        # set it so the fake satisfies that interface check.
        stateful = False

        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(ag, "BedrockModel", RecordingModel)
    ag.build_agent(model_id="model-x", guardrail_id="gr-1", guardrail_version="3")
    assert seen["region_name"] == "eu-west-1"
    assert seen["model_id"] == "model-x"
    assert seen["guardrail_id"] == "gr-1"
    assert seen["guardrail_version"] == "3"
    assert seen["max_tokens"] == ag.MAX_TOKENS


def test_build_agent_silences_the_streamed_tool_and_text_chatter(monkeypatch, capsys):
    """Strands' default callback_handler prints every tool call ("Tool #17:
    MeetEvaluation") and every text block the model emits, including its
    apologies to itself mid-retry. Across 41 meets that is the bulk of the
    output and none of it is a batch signal -- the per-meet outcome lines are.
    """
    class RecordingModel:
        stateful = False

        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(ag, "BedrockModel", RecordingModel)
    agent = ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                           guardrail_version="3")
    # strands normalises callback_handler=None to its own null handler, so assert
    # what matters: not the printing one, and it emits nothing.
    agent.callback_handler(data="hello", complete=True,
                           current_tool_use={"name": "MeetEvaluation"})
    assert capsys.readouterr().out == ""


def test_build_agent_does_not_pass_the_deprecated_cache_prompt(monkeypatch):
    """strands 1.50.1 warns cache_prompt is deprecated, and SYSTEM_PROMPT is
    well under Anthropic-on-Bedrock's minimum cacheable prompt length, so the
    cache point could never have produced a hit. It also once mis-diagnosed a
    non-Anthropic candidate as "no model access"."""
    seen = {}

    class RecordingModel:
        stateful = False

        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(ag, "BedrockModel", RecordingModel)
    ag.build_agent(model_id="model-x", guardrail_id="gr-1", guardrail_version="3")
    assert "cache_prompt" not in seen


def test_build_agent_refuses_a_draft_guardrail():
    with pytest.raises(ValueError):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="DRAFT")


def test_build_agent_refuses_a_padded_draft_guardrail():
    with pytest.raises(ValueError):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="  DRAFT  ")


def test_build_agent_refuses_a_whitespace_only_guardrail_version():
    with pytest.raises(ValueError, match="guardrail_version"):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="   ")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_build_agent_refuses_a_blank_guardrail_id(bad):
    """The asymmetry this closes is backwards: BedrockModel gates the whole
    guardrailConfig on BOTH id and version being truthy, so a bad version
    fails loudly at Bedrock while a blank id produces a completely unguarded
    Converse call with no error at all."""
    with pytest.raises(ValueError, match="guardrail_id"):
        ag.build_agent(model_id="model-x", guardrail_id=bad, guardrail_version="3")


# Pinned so the version constants cannot drift from what they version. Commit
# bc1cadf on this branch edited SYSTEM_PROMPT without bumping PROMPT_VERSION and
# was caught only by a human eye during review; had it shipped, the full-set
# generation would have mixed text from two different prompts under one cache
# key -- the cache-determinism guarantee failing silently, which is the only way
# it can fail. Update these hashes in the same commit as the version bump.
SYSTEM_PROMPT_SHA256 = "eb4c27ca9068afdfdea37d134b94af5a8c3a2feeb956e4d246754a0718ab0f0b"
SCHEMA_SHA256 = "84c8fb754611963b7b76bbaae680f39b28ef6616468eea266c3c3c2212b8cf9e"


def test_system_prompt_is_pinned_to_prompt_version():
    actual = hashlib.sha256(ag.SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    assert actual == SYSTEM_PROMPT_SHA256, (
        f"SYSTEM_PROMPT changed (sha256 now {actual}). Bump ag.PROMPT_VERSION "
        f"(currently {ag.PROMPT_VERSION!r}) so every meet regenerates, then set "
        f"SYSTEM_PROMPT_SHA256 in this test to the new hash. HEADINGS is "
        f"interpolated into the prompt, so a heading change lands here too.")


def test_output_schema_is_pinned_to_schema_version():
    schema = json.dumps(ag.MeetEvaluation.model_json_schema(), sort_keys=True)
    actual = hashlib.sha256(schema.encode("utf-8")).hexdigest()
    assert actual == SCHEMA_SHA256, (
        f"MeetEvaluation's JSON schema changed (sha256 now {actual}). Bump "
        f"ag.SCHEMA_VERSION (currently {ag.SCHEMA_VERSION!r}) so every meet "
        f"regenerates, then set SCHEMA_SHA256 in this test to the new hash.")


def test_model_label_falls_back_to_the_id():
    assert ag.model_label("something-unmapped") == "something-unmapped"


def test_the_output_schema_enumerates_the_allowed_headings():
    """The heading must be a schema enum, not a post-hoc validator.

    Measured on the first full-set run: Haiku misspelled one heading
    ("Fremhævede svømminger" for "svømninger"), the validator rejected it, and
    strands re-called the tool 105 times on that single meet before the model
    gave up and asked "could you please verify the exact heading format the
    MeetEvaluation tool accepts". It could not see the answer: `unknown heading:
    'X'` names the offender and not the alternatives. That runaway loop
    contributed to exhausting the account's daily token quota, which stalled the
    rest of the batch. An enum puts the four legal strings in the tool schema the
    model reads before it writes anything.
    """
    schema = ag.MeetEvaluation.model_json_schema()
    section = schema["$defs"]["Section"]["properties"]["heading"]
    assert section.get("enum") == list(ag.HEADINGS)


def test_a_bad_heading_error_names_the_allowed_headings():
    """The model's only feedback channel is the validation message."""
    with pytest.raises(Exception) as e:
        ag.Section(heading="Fremhævede svømminger", body="x")
    for heading in ag.HEADINGS:
        assert heading in str(e.value)


def test_evaluate_caps_the_tool_loop_with_a_token_budget():
    """The measured incident this exists for: a rejected structured-output field
    made strands re-call the tool 105 times on ONE meet. Each re-call resends the
    whole conversation plus every prior rejection, so input grows per call and the
    total grows quadratically — that single meet cost roughly 1.4M input tokens.
    Across the batch the day's Bedrock bill was ~28M input tokens / $30.87
    against an expected ~0.2M / $0.29.

    strands' MAX_ATTEMPTS=6 does not help: it governs *throttle* retries, not the
    agentic tool loop, which recurses as long as the model keeps calling the
    tool. `limits` is the per-invocation cap that does bound it, and it must be
    passed at every call site — an omitted `limits=` is an uncapped meet.
    """
    fake = FakeAgent(_sections("612 point."))
    ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert fake.kwargs[0]["limits"] == ag.LIMITS


def test_the_token_budget_leaves_room_for_a_healthy_meet():
    """A real meet spends ~3k input and ~700 output tokens per attempt, so the
    caps have to sit far above that or they would fire on healthy work — while
    still being small enough that a runaway loop cannot reach 1.4M."""
    assert ag.LIMITS["total_tokens"] >= 20_000
    assert ag.LIMITS["total_tokens"] <= 200_000
    assert ag.LIMITS["turns"] >= 3
    assert ag.LIMITS["turns"] <= 12


def test_evaluate_raises_when_the_token_budget_stops_the_loop():
    """A capped loop must fail the meet loudly. strands ends the invocation with
    a `limit_*` stop reason and no structured output — indistinguishable from a
    healthy empty answer unless we name it, which is exactly how the 105-call
    meet surfaced as an unexplained traceback the first time."""
    fake = FakeAgent(FakeResult(None, stop_reason="limit_total_tokens"))
    with pytest.raises(ag.EvaluationError, match="token budget"):
        ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert len(fake.prompts) == 1     # a budget trip is not retried: retrying pays again


def test_a_wrong_gendered_event_is_rewritten_before_publishing():
    """DM-L/9775 published "Pauline Mahieu ... vandt herrernes 50m Ryg" against
    a digest row reading "F 50m Ryg (LCM)". check_numbers cannot see it (every
    figure was right) and the guardrail barely can — measured on that section,
    0.88 grounding as published against 0.92 with only the gender corrected. So
    the deterministic check has to gate it, like a fabricated number does."""
    d = {**DIGEST, "top_swims": [{"name": "Pauline Mahieu", "club": "Frankrig",
                                  "event": "F 50m Ryg (LCM)", "time": "28.50",
                                  "points": 848, "rank": 1}]}
    fake = FakeAgent(_sections("Hun vandt herrernes 50m Ryg."),   # wrong gender
                     _sections("Hun vandt damernes 50m Ryg."))    # fixed
    out = ag.evaluate(d, agent=fake, guard=_guard())
    assert len(fake.prompts) == 2
    assert "herrernes 50m Ryg" in fake.prompts[1]     # the flip is quoted back
    assert "damernes" in out[0]["body"]


def test_a_wrong_gendered_event_that_survives_every_retry_raises():
    d = {**DIGEST, "top_swims": [{"name": "Pauline Mahieu", "club": "Frankrig",
                                  "event": "F 50m Ryg (LCM)", "time": "28.50",
                                  "points": 848, "rank": 1}]}
    fake = FakeAgent(*[_sections("Hun vandt herrernes 50m Ryg.") for _ in range(2)])
    with pytest.raises(ag.EvaluationError, match="gender"):
        ag.evaluate(d, agent=fake, guard=_guard(), retries=1)


def test_a_misattributed_result_is_rewritten_before_publishing():
    """A regenerated DMJ-L/11712 credited Lucas Linderoth with Mathias Hald's
    772-point 1500m Fri. Every number was real, so check_numbers passed and the
    guardrail passed — only the name-to-figure binding was wrong."""
    d = {**DIGEST, "top_swims": [
        {"name": "Mathias Hald", "club": "Lyngby", "event": "M 1500m Fri (LCM)",
         "time": "15:48.80", "points": 772, "rank": 1},
        {"name": "Lucas Linderoth", "club": "Sigma", "event": "M 100m Fri (LCM)",
         "time": "50.67", "points": 767, "rank": 1}]}
    fake = FakeAgent(_sections("Lucas Linderoth vandt med 772 point."),   # wrong
                     _sections("Mathias Hald vandt med 772 point."))      # fixed
    out = ag.evaluate(d, agent=fake, guard=_guard())
    assert len(fake.prompts) == 2
    assert "Lucas Linderoth: 772" in fake.prompts[1]
    assert "Mathias Hald" in out[0]["body"]


def test_the_prompt_and_schema_carry_the_club_section():
    """HEADINGS feeds three things at once: the SYSTEM_PROMPT text, the Literal
    in the Section tool schema, and MeetEvaluation's order validator. A heading
    the model cannot see in the schema is the failure that cost 105 tool calls
    on one meet."""
    assert ag.HEADINGS[-1] == "Klubberne"
    assert len(ag.HEADINGS) == 5
    assert "Klubberne" in ag.SYSTEM_PROMPT
    # The two blocks the new rules point at must be named in the prompt, or the
    # model has no way to know they exist.
    assert "digest.clubs" in ag.SYSTEM_PROMPT
    assert "digest.multi_title_swimmers" in ag.SYSTEM_PROMPT
    # Both versions are in the cache key; a section change that does not move
    # them republishes four-section text forever.
    assert (ag.PROMPT_VERSION, ag.SCHEMA_VERSION) == ("7", "3")


def test_the_retry_prompt_points_at_the_precomputed_title_count():
    """The old text told the model to never total up a swimmer's wins. The
    digest now carries the total, so the instruction has to point at it."""
    prompt = ag._prompt("{}", misattributed={"Emilie Beckmann: 764"})
    assert "digest.multi_title_swimmers" in prompt
    assert "never total up a swimmer's wins" not in prompt


def test_gender_rules_name_both_blocks_that_can_carry_the_marker():
    """check_genders judges events inside multi_title_swimmers[].wins too, but
    the rule and the retry prompt used to name only top_swims -- so a gendered
    event that exists only inside a win pointed the model's rewrite at a
    top_swims list where that event never appears, burning every retry."""
    assert ("digest.multi_title_swimmers[].wins carries a gender marker"
            in ag.SYSTEM_PROMPT)
    prompt = ag._prompt("{}", wrong_gender={"damernes 200m IM"})
    assert "digest.top_swims" in prompt
    assert "digest.multi_title_swimmers[].wins" in prompt


def test_clubs_rule_does_not_overclaim_on_the_junior_path():
    """On the junior path digest.clubs comes from junior_championship, which
    holds only juniors with a qualifying swim -- so "every swimmer each club
    entered" understates a club's actual entry. The rule must describe what
    the digest counted, not claim it is everyone entered."""
    assert "the number of swimmers each club entered" not in ag.SYSTEM_PROMPT
    assert "the number of the club's swimmers the digest counted" in ag.SYSTEM_PROMPT


# --- plain_prose ------------------------------------------------------------

@pytest.mark.parametrize("raw, want", [
    # The two forms actually published: raw marker, and Danish word + course.
    ("vandt M 100m Fly (SCM) med 51.76",
     "vandt herrernes 100m Fly med 51.76"),
    ("F 400m Fri (LCM) med 667 point",
     "Damernes 400m Fri med 667 point"),
    ("standarden i herrernes 400m Fri (LCM) med tiden",
     "standarden i herrernes 400m Fri med tiden"),
    # Mixed relay: marker dropped, no Danish word invented.
    ("i X 4x50m HM (SCM) blev", "i 4x50m HM blev"),
    # A sentence that merely contains a distance is left alone.
    ("Han svømmede 50m Ryg på 24.66", "Han svømmede 50m Ryg på 24.66"),
])
def test_plain_prose(raw, want):
    assert ag.plain_prose(raw) == want


def test_non_danish_prose_is_rewritten_before_publishing():
    """The fourth failure class. Haiku published "Agfs Svømmeafdeling førtede
    medaljeantallet" — every figure real, the guardrail content-grounded, and
    "førtede" is not a Danish word. Nothing gated language until now."""
    fake = FakeAgent(_sections("Klubben førtede med 612 point."),   # not Danish
                     _sections("Klubben førte med 612 point."))     # fixed
    out = ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert len(fake.prompts) == 2
    assert "førtede" in fake.prompts[1]          # the word is quoted back
    assert "førte" in out[0]["body"]


def test_non_danish_prose_that_survives_every_retry_raises():
    fake = FakeAgent(*[_sections("Klubben førtede med 612 point.") for _ in range(2)])
    with pytest.raises(ag.EvaluationError, match="not Danish"):
        ag.evaluate(DIGEST, agent=fake, guard=_guard(), retries=1)


def test_the_language_retry_prompt_names_the_rule_it_broke():
    prompt = ag._prompt("{}", foreign={"digest", "derived"})
    assert "derived, digest" in prompt          # sorted, like every other branch
    assert "dansk" in prompt.lower() or "Danish" in prompt


@pytest.mark.parametrize("raw, want", [
    # DM-L/10334: digest.clubs[].swimmers is just how many of the club's
    # swimmers competed, but prompt rule 10 calls it "the swimmers the digest
    # counted", and the model rendered that as the Danish idiom for counting
    # toward a standing ("tællende kampe"). No gate can see it — 31 is in the
    # digest, every word is Danish, and the sentence is grounded.
    ("6 titler, 18 podiepladser og 31 tællende svømmere.",
     "6 titler, 18 podiepladser og 31 svømmere."),
    # The plain forms the same section already uses are left alone.
    ("4 titler og 8 podiepladser fra 7 svømmere.",
     "4 titler og 8 podiepladser fra 7 svømmere."),
])
def test_plain_prose_drops_the_counting_swimmers_idiom(raw, want):
    assert ag.plain_prose(raw) == want


@pytest.mark.parametrize("raw, want", [
    ("Niveauet var uændret — 612 point i median.",
     "Niveauet var uændret - 612 point i median."),
    # The en-dash is the same defect and worse: it corrupts a club name the
    # digest spells with a plain hyphen ("GTI - Greve"), which is the string
    # check_attribution masks on.
    ("Karoline Barrett, GTI – Greve, vandt.", "Karoline Barrett, GTI - Greve, vandt."),
    # A hyphen already in the text is untouched, ranges included.
    ("præsterede på 720-750 point", "præsterede på 720-750 point"),
])
def test_plain_prose_normalizes_typographic_dashes(raw, want):
    assert ag.plain_prose(raw) == want


def test_plain_prose_repairs_the_podium_vocabulary():
    """The model cannot spell this family and answers a rejection with a fresh
    misspelling, so it is repaired rather than gated. Safe because every observed
    occurrence sat in the club table's podiums slot ("6 titler, 12 pokaler")."""
    for bad in ("pokaler", "pokalpladser", "pokaliepladser", "pokalieplaceringer",
                "pokaljepladser", "podieplaceringe", "podieplacerninger",
                "podieplacerigner", "podieplaceriner"):
        assert ag.plain_prose(f"6 titler, 12 {bad} og 16 svømmere.") == (
            "6 titler, 12 podiepladser og 16 svømmere."), bad
    for good in ("podiepladser", "podieplaceringer", "podieplaceringerne"):
        assert ag.plain_prose(f"12 {good}.") == f"12 {good}."
    # A correct singular is left alone, and so is unrelated prose.
    assert ag.plain_prose("hans eneste podieplacering") == "hans eneste podieplacering"


def test_plain_prose_swaps_the_english_terms_with_a_fixed_danish_word():
    """Same reasoning as the podium family: DM-K/10976 answered four rejections
    with "46 events" every time. These have one unambiguous Danish word each, so
    they are repaired. "digest"/"derived" are NOT here — they arrive inside a
    phrase ("digest.derived angiver 0 procent") where dropping a token leaves
    broken prose, so those stay gated."""
    cases = {
        "Stævnet blev afviklet over 46 events.": "Stævnet blev afviklet over 46 discipliner.",
        "Alle strokes lå under niveauet.": "Alle stilarter lå under niveauet.",
        "8 titler og 13 podiums.": "8 titler og 13 podiepladser.",
        "viser negative deltas i forhold til": "viser negative forskelle i forhold til",
        "På tværs af slagarter og distancer": "På tværs af stilarter og distancer",
    }
    for raw, want in cases.items():
        assert ag.plain_prose(raw) == want
    # Sentence-initial keeps its capital.
    assert ag.plain_prose("Events fordelte sig jævnt.") == "Discipliner fordelte sig jævnt."


def test_plain_prose_covers_the_whole_counted_swimmers_and_podium_families():
    """Both families came back in new spellings after the first fix: rule 10's
    "counted swimmers" as tællede/tællesvømmere, and the podium word as
    palleplaceringer (a pallet). Families, not spellings — again."""
    for bad in ("31 tællende svømmere", "31 tællede svømmere", "31 tællesvømmere"):
        assert ag.plain_prose(f"18 podiepladser og {bad}.") == (
            "18 podiepladser og 31 svømmere."), bad
    assert ag.plain_prose("8 titler, 17 palleplaceringer og 32 svømmere.") == (
        "8 titler, 17 podiepladser og 32 svømmere.")
    assert ag.plain_prose("mod et femårsnit på 518 point") == (
        "mod et femårssnit på 518 point")
    # "tæller" as a verb is untouched: it is always followed by a count, never
    # by "svømmere" directly.
    assert ag.plain_prose("Stævnet tæller 265 juniorer.") == "Stævnet tæller 265 juniorer."
