"""Fill the evaluation cache and emit evaluation.json per meet.

Run after webbuild and before the S3 sync (see the Makefile). Cheap on a cache
hit: the digest queries are aggregates, and no model is called unless the key
is missing. Any failure skips that meet — the page then renders exactly as it
does today.

Config comes from the environment:
  EVAL_MODEL_ID           Bedrock model id (or --model)
  EVAL_GUARDRAIL_ID       Bedrock guardrail id
  EVAL_GUARDRAIL_VERSION  numbered guardrail version (never DRAFT)
"""
import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

import boto3

from analytics.loader import connect
from evaluation import agent as ag
from evaluation import cache
from webbuild import digest as dg
from webbuild.shape import write_json

log = logging.getLogger("evaluation")


def _all_meets(con) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT DISTINCT category, meet_id FROM results_by_category "
        "WHERE class = 'open' ORDER BY category, meet_id").fetchall()
    return [(c, m) for c, m in rows]


def _parse_meets(spec: str) -> list[tuple[str, str]]:
    out = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "/" not in item:
            raise SystemExit(f"--meets entries must be CATEGORY/MEET_ID, got {item!r}")
        cat, mid = item.split("/", 1)
        out.append((cat.strip(), mid.strip()))
    return out


def _drop_stale(out: Path, category: str, meet_id: str, *, dry_run: bool) -> None:
    """Remove this meet's evaluation.json when the meet is skipped.

    webbuild does not clear its output directory and nothing else deletes from
    it, so on a reused web/public/data a skip would otherwise keep the file an
    *earlier* run wrote -- and the `aws s3 sync --delete` that follows
    republishes it, pairing text from an older digest (possibly an older
    prompt) with a page rebuilt from current data. Dropping it is what
    docs/analytics.md already documents: a meet that fails gets no
    evaluation.json, so the sync removes its section from the live site. A
    transient failure therefore costs the section until the next run, which is
    the cheap direction of the trade.

    A --dry-run deletes nothing, deliberately: it is a reporting mode, the
    `--delete` sync never follows it, and a dry run that pruned files would make
    the next real run's report differ from the one just read.
    """
    if dry_run:
        return
    (out / category / meet_id / "evaluation.json").unlink(missing_ok=True)


def _spent(agent) -> tuple[int, int]:
    """(input, output) tokens the agent has spent, cumulative over the batch.

    Read once at the end rather than per meet: strands accumulates across every
    invocation of the same agent, and `evaluate` clears the conversation but not
    the counters. Defensive because the metrics shape varies by SDK version and
    because a --dry-run never builds an agent at all — an unreported number is a
    worse outcome than an approximate one, but neither is worth failing a batch
    that already produced its reports.
    """
    try:
        usage = agent.event_loop_metrics.accumulated_usage
        return int(usage.get("inputTokens", 0)), int(usage.get("outputTokens", 0))
    except Exception:
        return 0, 0


def run(con, out: Path, *, model_id: str, guardrail_id: str, guardrail_version: str,
        meets=None, force: bool = False, dry_run: bool = False) -> dict:
    s3 = boto3.client("s3", region_name=ag.REGION)
    agent = guard = None
    if not dry_run:
        agent = ag.build_agent(model_id=model_id, guardrail_id=guardrail_id,
                               guardrail_version=guardrail_version)
        # The guardrail applied to the generated text (the inline one on the
        # Converse call only reaches the input). Same id and numbered version.
        guard = ag.OutputGuard(
            guardrail_id=guardrail_id, guardrail_version=guardrail_version,
            client=boto3.client("bedrock-runtime", region_name=ag.REGION))
    # `meets is None` means "no filter" -- an empty list is a filter that
    # selected nothing, and must not silently widen to the whole registry.
    meet_list = _all_meets(con) if meets is None else meets
    stats = {"total": len(meet_list), "hit": 0, "generated": 0, "skipped": 0,
             "written": 0, "input_tokens": 0, "output_tokens": 0}

    for category, meet_id in meet_list:
        # One outer catch-all per meet: cache.get/put and write_json are not
        # individually guarded below, so a transient S3 error (throttling, a
        # permissions blip, a corrupted cached body) must not abort the whole
        # batch — it should cost this meet only, same as a digest or evaluate
        # failure. The two inner try/excepts keep their specific log messages;
        # this one is the backstop for everything else.
        try:
            try:
                digest = dg.build(con, category, meet_id)
            except Exception:
                log.exception("digest failed for %s/%s", category, meet_id)
                stats["skipped"] += 1
                _drop_stale(out, category, meet_id, dry_run=dry_run)
                continue

            # A bogus or not-yet-curated meet id doesn't make dg.build raise
            # -- it degrades to an all-zero/None digest. Don't spend a model
            # call (or a cache entry) writing a report about zero swimmers.
            if not digest["facts"]["entrants"]:
                log.warning("empty digest for %s/%s (no scored swims) -- skipping",
                            category, meet_id)
                stats["skipped"] += 1
                _drop_stale(out, category, meet_id, dry_run=dry_run)
                continue

            key = cache.cache_key(digest, prompt_version=ag.PROMPT_VERSION,
                                  schema_version=ag.SCHEMA_VERSION, model_id=model_id,
                                  guardrail_id=guardrail_id,
                                  guardrail_version=guardrail_version,
                                  max_tokens=ag.MAX_TOKENS)
            payload = None if force else cache.get(s3, category, meet_id, key)
            if payload is not None:
                stats["hit"] += 1
            elif dry_run:
                # No _drop_stale: a dry run deletes nothing, on purpose (see there).
                log.info("would generate %s/%s", category, meet_id)
                stats["skipped"] += 1
                continue
            else:
                try:
                    sections = ag.evaluate(digest, agent=agent, guard=guard)
                except ag.EvaluationError as e:
                    # A refusal is the policy working, not the code breaking:
                    # the message already names the offending section or number.
                    # One line, no traceback -- six frames per refused meet read
                    # as a crash and bury the reason across a 40-meet batch.
                    log.warning("refused %s/%s: %s", category, meet_id, e)
                    stats["skipped"] += 1
                    _drop_stale(out, category, meet_id, dry_run=dry_run)
                    continue
                except Exception:
                    log.exception("evaluation failed for %s/%s", category, meet_id)
                    stats["skipped"] += 1
                    _drop_stale(out, category, meet_id, dry_run=dry_run)
                    continue
                payload = {
                    "category": category, "meet_id": meet_id,
                    "prompt_version": ag.PROMPT_VERSION,
                    "schema_version": ag.SCHEMA_VERSION,
                    "model_id": model_id, "model_label": ag.model_label(model_id),
                    "generated_at": dt.date.today().isoformat(),
                    "sections": sections,
                }
                cache.put(s3, category, meet_id, key, payload)
                stats["generated"] += 1

            write_json(out / category / meet_id / "evaluation.json", payload)
            stats["written"] += 1
        except Exception:
            log.exception("evaluation pipeline failed for %s/%s", category, meet_id)
            stats["skipped"] += 1
            _drop_stale(out, category, meet_id, dry_run=dry_run)

    stats["input_tokens"], stats["output_tokens"] = _spent(agent)
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate cached AI meet evaluations and emit evaluation.json.")
    ap.add_argument("--out", required=True, type=Path, help="web data output directory")
    ap.add_argument("--meets", help="comma-separated CATEGORY/MEET_ID (default: all)")
    ap.add_argument("--model", default=os.environ.get("EVAL_MODEL_ID"),
                    help="Bedrock model id (default: $EVAL_MODEL_ID)")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even on a cache hit (revokes the cached text)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report hits/misses, never call the model")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.model:
        raise SystemExit("no model: pass --model or set EVAL_MODEL_ID")
    guardrail_id = os.environ.get("EVAL_GUARDRAIL_ID")
    guardrail_version = os.environ.get("EVAL_GUARDRAIL_VERSION")
    # Required for --dry-run too, even though it calls no model: the guardrail's
    # identity is part of the cache key, so without it a dry run computes a key
    # no real run ever stores under and reports every meet as a miss. Reporting
    # hits and misses is the mode's only purpose, so two exports are cheaper
    # than a second, mode-conditional key formula.
    if not (guardrail_id and guardrail_version):
        raise SystemExit(
            "set EVAL_GUARDRAIL_ID and EVAL_GUARDRAIL_VERSION "
            "(from the SwimtrendsEvaluationStack outputs)")

    if args.meets is not None and not args.meets.strip():
        raise SystemExit(
            "--meets was given but empty (omit the flag to process all meets)")
    meets = _parse_meets(args.meets) if args.meets is not None else None
    # A filter that parsed to nothing (e.g. --meets ",") is a typo, not a
    # request for every meet: with --force that would revoke every cached text.
    if meets is not None and not meets:
        raise SystemExit(
            f"--meets {args.meets!r} selected no meets "
            "(omit the flag to process all meets)")

    stats = run(connect(), args.out, model_id=args.model,
                guardrail_id=guardrail_id, guardrail_version=guardrail_version,
                meets=meets, force=args.force, dry_run=args.dry_run)
    print("evaluations: " + ", ".join(f"{k}={v}" for k, v in stats.items()))

    # A systemic failure (bad model id, revoked guardrail, expired creds,
    # throttling that starts partway through) must not exit 0: web-refresh syncs
    # with --delete right after this, so every skipped meet loses its published
    # section. The guard is proportional rather than a zero-floor, because
    # throttling from meet 5 onwards gives written=5, skipped=32 — which is a
    # systemic failure wearing the shape of routine skips. A minority of skips
    # in an otherwise healthy batch still exits 0, or one stubborn meet would
    # block every refresh. A --dry-run never writes by design (it only reports
    # hits/misses), so it is exempt — its zero-written outcome is expected.
    if not args.dry_run and stats["total"] > 0 and stats["skipped"] > stats["written"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
