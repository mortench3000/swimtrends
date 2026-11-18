"""CLI curate/class subcommands route to the right injected side effects."""
from ingestion import cli


class FakeOverrides:
    def __init__(self):
        self.calls = []

    def set_override(self, meet_id, race_id, klass, reason=""):
        self.calls.append((meet_id, race_id, klass, reason))


def test_curate_single_meet_invokes_curator():
    invoked = []
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload) or {"launched": payload.get("meet_ids", [])},
            overrides=None)
    assert invoked == [{"meet_ids": ["8609"]}]


def test_curate_all_invokes_with_all_flag():
    invoked = []
    cli.run(["curate", "--all"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload) or {"launched": payload.get("meet_ids", [])},
            overrides=None)
    assert invoked == [{"all": True}]


def test_class_set_writes_override():
    ov = FakeOverrides()
    cli.run(["class", "set", "8609", "213", "para", "--reason", "para-only"],
            registry=None, invoke=None, curate=None, overrides=ov)
    assert ov.calls == [("8609", 213, "para", "para-only")]


def test_curate_event_matches_the_s3_trigger_key():
    # The curate trigger Lambda only understands S3 ObjectCreated events on
    # raw/meet=<id>/results.jsonl; a bare {"meet_ids": ...} was a silent no-op.
    assert cli.curate_event(["8609", "12489"]) == {"Records": [
        {"s3": {"object": {"key": "raw/meet=8609/results.jsonl"}}},
        {"s3": {"object": {"key": "raw/meet=12489/results.jsonl"}}},
    ]}


def test_curate_reports_launched_meets(capsys):
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: {"launched": ["8609"]}, overrides=None)
    assert "Curate launched: 8609" in capsys.readouterr().out


def test_curate_fails_loudly_when_meet_not_launched():
    import pytest
    with pytest.raises(SystemExit, match="8609"):
        cli.run(["curate", "8609"], registry=None, invoke=None,
                curate=lambda payload: {"launched": []}, overrides=None)
