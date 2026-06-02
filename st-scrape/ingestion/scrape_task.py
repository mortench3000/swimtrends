"""Fargate container entrypoint.

Runs scrape_races.py for one meet, uploads the three JSONL outputs to the S3 raw
zone, and records the outcome in the registry + SNS. Orchestration (run_scrape_task)
takes its side effects as callables so it is unit-testable; main() wires the real
subprocess/boto3 implementations from environment variables.
"""
import json
import os
import subprocess
import sys

# ingestion/scrape_task.py -> ingestion/ -> st-scrape/
SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # st-scrape/
SCRAPER = os.path.join(SCRIPT_DIR, "scrape_races.py")
DEFAULT_DB_DIR = os.path.join(SCRIPT_DIR, "db")

# Output filename -> S3 object basename within raw/meet=<id>/.
RAW_FILES = {
    "{meet_id}_meet_info.jsonl": "meet_info.jsonl",
    "{meet_id}_races.jsonl": "races.jsonl",
    "{meet_id}_results.jsonl": "results.jsonl",
}


def _count_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _safe_notify(notify, subject, message):
    """Notifications are auxiliary; the registry is the source of truth. Never
    let a notify failure flip a successful scrape to failed or mask the original
    error on the failure path."""
    try:
        notify(subject, message)
    except Exception as e:  # noqa: BLE001 - best effort
        print(f"notify failed ({subject!r}): {e}", file=sys.stderr)


def run_scrape_task(*, meet_id, categories, db_dir, registry, scrape, upload,
                    notify, when=None):
    """Scrape one meet, upload raw files, update registry. Re-raises on failure
    (after marking failed) so the container exits non-zero."""
    try:
        scrape(meet_id, categories)

        meet_info_path = os.path.join(db_dir, f"{meet_id}_meet_info.jsonl")
        results_path = os.path.join(db_dir, f"{meet_id}_results.jsonl")
        races_path = os.path.join(db_dir, f"{meet_id}_races.jsonl")

        with open(meet_info_path, encoding="utf-8") as f:
            line = f.readline()
        if not line:
            raise ValueError(f"meet_info.jsonl for meet {meet_id} is empty")
        meet_name = json.loads(line).get("meet", "")
        result_count = _count_lines(results_path)
        race_count = _count_lines(races_path)

        for local_template, s3_basename in RAW_FILES.items():
            local = os.path.join(db_dir, local_template.format(meet_id=meet_id))
            upload(local, f"raw/meet={meet_id}/{s3_basename}")

        registry.mark_scraped(meet_id, meet_name, result_count, race_count, when=when)
        _safe_notify(notify, "Swimtrends scrape SUCCEEDED",
                     f"Meet {meet_id} ({meet_name}): {result_count} results across "
                     f"{race_count} races uploaded to raw/meet={meet_id}/.")
    except Exception as e:
        registry.mark_failed(meet_id, str(e), when=when)
        _safe_notify(notify, "Swimtrends scrape FAILED", f"Meet {meet_id}: {e}")
        raise


def _subprocess_scrape(meet_id, categories):
    """Run the real scraper as a child process (keeps scrape_races.py untouched)."""
    subprocess.run([sys.executable, SCRAPER, str(meet_id), *categories],
                   check=True, cwd=SCRIPT_DIR)


def main():
    import boto3

    from ingestion.registry import MeetRegistry

    meet_id = os.environ["MEET_ID"]
    categories = [c for c in os.environ.get("CATEGORIES", "").split(",") if c]
    bucket = os.environ["RAW_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    s3 = boto3.client("s3")
    sns = boto3.client("sns")

    run_scrape_task(
        meet_id=meet_id,
        categories=categories,
        db_dir=DEFAULT_DB_DIR,
        registry=registry,
        scrape=_subprocess_scrape,
        upload=lambda local, key: s3.upload_file(local, bucket, key),
        notify=lambda subject, msg: sns.publish(
            TopicArn=topic_arn, Subject=subject[:100], Message=msg),
    )


if __name__ == "__main__":
    main()
