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
    meet_list = meets or _all_meets(con)
    stats = {"total": len(meet_list), "hit": 0, "generated": 0, "skipped": 0, "written": 0}

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
                continue

            # A bogus or not-yet-curated meet id doesn't make dg.build raise
            # -- it degrades to an all-zero/None digest. Don't spend a model
            # call (or a cache entry) writing a report about zero swimmers.
            if not digest["facts"]["entrants"]:
                log.warning("empty digest for %s/%s (no scored swims) -- skipping",
                            category, meet_id)
                stats["skipped"] += 1
                continue

            key = cache.cache_key(digest, prompt_version=ag.PROMPT_VERSION,
                                  schema_version=ag.SCHEMA_VERSION, model_id=model_id)
            payload = None if force else cache.get(s3, category, meet_id, key)
            if payload is not None:
                stats["hit"] += 1
            elif dry_run:
                log.info("would generate %s/%s", category, meet_id)
                stats["skipped"] += 1
                continue
            else:
                try:
                    sections = ag.evaluate(digest, agent=agent, guard=guard)
                except Exception:
                    log.exception("evaluation failed for %s/%s", category, meet_id)
                    stats["skipped"] += 1
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
    if not args.dry_run and not (guardrail_id and guardrail_version):
        raise SystemExit(
            "set EVAL_GUARDRAIL_ID and EVAL_GUARDRAIL_VERSION "
            "(from the SwimtrendsEvaluationStack outputs)")

    if args.meets is not None and not args.meets.strip():
        raise SystemExit(
            "--meets was given but empty (omit the flag to process all meets)")
    meets = _parse_meets(args.meets) if args.meets is not None else None

    stats = run(connect(), args.out, model_id=args.model,
                guardrail_id=guardrail_id, guardrail_version=guardrail_version,
                meets=meets, force=args.force, dry_run=args.dry_run)
    print("evaluations: " + ", ".join(f"{k}={v}" for k, v in stats.items()))

    # A systemic failure (bad model id, revoked guardrail, expired creds) must
    # not exit 0: web-refresh syncs with --delete right after this, and a
    # silent 0/0 would delete every previously published evaluation from the
    # site. Routine per-meet skips with a nonempty result still exit 0. A
    # --dry-run never writes by design (it only reports hits/misses), so it is
    # exempt — its zero-written outcome is expected, not a failure.
    if not args.dry_run and stats["total"] > 0 and stats["written"] == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
