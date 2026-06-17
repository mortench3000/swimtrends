"""Dispatcher: find due meets and launch one Fargate scrape task per meet.

run_cycle() is pure-ish orchestration with all side effects injected
(run_task, has_results, notify), so it unit-tests without AWS. lambda_handler()
wires the real boto3 + scraper implementations and is the EventBridge/CLI entry.
"""
import os

from ingestion import completion
from ingestion.registry import MeetRegistry

DEFAULT_MAX_ATTEMPTS = 3


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
    topic_arn = os.environ["SNS_TOPIC_ARN"]

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

    event = event or {}
    dispatched = run_cycle(
        registry,
        now=now,
        run_task=run_task,
        has_results=scrape_races.meet_has_results,
        notify=notify,
        meet_ids=event.get("meet_ids"),
        force=bool(event.get("force", False)),
        max_attempts=int(os.environ.get("MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)),
    )
    return {"dispatched": dispatched, "count": len(dispatched)}
