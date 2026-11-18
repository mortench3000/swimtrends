# Operational CLI (ingestion & curate)

The `swimtrends` CLI controls the ingestion pipeline: registering meets,
triggering scrapes/curation, managing class overrides, and inspecting the
registry. For read-only analysis of the curated data see
[analytics.md](analytics.md).

Run from `st-scrape/` (`.venv/bin/python -m ingestion.cli <cmd>` if `swimtrends`
isn't on your PATH). Commands here talk to AWS: profile `swimtrends`, region
`eu-west-1`.

## Meet lifecycle

```
register ──▶ scheduled ──(dispatch/claim)──▶ scraping ──▶ scraped
                 ▲                                │
                 └────────── register --rescrape ─┴──▶ failed
```

A scraped meet's `results.jsonl` landing in S3 triggers curation automatically
(the CurateTrigger Lambda). `scheduled` and `failed` meets are the ones the
dispatcher will (re)pick up — that's what `pending` lists.

## Environment
Only AWS creds are needed (`AWS_PROFILE=swimtrends`). Table names default to
their fixed CDK names (`swimtrends-meet-registry`, `swimtrends-class-overrides`),
and the dispatcher / curate-trigger Lambda names are looked up from the
`SwimtrendsIngestionStack` / `SwimtrendsCuratedStack` CloudFormation stacks on
first use. Exporting `REGISTRY_TABLE`, `OVERRIDES_TABLE`, `DISPATCHER_FUNCTION`
or `CURATOR_FUNCTION` overrides the default.

## Commands

### register — add or re-arm a meet
```bash
# Register a new meet (both flags required)
swimtrends register 12486 --categories DM-L,DMJ-L --end-date 2026-07-09

# Tune the scrape timing (optional)
swimtrends register 12486 --categories DM-K --end-date 2025-12-11 \
  --grace-hours 6 --deadline-hours 72

# Re-arm an already-registered meet (status->scheduled, attempts=0, error cleared)
swimtrends register 12486 --rescrape
```
- `--categories` — comma-separated championship tags (e.g. `DM-L,DMJ-L`). These
  become the meet's `category` in the curated zone, so tag consistently
  (a combined meet gets both).
- `--end-date` — the meet's last day (`YYYY-MM-DD`).
- `--grace-hours` — hours after the last day (23:59 local) before scraping
  (default 6).
- `--deadline-hours` — hours after which the meet is force-scraped even without
  confirmed results (default 72).
- `--rescrape` — re-arm an existing meet; does not need `--categories`/`--end-date`.

### dispatch — invoke the dispatcher Lambda
```bash
swimtrends dispatch                  # normal due-check cycle (scrape whatever is due)
swimtrends dispatch 12486 --force    # one meet now, skipping the grace/completeness gates
swimtrends dispatch --all --force    # backfill every scheduled meet now
```
`--all` only applies with `--force`. Forcing every meet requires `--all`
explicitly (no accidental mass-scrape).

### curate — run the curated transform
```bash
swimtrends curate 12486   # one meet
swimtrends curate --all   # full rebuild of the curated zone
swimtrends curate --season 2023 --course SCM   # every curated meet of that season/course
swimtrends curate --unscored [--season S]      # meets with no points at all
```
Normally curation is automatic on scrape; use this to re-curate after a code or
base-times change.

### class — authoritative open/para override
```bash
swimtrends class set 12486 274779 para --reason "para-only heat"
```
Overrides the heuristic open/para classification for a single race.

### pending — list meets awaiting (re)scrape
```bash
swimtrends pending
```
Lists registry meets with status `scheduled` or `failed` (the set the dispatcher
will pick up), with attempts, category, end date, and any last error:
```
meet   status     attempts  category  end_date    error
12490  scheduled  0         DM-K      2026-12-20
```

## Manual backfill (scrape + upload) outside the platform
For historical meets you can run the scraper directly and push to the raw zone;
the `results.jsonl` upload fires curation. Upload the non-trigger files first:
```bash
python scrape_races.py 5879 DM-L                      # -> db/5879_*.jsonl
B=s3://swimtrends-meet-data/raw/meet=5879
aws s3 cp db/5879_meet_info.jsonl $B/meet_info.jsonl
aws s3 cp db/5879_races.jsonl     $B/races.jsonl
aws s3 cp db/5879_results.jsonl   $B/results.jsonl    # last -> triggers curate
```
Be polite to svømmetider.dk: one meet at a time, sequential.

## New World Aquatics base times (twice a year)
`points` are scored against `reference/point_base_times.jsonl`, keyed by Danish
season + course. WA publishes two editions a year:

| WA edition | Published | Valid | Danish season |
| --- | --- | --- | --- |
| SCM *Y* (25 m) | ~September | 1 Sep *Y* – 31 Aug *Y+1* | *Y+1* |
| LCM *Y* (50 m) | ~January | 1 Jan *Y* – 31 Dec *Y* | *Y* |

Until the new edition is in the reference file, every meet of that season and
course is curated with `points = NULL` (`points_fixed` is unaffected), and the
curate email arrives as **`Swimtrends curate WARNING: no base times`** instead
of SUCCEEDED.

Each WA document normally holds both courses; one half repeats the edition
already in the generator. Add only the new half, after checking the other is
unchanged.

1. **Source.** Save the PDF to `st-scrape/wa-points/pdf/` and its markdown
   conversion to `st-scrape/wa-points/`
   (`Points-Base-times-SCM-and-LCM-<YYYY>_<MM>.<YYYY>.md`).
2. **Generator.** Add a block to `BLOCKS` in `st-scrape/gen_base_times.py`:
   `wa_label`, `course`, `season` (table above), `validity_start/end`, and the
   individual / relay / mixed rows. Copy the previous edition of the same
   course and change only the times that moved.
3. **Regenerate + verify.** `cd st-scrape && .venv/bin/python gen_base_times.py`
   (fails on any time-string/seconds mismatch). Diff against the live copy:
   ```bash
   aws s3 cp s3://swimtrends-meet-data/reference/point_base_times.jsonl - | diff - db/point_base_times.jsonl
   ```
   Expect only added rows for the new season: **48 for SCM, 42 for LCM**,
   none removed (a correction shows as changed rows instead). Then `pytest -q tests/test_base_times_source.py`, which checks
   every `BLOCKS` row against the `wa-points/*.md` documents. If it flags a
   row, check the PDF: the markdown conversion has typos.
4. **PR.** `pytest -q`, branch, PR, green CI, squash-merge.
5. **Upload** (the bucket is versioned):
   ```bash
   aws s3 cp db/point_base_times.jsonl s3://swimtrends-meet-data/reference/point_base_times.jsonl
   ```
   Every curate from here on scores the new season.
6. **Re-curate** meets curated before the upload:
   ```bash
   swimtrends curate --unscored --season <S> --course <C>
   ```
   When *correcting* an existing edition, drop `--unscored`: those meets are
   scored, just wrongly.
7. **Publish.** `make web-refresh` (~50 min), after all re-curates have
   finished. AI reports regenerate in the same run for every meet of that
   course in seasons *S*…*S+5* (each digest spans six seasons), not only the
   re-curated ones. A refused report is removed from the site until a later
   run passes; `make web-eval-deploy` re-rolls in seconds.
