# CLAUDE.md — Swimtrends

Guidance for AI agents (and humans) working in this repo. Read this first.

## What this is
Analytics of Danish competitive swimming. Meet results are scraped from
svømmetider.dk into a raw zone on S3, transformed into a curated Parquet zone
(World Aquatics points + open/para/junior classification), catalogued in Glue,
and queried locally with DuckDB. Ingestion is automated on AWS (DynamoDB
registry + dispatcher Lambda + Fargate scraper, hourly EventBridge cycle).

## Repository layout
| Path | What |
| --- | --- |
| `st-scrape/` | **The application.** `scrape_races.py` (scraper), `curate/` (raw→Parquet transform), `analytics/` (DuckDB views + loader), `ingestion/` (registry, dispatcher, `cli.py`), `gen_base_times.py`, `tests/`, `notebooks/`. |
| `swimtrends-app/` | AWS **CDK infrastructure** (Python): S3, DynamoDB, dispatcher/curate Lambdas, Fargate task defs, SNS, Glue. Stacks in `swimtrends_app/*_stack.py`; tests in `tests/unit`. |
| `docs/` | [`analytics.md`](docs/analytics.md) (querying), [`ingestion.md`](docs/ingestion.md) (operational CLI), design specs/plans under `superpowers/`. |
| `legacy/` | Deprecated original Scrapy → PostgreSQL pipeline + Docker. Not maintained. See [`legacy/README.md`](legacy/README.md). Don't build on it. |

## Data flow
```
scrape_races.py <meet_id> <categories…>
  └─ db/<id>_{meet_info,races,results}.jsonl
       └─ upload to s3://swimtrends-meet-data/raw/meet=<id>/  (results.jsonl LAST)
            └─ CurateTrigger Lambda (S3 ObjectCreated on results.jsonl)
                 └─ curate Fargate task  →  curated/{dim_meet,dim_race,fact_result,
                        fact_split,obt_result}/season=<Y>/course=<C>/meet=<id>.parquet
                      └─ Glue catalog + local DuckDB (analytics/loader.py)
```
- Bucket `swimtrends-meet-data` is **versioned** (overwrites keep prior versions).
- Registry table `swimtrends-meet-registry`. Base times at `reference/point_base_times.jsonl`.
- The curate trigger URL-decodes the S3 key (`meet%3D…`) — keep that if you touch it.

## Environment & setup
Two independent virtualenvs:
- **App/tests:** `st-scrape/.venv` ← `requirements.txt` (+ `requirements-dev.txt`, `requirements-notebook.txt`). Python 3.12.
- **CDK:** `swimtrends-app/.venv` ← its `requirements.txt`.

AWS: profile **`swimtrends`**, region **`eu-west-1`** (account is selected by the
profile — do not hardcode the account id in new files; this is a public repo).
Scraping and AWS commands need network + credentials.

## Common commands (run from the dir shown)
```bash
# Tests — always run before claiming done
cd st-scrape       && .venv/bin/python -m pytest -q        # app + analytics + ingestion (134)
cd swimtrends-app  && .venv/bin/python -m pytest tests/unit # CDK assertions

# Scrape one meet (writes db/<id>_*.jsonl locally)
cd st-scrape && .venv/bin/python scrape_races.py 12486 DM-L DMJ-L

# Regenerate the points base-times table (reads legacy CSV + wa-points/*.md)
cd st-scrape && .venv/bin/python gen_base_times.py   # -> db/point_base_times.jsonl

# CLI — operational (need REGISTRY_TABLE etc.; see docs/ingestion.md)
cd st-scrape && .venv/bin/python -m ingestion.cli register|dispatch|curate|class|pending …

# CLI — read-only analytics (need only AWS creds for S3)
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli \
    query [--sql "…"] | meets [--category X] [--season Y] [--asc] | categories | summary
```

## Deploying the CDK stacks (there are real gotchas)
```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22        # node 22, NOT the default
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk deploy SwimtrendsIngestionStack \
  --app ".venv/bin/python3 app.py" \
  -c alert_email=<your-address> \
  --require-approval never
```
- **Use node 22's `cdk`** (or `npx aws-cdk@2.1125.0`). The default nvm node has a
  stale global `cdk` incompatible with the venv's `aws-cdk-lib`.
- **`--app ".venv/bin/python3 app.py"`** — only the venv python has the CDK libs.
- **ALWAYS pass `-c alert_email=<address>`.** It is read from CDK context, not
  stored anywhere. Omitting it deletes the existing SNS email subscription, so
  alerts silently stop (applies to both `SwimtrendsIngestionStack` and
  `SwimtrendsCuratedStack`). A new SNS confirmation email is sent each time.
- **Docker must be running** (CDK builds the scraper image + Lambda bundle assets).

## Domain conventions (curated column values)
- **stroke** is Danish: `Fri` free, `Ryg` back, `Bryst` breast, `Fly`,
  `IM` individual medley, `HM` team medley. (Mapped to WA `FREE/BACK/BREAST/FLY/MEDLEY`.)
- **course**: `LCM` (50 m) / `SCM` (25 m). **gender**: `M`/`F`/`X` (mixed relay).
- **season** = Danish season year. LCM meets → the year held; **SCM meets (held
  in December) map to the *next* year** (a Dec-2025 meet is season 2026).
- **points** = `trunc(1000 · (basetime/swimtime)³)`. `points` uses the meet's own
  season base times; `points_fixed` uses a frozen reference season (2026) for
  cross-era comparison. Para / DQ / timeless swims are not scored.
- **phase** (from race type): `Heats→heats`, `Final→final`, else `timed_final`.
- **para**: a `Timed final` ('Direkte finale') that duplicates an event also run
  as Heats/Final in the same meet → `class='para'`; else `open`. Override with
  `swimtrends class set`.
- **junior**: competition-season age 16-18 (`is_junior` on the `results` view).
  The junior title is decided from the *qualifying* swim (heats, or the timed
  final for 800/1500) — see `junior_championship`, never the senior final.
- **DSQ**: renders as a **7-column** row (rank cell `-`, `DSQ` in the time cell).
  The parser accepts `len(cells) >= 6` and maps a non-numeric rank to `-1`;
  curate excludes `rank == -1` from scoring. Don't reintroduce a `== 6` check.

## Development conventions
- **TDD.** Write the failing test first, watch it fail, then implement. App tests
  live in `st-scrape/tests/`; analytics-view tests build an in-memory DuckDB via
  `tests/analytics_fixtures.build_curated` + `analytics.loader.create_views` (no
  S3). CDK tests are assertion tests in `swimtrends-app/tests/unit`.
- **Analytics views** are plain SQL in `st-scrape/analytics/views/*.sql`, loaded
  in filename order; they bind to `cur_obt`/`cur_dim_meet`/`cur_fact_split`.
  Prefer a view over baking derived policy into curate (junior status, etc.).
- Match surrounding style; keep changes minimal and focused.

## Guardrails
- **Be polite to svømmetider.dk** (host `xn--svmmetider-1cb.dk`): single,
  **sequential** requests only — never parallelize scrapes. The scraper already
  paces itself (0.25 s delay, backoff on 415/429/5xx). Backfill one meet at a time.
- **Never deploy without `-c alert_email`** (see above).
- Confirm before hard-to-reverse or outward-facing actions (deploys, S3
  overwrites, force-dispatch of the whole registry).
