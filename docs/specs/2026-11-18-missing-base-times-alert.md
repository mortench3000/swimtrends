# Missing base-times alert + WA base-times runbook

## Problem
World Aquatics publishes two base-time editions a year (SCM in September, LCM
in January). A meet curated before its season's edition is in
`reference/point_base_times.jsonl` gets `points = NULL` on every result, and
the curate SNS email still says **SUCCEEDED**. DMJ-K 12489 (Oct 2026) went
live with no points that way.

## Change
1. **Alert.** `curate/run.py:run_curate_task` checks whether the base-times
   table has any row for the meet's `(season, course)`. If not, the SNS
   notification it already sends uses the subject
   `Swimtrends curate WARNING: no base times` and a body naming the season,
   course and the runbook. The meet is still written (`points_fixed` is still
   valid); exit code is unchanged.
2. **Runbook.** A "New World Aquatics base times" section in
   `docs/ingestion.md`: edition → season mapping, add/regenerate/verify,
   upload, re-curate affected meets, `make web-refresh`.

## Affected paths
- `st-scrape/curate/run.py` (notification subject/body only)
- `st-scrape/tests/test_curate_run.py`
- `docs/ingestion.md`
- No web pages, views, JSON, or CDK resources change. The curate image picks
  the change up on the next manual `SwimtrendsCuratedStack` deploy.

## Not done
No automatic fetch of WA documents and no CI check: two editions a year
doesn't justify it, and the alert covers the failure mode.
