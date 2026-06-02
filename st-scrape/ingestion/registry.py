"""DynamoDB access layer for the meet registry.

Status lifecycle: scheduled -> scraping -> (scraped | failed). A failed meet is
retried until max_attempts (enforced by the dispatcher, not here). claim() is the
idempotency guard: a conditional transition to 'scraping' that increments
attempts, so overlapping dispatcher runs cannot double-launch the same meet.
"""
import boto3
from boto3.dynamodb.conditions import Attr

# Statuses the dispatcher may pick up for a (re)scrape.
PICKABLE = ("scheduled", "failed")


class MeetRegistry:
    def __init__(self, table_name, region=None):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put_meet(self, meet_id, category, end_date, grace_hours=None, deadline_hours=None):
        """Insert/overwrite a meet as freshly scheduled."""
        item = {
            "meet_id": meet_id,
            "category": list(category),
            "end_date": end_date,
            "status": "scheduled",
            "attempts": 0,
        }
        if grace_hours is not None:
            item["grace_hours"] = grace_hours
        if deadline_hours is not None:
            item["deadline_hours"] = deadline_hours
        self._table.put_item(Item=item)

    def get(self, meet_id):
        return self._table.get_item(Key={"meet_id": meet_id}).get("Item")

    def scheduled_meets(self):
        """All meets eligible for (re)scraping: status in scheduled|failed."""
        items, kwargs = [], {"FilterExpression": Attr("status").is_in(list(PICKABLE))}
        while True:
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def claim(self, meet_id):
        """Atomically move scheduled|failed -> scraping and bump attempts.
        Returns True if this caller won the claim, False if already taken."""
        try:
            self._table.update_item(
                Key={"meet_id": meet_id},
                UpdateExpression="SET #s = :scraping ADD attempts :one",
                ConditionExpression=Attr("status").is_in(list(PICKABLE)),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":scraping": "scraping", ":one": 1},
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def mark_scraped(self, meet_id, meet_name, result_count, race_count, when=None):
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression=(
                "SET #s = :scraped, meet_name = :n, result_count = :rc, "
                "race_count = :rac, last_scraped_at = :t REMOVE last_error"
            ),
            ConditionExpression=Attr("meet_id").exists(),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":scraped": "scraped",
                ":n": meet_name,
                ":rc": result_count,
                ":rac": race_count,
                ":t": _now_iso() if when is None else when,
            },
        )

    def mark_failed(self, meet_id, error, when=None):
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression="SET #s = :failed, last_error = :e, last_scraped_at = :t",
            ConditionExpression=Attr("meet_id").exists(),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":failed": "failed",
                ":e": str(error)[:1000],
                ":t": _now_iso() if when is None else when,
            },
        )

    def reset(self, meet_id):
        """Manual --rescrape: back to scheduled, attempts zeroed, error cleared."""
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression="SET #s = :scheduled, attempts = :zero REMOVE last_error",
            ConditionExpression=Attr("meet_id").exists(),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":scheduled": "scheduled", ":zero": 0},
        )


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
