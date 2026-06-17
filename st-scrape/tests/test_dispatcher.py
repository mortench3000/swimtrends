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


def test_past_deadline_with_results_dispatches_silently(dynamodb_table):
    # A historical backfill is always past its deadline, but the results page
    # has been complete for years. It must scrape WITHOUT the false alarm.
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2021-07-21")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2026, 6, 4, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == ["1"]
    assert rec.launched == [("1", ["DO"])]
    assert rec.notes == []


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


# --------------------------------------------------------------------------
# run_reaper: resolve meets orphaned in 'scraping' when their container died
# --------------------------------------------------------------------------

def _stale_scraping(reg, meet_id):
    """A meet claimed long ago and never finished -> orphaned in 'scraping'."""
    reg.put_meet(meet_id, ["DO"], "2024-07-11")
    reg.claim(meet_id, when="2020-01-01T00:00:00Z")


def test_reaper_reconciles_orphan_with_complete_raw_data(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    _stale_scraping(reg, "8609")
    rec = Recorder()
    # All three raw files are present in S3 -> a lost terminal write.
    reconcile = lambda mid: {"meet_name": "Forced Open", "result_count": 1603,
                             "race_count": 64}
    resolved = dispatcher.run_reaper(
        reg, now=at(2026, 6, 17, 12), reconcile=reconcile, notify=rec.notify)
    assert resolved == [("8609", "reconciled")]
    item = reg.get("8609")
    assert item["status"] == "scraped"
    assert int(item["result_count"]) == 1603
    assert int(item["race_count"]) == 64


def test_reaper_reclaims_orphan_without_raw_data(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    _stale_scraping(reg, "8609")
    rec = Recorder()
    # Raw files absent/incomplete -> nothing to reconcile, reset for retry.
    resolved = dispatcher.run_reaper(
        reg, now=at(2026, 6, 17, 12), reconcile=lambda mid: None,
        notify=rec.notify)
    assert resolved == [("8609", "reclaimed")]
    assert reg.get("8609")["status"] == "failed"
    assert any("8609" in m for _, m in rec.notes)


def test_reaper_leaves_fresh_scraping_meet_alone(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    reg.claim("1", when="2026-06-17T11:30:00Z")  # claimed 30 min ago
    rec = Recorder()

    def fail_if_called(mid):
        raise AssertionError("must not reconcile a fresh scrape")

    resolved = dispatcher.run_reaper(
        reg, now=at(2026, 6, 17, 12), reconcile=fail_if_called,
        notify=rec.notify)
    assert resolved == []
    assert reg.get("1")["status"] == "scraping"


def test_reaper_treats_missing_claimed_at_as_stale(dynamodb_table):
    # Legacy rows claimed before claimed_at existed must still be reapable.
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    dynamodb_table.update_item(
        Key={"meet_id": "1"},
        UpdateExpression="SET #s = :scraping",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":scraping": "scraping"})
    rec = Recorder()
    resolved = dispatcher.run_reaper(
        reg, now=at(2026, 6, 17, 12), reconcile=lambda mid: None,
        notify=rec.notify)
    assert resolved == [("1", "reclaimed")]


def test_reconcile_raw_counts_complete_meet():
    files = {
        "raw/meet=8609/meet_info.jsonl": '{"meet": "Forced Open"}\n',
        "raw/meet=8609/races.jsonl": "a\nb\nc\n",
        "raw/meet=8609/results.jsonl": "1\n2\n\n3\n",  # blank line ignored
    }
    counts = dispatcher.reconcile_raw(lambda key: files.get(key), "8609")
    assert counts == {"meet_name": "Forced Open", "result_count": 3,
                      "race_count": 3}


def test_reconcile_raw_returns_none_when_a_file_is_missing():
    files = {
        "raw/meet=8609/meet_info.jsonl": '{"meet": "X"}\n',
        "raw/meet=8609/races.jsonl": "a\n",
        # results.jsonl absent -> incomplete scrape, cannot reconcile
    }
    assert dispatcher.reconcile_raw(lambda key: files.get(key), "8609") is None


def test_reconcile_raw_returns_none_when_meet_info_empty():
    files = {
        "raw/meet=8609/meet_info.jsonl": "",
        "raw/meet=8609/races.jsonl": "a\n",
        "raw/meet=8609/results.jsonl": "1\n",
    }
    assert dispatcher.reconcile_raw(lambda key: files.get(key), "8609") is None


def test_reaper_ignores_non_scraping_meets(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")  # scheduled, untouched
    rec = Recorder()

    def fail_if_called(mid):
        raise AssertionError("must not touch a scheduled meet")

    resolved = dispatcher.run_reaper(
        reg, now=at(2026, 6, 17, 12), reconcile=fail_if_called,
        notify=rec.notify)
    assert resolved == []
    assert reg.get("1")["status"] == "scheduled"
