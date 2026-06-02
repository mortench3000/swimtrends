"""CLI command handling: register hits the registry, dispatch builds the right
Lambda payload."""
import pytest

from ingestion import cli
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def test_register_creates_scheduled_meet(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    cli.run(["register", "10970", "--categories", "DM-L,DMJ-L",
             "--end-date", "2024-07-11"], registry=reg, invoke=None)
    item = reg.get("10970")
    assert item["status"] == "scheduled"
    assert item["category"] == ["DM-L", "DMJ-L"]
    assert item["end_date"] == "2024-07-11"


def test_register_with_overrides(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    cli.run(["register", "11712", "--categories", "DM-L", "--end-date",
             "2025-04-05", "--grace-hours", "12", "--deadline-hours", "48"],
            registry=reg, invoke=None)
    item = reg.get("11712")
    assert int(item["grace_hours"]) == 12
    assert int(item["deadline_hours"]) == 48


def test_rescrape_resets_existing_meet(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    cli.run(["register", "10970", "--rescrape"], registry=reg, invoke=None)
    item = reg.get("10970")
    assert item["status"] == "scheduled"
    assert int(item["attempts"]) == 0
    assert "last_error" not in item


def test_register_existing_without_rescrape_errors(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DO"], "2024-07-11")
    with pytest.raises(SystemExit):
        cli.run(["register", "10970", "--categories", "DO", "--end-date", "2024-07-11"],
                registry=reg, invoke=None)


def test_rescrape_missing_meet_errors(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    with pytest.raises(SystemExit):
        cli.run(["register", "99999", "--rescrape"], registry=reg, invoke=None)


def test_dispatch_force_all_without_all_flag_errors(dynamodb_table):
    with pytest.raises(SystemExit):
        cli.run(["dispatch", "--force"], registry=None, invoke=lambda payload: None)


def test_dispatch_no_args_sends_empty_payload(dynamodb_table):
    calls = []
    cli.run(["dispatch"], registry=None, invoke=lambda payload: calls.append(payload))
    assert calls == [{}]


def test_dispatch_specific_meet_with_force(dynamodb_table):
    calls = []
    cli.run(["dispatch", "10970", "--force"], registry=None,
            invoke=lambda payload: calls.append(payload))
    assert calls == [{"meet_ids": ["10970"], "force": True}]


def test_dispatch_all_force_backfill(dynamodb_table):
    calls = []
    cli.run(["dispatch", "--all", "--force"], registry=None,
            invoke=lambda payload: calls.append(payload))
    assert calls == [{"force": True}]
