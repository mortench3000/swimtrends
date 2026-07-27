"""Content-addressed store for generated meet evaluations.

The key is a hash of the digest AND the prompt version, schema version and
model id. So: unchanged inputs reuse the stored text verbatim (no model call,
no cost, no drift between refreshes); a deliberate prompt or model change
regenerates every meet, visibly and on purpose.

Revoke by deleting the object, or via `python -m evaluation --force`. The
bucket is versioned, so a regeneration keeps the prior text.
"""
import hashlib
import json

from botocore.exceptions import ClientError

BUCKET = "swimtrends-meet-data"
PREFIX = "evaluations"


def canonical_json(obj) -> str:
    """Byte-stable JSON: sorted keys, no padding, Danish characters intact."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(digest: dict, *, prompt_version: str, schema_version: str,
              model_id: str) -> str:
    material = canonical_json({
        "digest": digest,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "model_id": model_id,
    })
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def s3_key(category: str, meet_id: str, key: str) -> str:
    return f"{PREFIX}/{category}/{meet_id}/{key}.json"


def get(client, category: str, meet_id: str, key: str) -> dict | None:
    try:
        obj = client.get_object(Bucket=BUCKET, Key=s3_key(category, meet_id, key))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read().decode("utf-8"))


def put(client, category: str, meet_id: str, key: str, payload: dict) -> None:
    client.put_object(
        Bucket=BUCKET, Key=s3_key(category, meet_id, key),
        Body=canonical_json(payload).encode("utf-8"),
        ContentType="application/json; charset=utf-8")
