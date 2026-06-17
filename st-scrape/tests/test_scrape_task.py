"""run_scrape_task orchestration with injected scrape/upload/notify fakes."""
import json

import pytest

from ingestion import scrape_task
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def write_db_files(tmp_path, meet_id, n_results, n_races, meet_name):
    (tmp_path / f"{meet_id}_meet_info.jsonl").write_text(
        json.dumps({"meet_id": int(meet_id), "meet": meet_name}) + "\n", encoding="utf-8")
    with open(tmp_path / f"{meet_id}_results.jsonl", "w", encoding="utf-8") as f:
        for i in range(n_results):
            f.write(json.dumps({"race_id": i}) + "\n")
    with open(tmp_path / f"{meet_id}_races.jsonl", "w", encoding="utf-8") as f:
        for i in range(n_races):
            f.write(json.dumps({"race_id": i}) + "\n")


def test_success_uploads_three_files_and_marks_scraped(dynamodb_table, tmp_path):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DM-L"], "2024-07-11")
    reg.claim("10970")
    write_db_files(tmp_path, "10970", n_results=5, n_races=2, meet_name="Danish Open")
    uploaded, notes = [], []

    scrape_task.run_scrape_task(
        meet_id="10970", categories=["DM-L"], db_dir=str(tmp_path),
        registry=reg,
        scrape=lambda mid, cats: None,  # pretend the scraper already wrote files
        upload=lambda local, key: uploaded.append(key),
        notify=lambda subject, msg: notes.append(subject),
        when="2026-06-02T10:00:00Z")

    assert sorted(uploaded) == [
        "raw/meet=10970/meet_info.jsonl",
        "raw/meet=10970/races.jsonl",
        "raw/meet=10970/results.jsonl",
    ]
    item = reg.get("10970")
    assert item["status"] == "scraped"
    assert item["meet_name"] == "Danish Open"
    assert int(item["result_count"]) == 5
    assert int(item["race_count"]) == 2
    assert any("succeeded" in s.lower() for s in notes)


def test_scrape_failure_marks_failed_and_raises(dynamodb_table, tmp_path):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DM-L"], "2024-07-11")
    reg.claim("10970")
    notes = []

    def boom(mid, cats):
        raise RuntimeError("scraper exited 1")

    with pytest.raises(RuntimeError):
        scrape_task.run_scrape_task(
            meet_id="10970", categories=["DM-L"], db_dir=str(tmp_path),
            registry=reg, scrape=boom,
            upload=lambda local, key: None,
            notify=lambda subject, msg: notes.append(subject))
    assert reg.get("10970")["status"] == "failed"
    assert any("failed" in s.lower() for s in notes)


def test_notify_failure_on_success_does_not_flip_to_failed(dynamodb_table, tmp_path):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DM-L"], "2024-07-11")
    reg.claim("10970")
    write_db_files(tmp_path, "10970", n_results=3, n_races=1, meet_name="Danish Open")

    def flaky_notify(subject, msg):
        raise RuntimeError("SNS down")

    # Notify blowing up must NOT raise and must NOT undo the scraped status.
    scrape_task.run_scrape_task(
        meet_id="10970", categories=["DM-L"], db_dir=str(tmp_path),
        registry=reg, scrape=lambda mid, cats: None,
        upload=lambda local, key: None, notify=flaky_notify,
        when="2026-06-02T10:00:00Z")
    assert reg.get("10970")["status"] == "scraped"
