---
name: wa-base-times
description: Add a new World Aquatics points base-times edition (SCM each September, LCM each January) and re-score the affected meets. Use when the user has a new WA base-times PDF/markdown, mentions new WA/FINA base times or points tables, or a curate email says "WARNING: no base times".
---

# Add a World Aquatics base-times edition

`points` are scored against `reference/point_base_times.jsonl`, keyed by Danish
season + course. A meet curated before its season's edition exists gets
`points = NULL` on every result. The runbook is the "New World Aquatics base
times" section of `docs/ingestion.md`; this skill is that runbook with the
checks wired in. Work on a branch; the upload and re-curate come after merge.

## 1. Map the edition to a season
| WA edition | Valid | Danish season |
| --- | --- | --- |
| SCM *Y* | 1 Sep *Y* – 31 Aug *Y+1* | *Y+1* |
| LCM *Y* | 1 Jan *Y* – 31 Dec *Y* | *Y* |

Read the `Validity period:` lines in the markdown. Each WA document normally
holds both courses; one half repeats an edition already in `BLOCKS` (same
validity period). Add only the new half.

## 2. Source files
The user supplies them (WA's site and PDF layout are not stable enough to
fetch). Expect `st-scrape/wa-points/pdf/<name>.pdf` and
`st-scrape/wa-points/<name>.md`, named
`Points-Base-times-SCM-and-LCM-<YYYY>_<MM>.<YYYY>`. If only the PDF exists,
convert it to markdown and keep it next to the others.

## 3. Generator block
In `st-scrape/gen_base_times.py`, copy the previous `BLOCKS` entry for the same
course and set `wa_label`, `course`, `season`, `validity_start/end`, plus a
source comment. Change only the times that moved (new world records). Rows are
`(dist, stroke, men_time, men_sec, women_time, women_sec)`; relays prefix
`relay_count`; mixed rows have one time.

## 4. Verify (both must pass)
```bash
cd st-scrape
.venv/bin/python gen_base_times.py                       # time string vs seconds
.venv/bin/python -m pytest -q tests/test_base_times_source.py   # BLOCKS vs every wa-points/*.md
AWS_PROFILE=swimtrends aws s3 cp s3://swimtrends-meet-data/reference/point_base_times.jsonl - \
  | diff - db/point_base_times.jsonl | grep -c '^>'      # 48 (SCM) or 42 (LCM), and no '<' lines
```
If the source test flags a row, check the **PDF**, not just the markdown: the
conversion has typos (one-decimal times, `4 :25.87`, shifted relay labels), and
WA's own PDFs occasionally disagree between the time and seconds columns. The
generator stores the seconds column.

## 5. PR
Full suite (`.venv/bin/python -m pytest -q`), branch, `gh pr create`,
`gh pr checks --watch`, `gh pr merge --squash --delete-branch`.

## 6. Upload, re-score, publish
```bash
cd st-scrape && export AWS_PROFILE=swimtrends
aws s3 cp db/point_base_times.jsonl s3://swimtrends-meet-data/reference/point_base_times.jsonl
.venv/bin/python -m ingestion.cli curate --unscored --season <S> --course <C>
```
The bucket is versioned, so the upload is recoverable. Use
`--season/--course` without `--unscored` when *changing* an existing edition:
those meets are scored, just wrongly. `curate` prints what it launched and
needs no env vars. Each task rewrites `curated/obt_result/season=<S>/course=<C>/meet=<id>.parquet`;
confirm with
`ingestion.cli query --sql "select meet_id, count(points) from cur_obt where season=<S> and course='<C>' group by 1"`.

Then `make web-refresh` from the repo root (~50 min, silent until the end;
run it in the background). The AI reports for re-scored meets regenerate in
the same run. Confirm on `https://swimtrends.dk/data/<CAT>/<meet>/meet.json`
(`elite_median_points` is non-null).
