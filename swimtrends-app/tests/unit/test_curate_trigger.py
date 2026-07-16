"""Unit tests for the curate-trigger Lambda handler.

S3 event notifications URL-encode the object key, so a raw upload at
'raw/meet=9780/results.jsonl' is delivered to the handler as
'raw/meet%3D9780/results.jsonl'. The handler must decode the key, launch exactly
one curate task per matching meet, and surface RunTask failures rather than
silently swallowing them.
"""
import sys
from pathlib import Path

import pytest

LAMBDA_DIR = Path(__file__).resolve().parents[2] / "lambda_curate_trigger"
sys.path.insert(0, str(LAMBDA_DIR))

import curate_trigger  # noqa: E402


class FakeEcs:
    def __init__(self, failures=None):
        self.calls = []
        self._failures = failures or []

    def run_task(self, **kwargs):
        self.calls.append(kwargs)
        return {"tasks": [{"taskArn": "arn:aws:ecs:::task/x"}],
                "failures": self._failures}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in {
        "ECS_CLUSTER": "cluster",
        "TASK_DEFINITION": "td",
        "CONTAINER_NAME": "curate",
        "SUBNET_IDS": "subnet-1,subnet-2",
        "SECURITY_GROUP_ID": "sg-1",
    }.items():
        monkeypatch.setenv(k, v)


def _event(*keys):
    return {"Records": [{"s3": {"object": {"key": k}}} for k in keys]}


def _patch_ecs(monkeypatch, fake):
    monkeypatch.setattr(curate_trigger.boto3, "client", lambda service: fake)


def test_decodes_url_encoded_key_and_launches(monkeypatch):
    # The realistic case: S3 percent-encodes the '=' in the Hive-style partition.
    fake = FakeEcs()
    _patch_ecs(monkeypatch, fake)
    out = curate_trigger.lambda_handler(
        _event("raw/meet%3D9780/results.jsonl"), None)
    assert out == {"launched": ["9780"]}
    assert len(fake.calls) == 1
    env = fake.calls[0]["overrides"]["containerOverrides"][0]["environment"]
    assert {"name": "MEET_ID", "value": "9780"} in env


def test_handles_plain_unencoded_key(monkeypatch):
    fake = FakeEcs()
    _patch_ecs(monkeypatch, fake)
    out = curate_trigger.lambda_handler(
        _event("raw/meet=8609/results.jsonl"), None)
    assert out == {"launched": ["8609"]}
    assert len(fake.calls) == 1


def test_ignores_non_results_object(monkeypatch):
    fake = FakeEcs()
    _patch_ecs(monkeypatch, fake)
    out = curate_trigger.lambda_handler(
        _event("raw/meet%3D9780/races.jsonl"), None)
    assert out == {"launched": []}
    assert fake.calls == []


def test_raises_on_run_task_failure(monkeypatch):
    # A real RunTask failure (capacity, networking) must not be swallowed.
    fake = FakeEcs(failures=[{"reason": "RESOURCE:MEMORY"}])
    _patch_ecs(monkeypatch, fake)
    with pytest.raises(RuntimeError):
        curate_trigger.lambda_handler(
            _event("raw/meet%3D9780/results.jsonl"), None)
