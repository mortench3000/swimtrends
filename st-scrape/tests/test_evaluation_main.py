"""The batch CLI's run()/main(): per-meet best-effort behaviour, and the
publication guard that stops web-refresh's --delete sync from firing on a
systemic failure.

S3 is moto (see tests/conftest.py's autouse mocked_aws); the digest comes from
a real in-memory DuckDB (tests/evaluation_fixtures.digest_con); the agent is
never real — build_agent and evaluate are monkeypatched per test so no test
can reach Bedrock.
"""
import json

import boto3
import pytest
from botocore.exceptions import ClientError

from evaluation import __main__ as cli
from evaluation import agent as ag
from evaluation import cache
from tests.evaluation_fixtures import digest_con
from webbuild import digest as dg

CATEGORY = "DM-L"
MEET_A = "D2026"
MEET_B = "D2025"
MODEL_ID = "model-x"
KWARGS = dict(model_id=MODEL_ID, guardrail_id="gr-1", guardrail_version="3")


def _bucket():
    client = boto3.client("s3", region_name="eu-west-1")
    client.create_bucket(Bucket=cache.BUCKET,
                         CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    return client


def _key(con, category, meet_id):
    digest = dg.build(con, category, meet_id)
    return digest, cache.cache_key(digest, prompt_version=ag.PROMPT_VERSION,
                                   schema_version=ag.SCHEMA_VERSION, model_id=MODEL_ID)


def _cached_payload(category, meet_id, body="cached tekst"):
    return {"category": category, "meet_id": meet_id,
            "prompt_version": ag.PROMPT_VERSION, "schema_version": ag.SCHEMA_VERSION,
            "model_id": MODEL_ID, "model_label": MODEL_ID,
            "generated_at": "2026-01-01",
            "sections": [{"heading": h, "body": body} for h in ag.HEADINGS]}


def _valid_sections(digest, body_extra=""):
    """Sections whose only number (entrants) is licensed by the digest, so a
    real ag.evaluate() call (with a FakeAgent) would pass check_numbers."""
    n = digest["facts"]["entrants"]
    return [{"heading": h, "body": f"{n} deltagere. {body_extra}"} for h in ag.HEADINGS]


@pytest.fixture(autouse=True)
def no_real_agent(monkeypatch):
    """Every test replaces build_agent; tests that reach evaluate() replace it
    too. This fixture only stops an accidental real Bedrock construction if a
    test forgets — evaluate itself is stubbed per-test below."""
    monkeypatch.setattr(cli.ag, "build_agent", lambda **kw: object())


def test_cache_hit_skips_evaluate_and_writes_cached_payload_verbatim(tmp_path, monkeypatch):
    con = digest_con()
    digest, key = _key(con, CATEGORY, MEET_A)
    client = _bucket()
    payload = _cached_payload(CATEGORY, MEET_A)
    cache.put(client, CATEGORY, MEET_A, key, payload)

    called = []
    monkeypatch.setattr(cli.ag, "evaluate", lambda *a, **k: called.append(1))

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, MEET_A)], **KWARGS)

    assert not called
    assert stats == {"total": 1, "hit": 1, "generated": 0, "skipped": 0, "written": 1}
    written = json.loads((tmp_path / CATEGORY / MEET_A / "evaluation.json").read_text())
    assert written == payload


def test_force_on_hit_calls_evaluate_and_overwrites_the_cache(tmp_path, monkeypatch):
    con = digest_con()
    digest, key = _key(con, CATEGORY, MEET_A)
    client = _bucket()
    cache.put(client, CATEGORY, MEET_A, key, _cached_payload(CATEGORY, MEET_A, "gammel tekst"))

    new_sections = _valid_sections(digest, "ny tekst.")
    calls = []
    monkeypatch.setattr(cli.ag, "evaluate", lambda d, **k: calls.append(d) or new_sections)

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, MEET_A)], force=True, **KWARGS)

    assert len(calls) == 1
    assert stats == {"total": 1, "hit": 0, "generated": 1, "skipped": 0, "written": 1}
    stored = cache.get(client, CATEGORY, MEET_A, key)
    assert stored["sections"] == new_sections


def test_digest_failure_skips_the_meet_and_writes_nothing(tmp_path):
    con = digest_con()
    _bucket()

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, "NOPE")], **KWARGS)

    assert stats == {"total": 1, "hit": 0, "generated": 0, "skipped": 1, "written": 0}
    assert not (tmp_path / CATEGORY).exists()


def test_empty_digest_skips_without_calling_evaluate_or_touching_the_cache(
        tmp_path, monkeypatch):
    """"NOPE" doesn't make dg.build raise -- it degrades to an all-zero
    digest (facts["entrants"] == 0). Before the fix-round-2 guard, run() still
    reached ag.evaluate() with that empty digest (and only survived because
    the autouse fake agent isn't callable); that's a wasted model call in
    production. The digest-level guard in run() must skip before evaluate is
    ever invoked and before the cache is touched -- that's the assertion that
    proves we don't spend."""
    con = digest_con()
    _bucket()

    evaluate_calls = []
    put_calls = []
    monkeypatch.setattr(cli.ag, "evaluate", lambda *a, **k: evaluate_calls.append(1))
    monkeypatch.setattr(cli.cache, "put", lambda *a, **k: put_calls.append(1))

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, "NOPE")], **KWARGS)

    assert not evaluate_calls
    assert not put_calls
    assert stats == {"total": 1, "hit": 0, "generated": 0, "skipped": 1, "written": 0}
    assert not (tmp_path / CATEGORY).exists()


def test_evaluation_error_skips_and_does_not_clobber_a_good_prior_cache_entry(
        tmp_path, monkeypatch):
    con = digest_con()
    digest, key = _key(con, CATEGORY, MEET_A)
    client = _bucket()
    good = _cached_payload(CATEGORY, MEET_A, "den gode tidligere tekst")
    cache.put(client, CATEGORY, MEET_A, key, good)

    def _boom(*a, **k):
        raise ag.EvaluationError("numbers not in digest")
    monkeypatch.setattr(cli.ag, "evaluate", _boom)

    # force=True so the cache-hit branch is bypassed and evaluate is actually
    # attempted; this is what a revoked/bad prompt version regeneration looks
    # like in production.
    stats = cli.run(con, tmp_path, meets=[(CATEGORY, MEET_A)], force=True, **KWARGS)

    assert stats == {"total": 1, "hit": 0, "generated": 0, "skipped": 1, "written": 0}
    assert cache.get(client, CATEGORY, MEET_A, key) == good
    assert not (tmp_path / CATEGORY / MEET_A / "evaluation.json").exists()


def test_a_cache_get_error_skips_that_meet_and_the_batch_continues(tmp_path, monkeypatch):
    """The Critical: a transient S3 error (e.g. SlowDown) on one meet must not
    abort meets after it. Regression test for the widened per-meet catch-all
    in run() — see the fix-round report for the failing run against the
    pre-fix code."""
    con = digest_con()
    _, key_a = _key(con, CATEGORY, MEET_A)
    digest_b, key_b = _key(con, CATEGORY, MEET_B)
    _bucket()

    real_get = cache.get

    def _flaky_get(client, category, meet_id, key):
        if meet_id == MEET_A:
            raise ClientError({"Error": {"Code": "SlowDown", "Message": "throttled"}},
                              "GetObject")
        return real_get(client, category, meet_id, key)
    monkeypatch.setattr(cli.cache, "get", _flaky_get)

    calls = []
    monkeypatch.setattr(cli.ag, "evaluate",
                        lambda d, **k: calls.append(d) or _valid_sections(d))

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, MEET_A), (CATEGORY, MEET_B)], **KWARGS)

    assert stats["total"] == 2
    assert stats["skipped"] == 1                 # MEET_A: the SlowDown
    assert stats["generated"] == 1               # MEET_B: reached and generated
    assert stats["written"] == 1
    assert len(calls) == 1 and calls[0] == digest_b       # only MEET_B's evaluate ran
    assert not (tmp_path / CATEGORY / MEET_A).exists()
    assert (tmp_path / CATEGORY / MEET_B / "evaluation.json").exists()


@pytest.mark.parametrize("prime_cache", [True, False], ids=["hit", "miss"])
def test_dry_run_never_calls_evaluate_or_put(tmp_path, monkeypatch, prime_cache):
    con = digest_con()
    digest, key = _key(con, CATEGORY, MEET_A)
    client = _bucket()
    if prime_cache:
        cache.put(client, CATEGORY, MEET_A, key, _cached_payload(CATEGORY, MEET_A))

    evaluate_calls = []
    put_calls = []
    monkeypatch.setattr(cli.ag, "evaluate", lambda *a, **k: evaluate_calls.append(1))
    monkeypatch.setattr(cli.cache, "put", lambda *a, **k: put_calls.append(1))

    stats = cli.run(con, tmp_path, meets=[(CATEGORY, MEET_A)], dry_run=True, **KWARGS)

    assert not evaluate_calls
    assert not put_calls
    if prime_cache:
        assert stats == {"total": 1, "hit": 1, "generated": 0, "skipped": 0, "written": 1}
        assert (tmp_path / CATEGORY / MEET_A / "evaluation.json").exists()
    else:
        assert stats == {"total": 1, "hit": 0, "generated": 0, "skipped": 1, "written": 0}
        assert not (tmp_path / CATEGORY).exists()


def test_main_exits_nonzero_when_meets_were_found_but_nothing_was_written(
        tmp_path, monkeypatch):
    con = digest_con()
    _bucket()
    monkeypatch.setattr(cli, "connect", lambda: con)
    monkeypatch.setattr(cli.ag, "evaluate",
                        lambda *a, **k: (_ for _ in ()).throw(ag.EvaluationError("boom")))
    monkeypatch.setenv("EVAL_GUARDRAIL_ID", "gr-1")
    monkeypatch.setenv("EVAL_GUARDRAIL_VERSION", "3")

    rc = cli.main(["--out", str(tmp_path), "--model", MODEL_ID])

    assert rc == 1


def test_main_exits_zero_when_dry_run_finds_nothing_to_generate(tmp_path, monkeypatch):
    """--dry-run is exempt: a zero-written dry run is its normal, successful
    report (it never writes by design), not the systemic-failure case the
    exit-code guard exists for."""
    con = digest_con()
    _bucket()
    monkeypatch.setattr(cli, "connect", lambda: con)

    rc = cli.main(["--out", str(tmp_path), "--model", MODEL_ID, "--dry-run"])

    assert rc == 0


def test_parse_meets_strips_whitespace_around_the_slash():
    assert cli._parse_meets(" DM-L / 12486 , DO/45 ") == [("DM-L", "12486"), ("DO", "45")]


def test_parse_meets_rejects_a_malformed_entry():
    with pytest.raises(SystemExit):
        cli._parse_meets("DM-L-12486")


def test_main_rejects_an_explicitly_empty_meets_flag(tmp_path):
    # --dry-run so the guardrail-env guard doesn't fire first; the empty
    # --meets check must still happen before any DuckDB/S3 call.
    with pytest.raises(SystemExit, match="empty"):
        cli.main(["--out", str(tmp_path), "--model", MODEL_ID, "--dry-run", "--meets", ""])
