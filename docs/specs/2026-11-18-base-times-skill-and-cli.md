# Base-times skill, source cross-check, and zero-config CLI

## Problem
- Adding a WA base-times edition is a twice-yearly, judgement-heavy job; the
  runbook in `docs/ingestion.md` exists but nothing enforces its "check against
  the markdown" step. Prototyping that check found a live transcription error:
  `SCM 2022` men's 100 Fly is `54.69` (the women's time) instead of WA's
  `47.78`, inflating season-2023 SCM men's 100 Fly points by ~50 %.
- Finding the meets to re-curate needs a hand-written SQL query.
- Every operational CLI command needs `REGISTRY_TABLE` + `DISPATCHER_FUNCTION`
  (and `CURATOR_FUNCTION` for curate) exported, even when unused; the Lambda
  names carry random CDK suffixes.

## Change
1. **Cross-check test** `st-scrape/tests/test_base_times_source.py`: parses
   every `wa-points/*.md` section (keyed by its validity period) and asserts
   each `BLOCKS` row's seconds match at least one document covering that
   period. Tolerates the known conversion noise (one-decimal times, `4 :25.87`,
   `4x50` without `m`, split rows, rows without a seconds column).
2. **Data fix**: `SCM 2022` men's 100 Fly → `47.78`. Then upload
   `point_base_times.jsonl`, re-curate season-2023 SCM meets, `make web-refresh`.
3. **CLI `curate` filters**: `--season S`, `--course C`, `--unscored` (meets
   whose results have no `points`), resolved against the curated zone and
   combinable; mutually exclusive with `meet_id`.
4. **Zero-config CLI**: table names default to their fixed CDK names
   (`swimtrends-meet-registry`, `swimtrends-class-overrides`); the dispatcher
   and curate-trigger Lambda names are looked up from CloudFormation on first
   use. Env vars still override.
5. **Project skill** `.claude/skills/wa-base-times/SKILL.md` walking the
   runbook end to end.
6. **Docs**: `docs/ingestion.md` env table + runbook steps updated.

## Affected paths
- `st-scrape/gen_base_times.py` (one row), `st-scrape/ingestion/cli.py`
- `st-scrape/tests/test_base_times_source.py` (new), `st-scrape/tests/test_cli_curate.py`
- `.claude/skills/wa-base-times/SKILL.md` (new), `docs/ingestion.md`
- Data: `reference/point_base_times.jsonl`; curated Parquet for season-2023
  SCM meets; web JSON for those meets (points, digests → AI reports regenerate).
- No CDK resources change.
