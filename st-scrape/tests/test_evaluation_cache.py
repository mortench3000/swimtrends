import boto3
import pytest
from moto import mock_aws

from evaluation import cache

DIGEST = {"meet": {"name": "Danish Champs 2026", "season": 2026},
          "facts": {"entrants": 24, "median_points": 500}}
VERSIONS = dict(prompt_version="1", schema_version="1", model_id="model-x",
                guardrail_id="gr-1", guardrail_version="3", max_tokens=1200)


def test_canonical_json_is_order_independent_and_keeps_danish():
    a = cache.canonical_json({"b": 1, "a": "Svømmeklubben Åræø"})
    b = cache.canonical_json({"a": "Svømmeklubben Åræø", "b": 1})
    assert a == b
    assert "Åræø" in a          # not \u-escaped


def test_cache_key_is_stable_across_dict_ordering():
    reordered = {"facts": DIGEST["facts"], "meet": DIGEST["meet"]}
    assert cache.cache_key(DIGEST, **VERSIONS) == cache.cache_key(reordered, **VERSIONS)


def test_cache_key_changes_with_data():
    other = {**DIGEST, "facts": {"entrants": 25, "median_points": 500}}
    assert cache.cache_key(DIGEST, **VERSIONS) != cache.cache_key(other, **VERSIONS)


@pytest.mark.parametrize("field", ["prompt_version", "schema_version", "model_id"])
def test_cache_key_changes_with_prompt_schema_or_model(field):
    bumped = {**VERSIONS, field: "different"}
    assert cache.cache_key(DIGEST, **VERSIONS) != cache.cache_key(DIGEST, **bumped)


@pytest.mark.parametrize("field,value", [("guardrail_id", "gr-2"),
                                         ("guardrail_version", "4"),
                                         ("max_tokens", 600)])
def test_cache_key_changes_with_the_enforcement_layers(field, value):
    """The guardrail is half the safety envelope, so its identity belongs in the
    content address: tightening the policy — a fifth denied topic after someone
    spots a violation class in production — must invalidate already-published
    text, which is precisely when regeneration matters most. max_tokens is a
    genuine input to the text (halving it truncates reports)."""
    changed = {**VERSIONS, field: value}
    assert cache.cache_key(DIGEST, **VERSIONS) != cache.cache_key(DIGEST, **changed)


def test_s3_key_layout():
    assert cache.s3_key("DM-L", "12486", "abc") == "evaluations/DM-L/12486/abc.json"


@mock_aws
def test_get_returns_none_on_miss_and_the_payload_on_hit():
    client = boto3.client("s3", region_name="eu-west-1")
    client.create_bucket(Bucket=cache.BUCKET,
                         CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    key = cache.cache_key(DIGEST, **VERSIONS)
    assert cache.get(client, "DM-L", "12486", key) is None
    payload = {"sections": [{"heading": "Samlet niveau", "body": "Et stærkt DM."}]}
    cache.put(client, "DM-L", "12486", key, payload)
    assert cache.get(client, "DM-L", "12486", key) == payload
