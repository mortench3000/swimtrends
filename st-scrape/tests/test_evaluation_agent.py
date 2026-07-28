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
        self.messages = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
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

    def apply_guardrail(self, **kwargs):
        self.calls.append(kwargs)
        return {"action": self.action, "assessments": [{"topicPolicy": "x"}]}


def _guard(action="NONE"):
    return ag.OutputGuard(guardrail_id="gr-1", guardrail_version="3",
                          client=FakeGuardrailClient(action))


def test_evaluate_returns_the_four_sections_in_order():
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
        ag.evaluate(DIGEST, agent=fake, guard=_guard())
    assert "888" in str(e.value)


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

    assert len(guard.client.calls) == 1
    call = guard.client.calls[0]
    assert call["guardrailIdentifier"] == "gr-1"
    assert call["guardrailVersion"] == "3"
    assert call["source"] == "OUTPUT"
    blocks = call["content"]
    # Contextual grounding needs the source and the query tagged; Converse
    # cannot receive either through a plain string prompt, which is why the
    # 0.85/0.5 thresholds had never once been evaluated.
    assert blocks[0]["text"]["qualifiers"] == ["grounding_source"]
    assert "412" in blocks[0]["text"]["text"]              # the digest
    assert blocks[1]["text"]["qualifiers"] == ["query"]
    # Unqualified = the content to guard, i.e. what we are about to publish.
    assert "qualifiers" not in blocks[2]["text"]
    assert blocks[2]["text"]["text"] == "\n".join(s["body"] for s in out)


def test_evaluate_raises_when_the_output_guardrail_intervenes():
    guard = _guard("GUARDRAIL_INTERVENED")
    fake = FakeAgent(_sections("612 point."))
    with pytest.raises(ag.EvaluationError, match="guardrail"):
        ag.evaluate(DIGEST, agent=fake, guard=guard)


def test_evaluate_guards_only_the_report_it_is_about_to_return():
    """No point paying for an ApplyGuardrail call on a report the number check
    already rejected — and the retry's replacement text must be guarded too."""
    guard = _guard()
    fake = FakeAgent(_sections("Median var 777 point."),      # rejected
                     _sections("Median var 612 point."))      # returned
    ag.evaluate(DIGEST, agent=fake, guard=guard)
    assert len(guard.client.calls) == 1
    assert "612" in guard.client.calls[0]["content"][2]["text"]["text"]


def test_evaluate_never_guards_a_report_that_fails_the_number_check():
    guard = _guard()
    fake = FakeAgent(_sections("777 point."), _sections("888 point."))
    with pytest.raises(ag.EvaluationError):
        ag.evaluate(DIGEST, agent=fake, guard=guard)
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
        guard.check("rapporten", "{}")
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
    assert seen["max_tokens"] == 1200


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


def test_model_label_falls_back_to_the_id():
    assert ag.model_label("something-unmapped") == "something-unmapped"
