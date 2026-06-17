"""MeetRegistry against a moto DynamoDB table."""
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def make_registry():
    return MeetRegistry(TABLE_NAME, region="eu-west-1")


def test_put_meet_creates_scheduled_row(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DM-L", "DMJ-L"], "2024-07-11")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scheduled"
    assert item["category"] == ["DM-L", "DMJ-L"]
    assert item["end_date"] == "2024-07-11"
    assert int(item["attempts"]) == 0


def test_put_meet_with_overrides(dynamodb_table):
    reg = make_registry()
    reg.put_meet("11712", ["DM-L"], "2025-04-05", grace_hours=12, deadline_hours=48)
    item = dynamodb_table.get_item(Key={"meet_id": "11712"})["Item"]
    assert int(item["grace_hours"]) == 12
    assert int(item["deadline_hours"]) == 48


def test_scheduled_meets_returns_scheduled_and_failed(dynamodb_table):
    reg = make_registry()
    reg.put_meet("1", ["DO"], "2024-01-01")
    reg.put_meet("2", ["DO"], "2024-01-02")
    reg.claim("2")
    reg.mark_scraped("2", "Meet 2", 10, 3)  # status -> scraped, excluded
    reg.put_meet("3", ["DO"], "2024-01-03")
    reg.claim("3")
    reg.mark_failed("3", "boom")  # status -> failed, included
    ids = {m["meet_id"] for m in reg.scheduled_meets()}
    assert ids == {"1", "3"}


def test_claim_succeeds_once_then_blocks(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    assert reg.claim("10970") is True   # scheduled -> scraping
    assert reg.claim("10970") is False  # already scraping
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scraping"
    assert int(item["attempts"]) == 1


def test_claim_allows_retry_from_failed(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    assert reg.claim("10970") is True  # failed -> scraping again
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert int(item["attempts"]) == 2


def test_mark_scraped_sets_fields_and_clears_error(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "old error")
    reg.claim("10970")
    reg.mark_scraped("10970", "Danish Open 2024", 1234, 74, when="2026-06-02T10:00:00Z")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scraped"
    assert item["meet_name"] == "Danish Open 2024"
    assert int(item["result_count"]) == 1234
    assert int(item["race_count"]) == 74
    assert item["last_scraped_at"] == "2026-06-02T10:00:00Z"
    assert "last_error" not in item


def test_reset_returns_to_scheduled(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    reg.reset("10970")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scheduled"
    assert int(item["attempts"]) == 0
    assert "last_error" not in item


def test_claim_records_claimed_at(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970", when="2026-06-17T09:00:00Z")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["claimed_at"] == "2026-06-17T09:00:00Z"


def test_scraping_meets_returns_only_in_flight(dynamodb_table):
    reg = make_registry()
    reg.put_meet("1", ["DO"], "2024-01-01")  # scheduled
    reg.put_meet("2", ["DO"], "2024-01-02")
    reg.claim("2")  # scraping
    reg.put_meet("3", ["DO"], "2024-01-03")
    reg.claim("3")
    reg.mark_scraped("3", "Meet 3", 10, 3)  # scraped
    reg.put_meet("4", ["DO"], "2024-01-04")
    reg.claim("4")
    reg.mark_failed("4", "boom")  # failed
    ids = {m["meet_id"] for m in reg.scraping_meets()}
    assert ids == {"2"}


def test_mark_scraped_clears_claimed_at(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_scraped("10970", "Meet", 10, 3)
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert "claimed_at" not in item


def test_mark_failed_clears_claimed_at(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "boom")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert "claimed_at" not in item


def test_get_returns_none_for_missing(dynamodb_table):
    reg = make_registry()
    assert reg.get("does-not-exist") is None


def test_put_meet_overwrites_stale_fields(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_scraped("10970", "Old Name", 99, 9)
    reg.put_meet("10970", ["DO"], "2024-07-11")  # re-register
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scheduled"
    assert int(item["attempts"]) == 0
    assert "result_count" not in item
    assert "meet_name" not in item
