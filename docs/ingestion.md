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
Different commands need different wiring (all use AWS creds for the region):

| Command | Needs |
| --- | --- |
| `register`, `pending` | `REGISTRY_TABLE` (DynamoDB, direct) |
| `dispatch` | `REGISTRY_TABLE`, `DISPATCHER_FUNCTION` (Lambda) |
| `curate` | `CURATOR_FUNCTION` (Lambda) |
| `class` | `OVERRIDES_TABLE` (DynamoDB) |

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
