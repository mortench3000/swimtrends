"""run_cycle orchestration with injected fakes (no AWS, deterministic clock)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ingestion import dispatcher
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME

CPH = ZoneInfo("Europe/Copenhagen")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=CPH)


class Recorder:
    """Captures run_task launches and notifications."""

    def __init__(self):
        self.launched = []
        self.notes = []

    def run_task(self, meet_id, category):
        self.launched.append((meet_id, category))

    def notify(self, subject, message):
        self.notes.append((subject, message))


def test_skips_meets_before_window(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 11, 12), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == []
    assert rec.launched == []


def test_dispatches_when_in_window_and_results_present(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DM-L", "DMJ-L"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == ["1"]
    assert rec.launched == [("1", ["DM-L", "DMJ-L"])]
    assert reg.get("1")["status"] == "scraping"


def test_in_window_but_no_results_yet_leaves_scheduled(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify)
    assert dispatched == []
    assert reg.get("1")["status"] == "scheduled"


def test_deadline_forces_dispatch_and_notifies(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 16, 8), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify)
    assert dispatched == ["1"]
    assert rec.launched == [("1", ["DO"])]
    assert any("deadline" in s.lower() for s, _ in rec.notes)


def test_force_bypasses_gates(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    # now is before the window, results absent — force overrides both.
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 11, 1), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify, force=True)
    assert dispatched == ["1"]


def test_meet_ids_filter_restricts_cycle(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    reg.put_meet("2", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify,
        meet_ids=["2"], force=True)
    assert dispatched == ["2"]


def test_exhausted_attempts_are_skipped(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    for _ in range(3):  # drive attempts to max_attempts=3, status failed
        reg.claim("1")
        reg.mark_failed("1", "boom")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify, max_attempts=3)
    assert dispatched == []


def test_run_task_failure_marks_failed_and_notifies(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()

    def boom(meet_id, category):
        raise RuntimeError("ECS RunTask rejected")

    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=boom,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == []
    assert reg.get("1")["status"] == "failed"
    assert any("failed" in s.lower() for s, _ in rec.notes)
