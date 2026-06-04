"""CLI curate/class subcommands route to the right injected side effects."""
from ingestion import cli


class FakeRegistry:
    def __init__(self, ids):
        self._ids = ids

    def scheduled_meets(self):  # unused here but matches interface
        return []

    def all_meet_ids(self):
        return self._ids


class FakeOverrides:
    def __init__(self):
        self.calls = []

    def set_override(self, meet_id, race_id, klass, reason=""):
        self.calls.append((meet_id, race_id, klass, reason))


def test_curate_single_meet_invokes_curator():
    invoked = []
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload), overrides=None)
    assert invoked == [{"meet_ids": ["8609"]}]


def test_curate_all_invokes_with_all_flag():
    invoked = []
    cli.run(["curate", "--all"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload), overrides=None)
    assert invoked == [{"all": True}]


def test_class_set_writes_override():
    ov = FakeOverrides()
    cli.run(["class", "set", "8609", "213", "para", "--reason", "para-only"],
            registry=None, invoke=None, curate=None, overrides=ov)
    assert ov.calls == [("8609", 213, "para", "para-only")]
