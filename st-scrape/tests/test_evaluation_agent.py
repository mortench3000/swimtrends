import pytest

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
    def __init__(self, sections):
        self.structured_output = ag.MeetEvaluation(sections=sections)


class FakeAgent:
    """Stands in for a Strands Agent: records prompts, returns canned reports."""
    def __init__(self, *reports):
        self.reports = list(reports)
        self.prompts = []
        self.messages = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return FakeResult(self.reports.pop(0))


def _sections(body):
    return [{"heading": h, "body": body} for h in ag.HEADINGS]


def test_evaluate_returns_the_four_sections_in_order():
    fake = FakeAgent(_sections("612 point og 412 deltagere."))
    out = ag.evaluate(DIGEST, agent=fake)
    assert [s["heading"] for s in out] == list(ag.HEADINGS)


def test_evaluate_passes_the_digest_in_the_prompt():
    fake = FakeAgent(_sections("612 point."))
    ag.evaluate(DIGEST, agent=fake)
    assert "<digest>" in fake.prompts[0]
    assert "412" in fake.prompts[0]


def test_evaluate_retries_once_when_a_number_is_fabricated():
    fake = FakeAgent(_sections("Median var 777 point."),      # bad
                     _sections("Median var 612 point."))      # good on retry
    out = ag.evaluate(DIGEST, agent=fake)
    assert len(fake.prompts) == 2
    assert "777" in fake.prompts[1]           # the offending token is quoted back
    assert "612" in out[0]["body"]


def test_evaluate_raises_when_the_retry_also_fabricates():
    fake = FakeAgent(_sections("777 point."), _sections("888 point."))
    with pytest.raises(ag.EvaluationError) as e:
        ag.evaluate(DIGEST, agent=fake)
    assert "888" in str(e.value)


def test_evaluate_does_not_carry_history_between_meets():
    """The digest must be the agent's entire world: a caller reusing one agent
    across meets would otherwise leak meet A's content into meet B's prompt,
    and the number check screens numbers only — a leaked name would pass."""
    fake = FakeAgent(_sections("612 point."), _sections("612 point."))
    fake.messages = [{"role": "user", "content": "an earlier meet's conversation"}]
    ag.evaluate(DIGEST, agent=fake)
    assert fake.messages == []


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
    assert seen["cache_prompt"] == "default"


def test_build_agent_refuses_a_draft_guardrail():
    with pytest.raises(ValueError):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="DRAFT")


def test_build_agent_refuses_a_padded_draft_guardrail():
    with pytest.raises(ValueError):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="  DRAFT  ")


def test_model_label_falls_back_to_the_id():
    assert ag.model_label("something-unmapped") == "something-unmapped"
