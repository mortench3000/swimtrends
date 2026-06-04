"""Curated transform task entrypoint.

run_curate_task() is pure-ish orchestration with all I/O injected (read_text,
get_overrides, write_bytes, notify) so it unit-tests without AWS. main() wires
the real boto3 implementations and is the Fargate container entry."""
import json
import os

from curate import basetimes, parquet, transform

RAW_PREFIX = "raw/meet={meet_id}/"
BASE_TIMES_KEY = "reference/point_base_times.jsonl"


def _read_jsonl(read_text, key):
    return [json.loads(l) for l in read_text(key).splitlines() if l.strip()]


def run_curate_task(*, meet_id, read_text, get_overrides, write_bytes, notify):
    """Transform one meet's raw zone into curated Parquet. Re-raises on failure
    after notifying, so the container exits non-zero."""
    try:
        prefix = RAW_PREFIX.format(meet_id=meet_id)
        meet = _read_jsonl(read_text, prefix + "meet_info.jsonl")[0]
        races = _read_jsonl(read_text, prefix + "races.jsonl")
        results = _read_jsonl(read_text, prefix + "results.jsonl")
        base_times = basetimes.parse(read_text(BASE_TIMES_KEY))
        overrides = get_overrides(meet_id)

        tables = transform.transform_meet(meet, races, results, base_times, overrides)
        season, course = meet["season"], meet["course"]
        counts = {}
        for table_name, rows in tables.items():
            key = parquet.object_key(table_name, season=season, course=course,
                                     meet_id=meet_id)
            write_bytes(key, parquet.write_parquet_bytes(table_name, rows))
            counts[table_name] = len(rows)

        notify("Swimtrends curate SUCCEEDED",
               f"Meet {meet_id} ({meet.get('meet','')}) curated: {counts}")
        return counts
    except Exception as e:
        notify("Swimtrends curate FAILED", f"Meet {meet_id}: {e}")
        raise


def main():
    import boto3

    from curate.overrides import ClassOverrides

    meet_id = os.environ["MEET_ID"]
    bucket = os.environ["CURATED_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    overrides = ClassOverrides(os.environ["OVERRIDES_TABLE"])

    s3 = boto3.client("s3")
    sns = boto3.client("sns")

    def read_text(key):
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    def write_bytes(key, data):
        s3.put_object(Bucket=bucket, Key=key, Body=data)

    run_curate_task(
        meet_id=meet_id,
        read_text=read_text,
        get_overrides=overrides.get_for_meet,
        write_bytes=write_bytes,
        notify=lambda subject, msg: sns.publish(
            TopicArn=topic_arn, Subject=subject[:100], Message=msg),
    )


if __name__ == "__main__":
    main()
