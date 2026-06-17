"""Dispatcher: find due meets and launch one Fargate scrape task per meet.

run_cycle() is pure-ish orchestration with all side effects injected
(run_task, has_results, notify), so it unit-tests without AWS. lambda_handler()
wires the real boto3 + scraper implementations and is the EventBridge/CLI entry.
"""
import os
from datetime import datetime, timedelta, timezone

from ingestion import completion
from ingestion.registry import MeetRegistry

DEFAULT_MAX_ATTEMPTS = 3

# A scrape task that has held its 'scraping' claim longer than this is presumed
# orphaned (its container died before recording a terminal status). Generous
# enough to never reap a genuinely in-progress, politely-throttled scrape.
DEFAULT_REAP_TTL_HOURS = 6


def run_cycle(registry, *, now, run_task, has_results, notify,
              meet_ids=None, force=False, max_attempts=DEFAULT_MAX_ATTEMPTS):
    """Evaluate every scheduled/failed meet and dispatch the due ones.

    Returns the list of meet_ids actually launched this cycle.
    """
    meets = registry.scheduled_meets()
    if meet_ids is not None:
        wanted = set(meet_ids)
        meets = [m for m in meets if m["meet_id"] in wanted]

    dispatched = []
    for meet in meets:
        meet_id = meet["meet_id"]

        # A failed meet that has used up its attempts needs a manual --rescrape.
        if meet.get("status") == "failed" and int(meet.get("attempts", 0)) >= max_attempts:
            continue

        forced_by_deadline = False
        if force:
            pass  # bypass time + completeness gates entirely
        else:
            grace = int(meet.get("grace_hours", completion.DEFAULT_GRACE_HOURS))
            deadline = int(meet.get("deadline_hours", completion.DEFAULT_DEADLINE_HOURS))
            verdict = completion.decide(now, meet["end_date"], grace, deadline)
            if verdict == completion.SKIP:
                continue
            if verdict == completion.CHECK:
                if not has_results(meet_id):
                    continue  # not ready — re-check next hour
            elif verdict == completion.DEADLINE:
                # Past deadline we force-scrape regardless, but only raise the
                # alarm when the page genuinely never showed results. Otherwise
                # every historical backfill (always past deadline) false-alarms.
                forced_by_deadline = not has_results(meet_id)

        # Idempotent claim: lose the race -> another run already took it.
        if not registry.claim(meet_id):
            continue

        category = meet["category"]
        try:
            run_task(meet_id, category)
        except Exception as e:
            registry.mark_failed(meet_id, f"RunTask failed: {e}")
            notify("Swimtrends scrape dispatch FAILED",
                   f"Meet {meet_id}: could not launch scrape task: {e}")
            continue

        if forced_by_deadline:
            notify("Swimtrends deadline-forced scrape",
                   f"Meet {meet_id} dispatched at deadline without a confirmed "
                   f"results page. Verify the meet completed as expected.")
        dispatched.append(meet_id)

    return dispatched


def _claim_is_stale(meet, now, ttl_hours):
    """True if this 'scraping' meet has held its claim past the TTL. A row with
    no claimed_at predates the field (legacy claim) and is treated as stale."""
    claimed_at = meet.get("claimed_at")
    if not claimed_at:
        return True
    claimed = datetime.strptime(claimed_at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)
    return now - claimed >= timedelta(hours=ttl_hours)


def reconcile_raw(read_text, meet_id):
    """Reconstruct scrape counts from the raw zone for an orphaned meet.

    read_text(key) returns the object body as str, or None if it is absent.
    Returns {meet_name, result_count, race_count} when all three raw files are
    present and meet_info is non-empty (a completed scrape with a lost terminal
    write), else None (incomplete — re-scrape instead).
    """
    import json

    prefix = f"raw/meet={meet_id}/"
    info = read_text(prefix + "meet_info.jsonl")
    races = read_text(prefix + "races.jsonl")
    results = read_text(prefix + "results.jsonl")
    if info is None or races is None or results is None:
        return None

    info_lines = [ln for ln in info.splitlines() if ln.strip()]
    if not info_lines:
        return None

    return {
        "meet_name": json.loads(info_lines[0]).get("meet", ""),
        "result_count": sum(1 for ln in results.splitlines() if ln.strip()),
        "race_count": sum(1 for ln in races.splitlines() if ln.strip()),
    }


def run_reaper(registry, *, now, reconcile, notify,
               ttl_hours=DEFAULT_REAP_TTL_HOURS):
    """Resolve meets orphaned in 'scraping' (container died before the terminal
    mark_scraped/mark_failed write). For each stale claim, reconcile from the
    raw zone if the data is all there (a lost terminal write — not a re-scrape),
    otherwise reset to 'failed' so the dispatcher retries it.

    reconcile(meet_id) returns {meet_name, result_count, race_count} when the
    raw files are all present, else None.

    Returns a list of (meet_id, action) where action is reconciled|reclaimed.
    """
    resolved = []
    for meet in registry.scraping_meets():
        meet_id = meet["meet_id"]
        if not _claim_is_stale(meet, now, ttl_hours):
            continue

        counts = reconcile(meet_id)
        if counts is not None:
            registry.mark_scraped(meet_id, counts["meet_name"],
                                  counts["result_count"], counts["race_count"])
            notify("Swimtrends orphaned scrape reconciled",
                   f"Meet {meet_id} was stuck in 'scraping' but its raw data is "
                   f"complete ({counts['result_count']} results / "
                   f"{counts['race_count']} races); reconciled to scraped.")
            resolved.append((meet_id, "reconciled"))
        else:
            registry.mark_failed(
                meet_id, "Reaped: orphaned in 'scraping' past TTL with no "
                "complete raw data in S3.")
            notify("Swimtrends orphaned scrape reclaimed",
                   f"Meet {meet_id} was stuck in 'scraping' with no usable raw "
                   f"data; reset to failed for retry.")
            resolved.append((meet_id, "reclaimed"))

    return resolved


# --------------------------------------------------------------------------
# Lambda wiring (real AWS implementations)
# --------------------------------------------------------------------------

def lambda_handler(event, context):
    """EventBridge (empty event) or CLI ({"meet_ids": [...], "force": bool})."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import boto3

    import scrape_races  # single source of truth for completeness parsing

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    tz = os.environ.get("REFERENCE_TZ", completion.DEFAULT_TZ)
    now = datetime.now(ZoneInfo(tz))

    ecs = boto3.client("ecs")
    sns = boto3.client("sns")
    s3 = boto3.client("s3")
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    raw_bucket = os.environ["RAW_BUCKET"]

    def run_task(meet_id, category):
        ecs.run_task(
            cluster=os.environ["ECS_CLUSTER"],
            taskDefinition=os.environ["TASK_DEFINITION"],
            launchType="FARGATE",
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": os.environ["SUBNET_IDS"].split(","),
                    "securityGroups": [os.environ["SECURITY_GROUP_ID"]],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": os.environ["CONTAINER_NAME"],
                    "environment": [
                        {"name": "MEET_ID", "value": str(meet_id)},
                        {"name": "CATEGORIES", "value": ",".join(category)},
                    ],
                }]
            },
        )

    def notify(subject, message):
        sns.publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)

    def read_text(key):
        try:
            return s3.get_object(Bucket=raw_bucket, Key=key)["Body"].read().decode("utf-8")
        except s3.exceptions.NoSuchKey:
            return None

    event = event or {}
    meet_ids = event.get("meet_ids")

    # On a full cycle (the hourly EventBridge trigger, not a targeted CLI
    # invoke) first reap meets orphaned in 'scraping' by a dead container.
    reaped = []
    if meet_ids is None:
        reaped = run_reaper(
            registry,
            now=now,
            reconcile=lambda mid: reconcile_raw(read_text, mid),
            notify=notify,
            ttl_hours=int(os.environ.get("REAP_TTL_HOURS", DEFAULT_REAP_TTL_HOURS)),
        )

    dispatched = run_cycle(
        registry,
        now=now,
        run_task=run_task,
        has_results=scrape_races.meet_has_results,
        notify=notify,
        meet_ids=meet_ids,
        force=bool(event.get("force", False)),
        max_attempts=int(os.environ.get("MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)),
    )
    return {"dispatched": dispatched, "count": len(dispatched),
            "reaped": reaped}
