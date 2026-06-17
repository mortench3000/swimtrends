# Swimtrends Ingestion Platform — Design Spec

- **Date:** 2026-06-02
- **Status:** Approved (design); pending implementation plan
- **Spec:** 1 of 3 (Ingestion platform)

## Context & goal

Swimtrends scrapes Danish swimming meet results from `svømmetider.dk` and is
building a historical dataset that grows as new meets complete. The current
scraper (`st-scrape/scrape_races.py`) runs locally and writes JSONL to `db/`.

The goal of this spec is to **deploy the scraper to AWS** so it runs on an
intelligent schedule: we register a list of meets, and shortly after each meet
completes its scrape executes automatically and lands raw data in S3. The
deployment must **scale to zero** and incur **minimum cost** when idle.

### Platform decomposition (this spec is #1)

1. **Ingestion platform** *(this spec)* — containerized scraper on Fargate,
   EventBridge-driven scheduling with a meet registry + completion detection,
   raw JSONL → S3.
2. **Curated data lake** *(later)* — raw → partitioned Parquet + points, Glue
   catalog, schema contract.
3. **Analytics access** *(later)* — Athena (cloud) + Dockerized DuckDB (local)
   over the Parquet.

Each sub-project gets its own spec → plan → build cycle. They share the S3
bucket and the raw layout defined here.

### Live vs obsolete code

- **Live:** `st-scrape/` (`scrape_races.py`, `calc_points.py`, `gen_base_times.py`,
  base-times docs, `db/` as local output) and `swimtrends-app/` (CDK).
- **Obsolete / out of scope:** the old Scrapy project (`swimtrends/`), the
  Postgres setup (`pgdckr/`), and root scripts (`post-process.py`, `ag-rank.py`, …).

The artifact deployed by this platform is the `st-scrape` scraper.

## Scope

### In scope
- Containerize `st-scrape` and run it on AWS Fargate (scale-to-zero compute).
- A DynamoDB **meet registry** = the configurable list of meets + per-meet status.
- A **dispatcher Lambda** that detects due/complete meets and launches scrapes,
  triggered hourly by EventBridge and on-demand by a CLI.
- Land the scraper's three raw JSONL files per meet in S3 (raw zone only).
- A `swimtrends` operational **CLI** to register meets and trigger dispatch.
- Notifications (SNS) and basic observability.

### Out of scope (later specs)
Points calculation, base-times management, Parquet/curated zone, Glue/Athena,
DuckDB, and auto-discovery of meets from a site calendar.

## Architecture

### Components

| Component | Service | Role |
|-----------|---------|------|
| Meet registry | DynamoDB | Configurable meet list + per-meet status/audit |
| Dispatcher | Lambda (≤1 min) | Find due meets, completeness check, launch scrapes |
| Scheduler | EventBridge Scheduler | Hourly cron trigger for the dispatcher |
| Scrape task | ECS Fargate task | Containerized `st-scrape`; scrape → raw JSONL → S3 |
| Raw store | S3 (`swimtrends-meet-data`) | Raw zone, one prefix per meet |
| Image | ECR | Scraper container image |
| Alerts | SNS (email) | Scrape success/failure/deadline notifications |

### Data flow

```
                EventBridge (hourly cron)        CLI (swimtrends dispatch [--force])
                          │                                   │ (lambda invoke)
                          └───────────────┬───────────────────┘
                                          ▼
                                  Dispatcher Lambda ──reads/writes──► DynamoDB meet registry
                                          │   find meets: now >= end_date+grace, status=scheduled
                                          │   sanity check: GET meet page, races present?
                                          ▼
                                  ECS RunTask (Fargate)  — one task per due meet
                                          │
                                          ▼
                        Fargate: scrape_races.py <meet_id> <categories>
                                          │
                          ┌───────────────┴────────────────┐
                          ▼                                 ▼
               S3 raw/ (3 JSONL files)        DynamoDB status -> scraped | failed
                          │                                 │
                          └────────────► SNS notify ◄───────┘
```

### Completion detection (hybrid, lightweight)

The meet page only shows **completed** races; results appear shortly after each
race finishes. `end_date + grace` (default **6h**) is a safe trigger.

Per meet, the dispatcher computes:
- `scrape_after = end_date 23:59 (Europe/Copenhagen) + grace_hours` (default 6)
- `deadline = end_date 23:59 (Europe/Copenhagen) + deadline_hours` (default 72)

Decision per scheduled meet:
- `now < scrape_after` → skip.
- `scrape_after <= now < deadline` → **completeness check** (GET meet page,
  confirm races present via a shared `meet_has_results()` helper). Present →
  dispatch; not present → leave `scheduled`, re-check next hour.
- `now >= deadline` → dispatch anyway (fallback for postponed/odd meets; emit a
  "deadline-forced" notification).

## Data contracts

### S3 raw layout

Reuse the existing **`swimtrends-meet-data`** bucket (imported by name). One
prefix per meet, three files (exactly what the scraper emits):

```
s3://swimtrends-meet-data/
  raw/
    meet=<meet_id>/
      meet_info.jsonl
      races.jsonl
      results.jsonl
```

- Keyed by `meet_id` (natural key). Re-scraping overwrites these three objects.
- Bucket is **versioned** → prior scrapes retained automatically (free audit
  history; no timestamped paths).
- `meet=<id>` Hive-style prefix so Spec 2's transform can discover meets.
- Scrape logs go to **CloudWatch** (Fargate `awslogs` driver), not S3.

#### Raw structure rationale

The three-file split coincides with the previous system's three Postgres tables
(`meet`, `race`, `race_result`), but it is retained here on its own merits, not
by inheritance:

- **Entities at natural cardinality.** `meet` (1/meet), `race` (N/meet),
  `result` (M/race) are three genuinely different schemas and cardinalities. A
  raw landing zone should faithfully mirror the source at minimal transformation;
  denormalizing meet/race attributes onto every result row is an *analytics*
  concern owned by **Spec 2's curated Parquet** ("one big table"), not raw. Both
  DuckDB and Athena join the three raw tables trivially.
- **`splits` stay nested inside `results`** (`results[].splits[]`) in the raw
  zone. Flattening them into a separate lap-level entity needs a stable
  per-result surrogate key to foreign-key against — awkward to assign at scrape
  time, especially for **relays where `Swimmer_id` is `null`** (so
  `race_id + swimmer_id` is not a unique result key). Generating that surrogate
  key and exploding splits into a flat `fact_split` table is deferred to Spec 2's
  curated transform.
- **No points in raw.** The deployed Fargate task runs `scrape_races.py` only
  (not `calc_points.py`), so raw `results.jsonl` contains the scraper-native
  fields plus nested `splits` and **no `points`/`points_fixed`** — points and
  base-times management belong entirely to Spec 2. (Local `db/` files show points
  only because `calc_points` was run locally during development.)

The structure has already evolved beyond the old tables (nested `splits`, list
`category`, `relay_count`/`class` on races), so it is not a frozen artifact.

### DynamoDB meet registry — `swimtrends-meet-registry`

Partition key **`meet_id`** (String). User supplies the first three fields; the
platform manages the rest.

| Attribute | Type | Set by | Notes |
|-----------|------|--------|-------|
| `meet_id` | S | user | e.g. `"10970"` |
| `category` | L<S> | user | e.g. `["DM-L","DMJ-L"]` → scraper args |
| `end_date` | S | user | `YYYY-MM-DD`, the meet's last day |
| `status` | S | platform | `scheduled` → `scraping` → `scraped` \| `failed` |
| `grace_hours` | N | optional | default **6** |
| `deadline_hours` | N | optional | default **72** |
| `attempts` | N | platform | retry counter |
| `last_scraped_at` | S | platform | ISO timestamp |
| `last_error` | S | platform | on failure |
| `meet_name` | S | platform | filled from scrape, for readability |

- **Finding due meets:** `Scan` for `status = scheduled` (a handful of rows; a
  `status` GSI is a future optimization).
- **Idempotency:** dispatch performs a conditional update `scheduled → scraping`,
  preventing double-launch across overlapping (hourly + manual) invocations.
- **Reference timezone** (Europe/Copenhagen), `grace_hours`, `deadline_hours`,
  and `max_attempts` (default 3) are configurable; defaults live in the Lambda.

## Runtime components

### Dispatcher Lambda (Python, <1 min)

Parameterized by its invocation event, so one function serves both triggers:

- **EventBridge (hourly)** → empty event → full cycle over all `scheduled` meets
  with the time + completeness gates above.
- **CLI invoke** → event `{ "meet_ids": [...], "force": true|false }`:
  - `meet_ids` → restrict the cycle to those meets.
  - `force: true` → bypass the time + completeness gates and dispatch now (still
    subject to the `scheduled → scraping` conditional update).

Dispatch = conditional status update, then `ecs:RunTask` (Fargate) with
container overrides `MEET_ID` and `CATEGORIES`.

IAM: `dynamodb:Scan/UpdateItem`, `ecs:RunTask`, `iam:PassRole`. Not in a VPC, so
it has outbound internet for the completeness check.

### Fargate scrape task

- ECR image: `python-slim` + `requests`/`bs4` + the `st-scrape` module + a thin
  **entrypoint wrapper**.
- Wrapper: run `scrape_races.py <meet_id> <categories>` → upload the three JSONL
  from `db/` to `s3://…/raw/meet=<id>/` → update registry to `scraped`
  (+ `meet_name`, `last_scraped_at`) or `failed` (+ `last_error`) → publish SNS.
- **Networking (cost-critical):** task runs in the **default VPC's public subnet
  with a public IP** — **no NAT gateway** (a NAT would be ~$32/mo idle, breaking
  scale-to-zero). Egress-only security group.
- Size: 0.5 vCPU / 1 GB (network-bound, low memory). Logs → CloudWatch.
- IAM task role: `s3:PutObject` (raw prefix), `dynamodb:UpdateItem`, `sns:Publish`.

### Operational CLI (`swimtrends`)

- `swimtrends register <meet_id> --categories DM-L,DMJ-L --end-date 2024-07-11`
  — `PutItem` into the registry (`status=scheduled`). `--rescrape` resets an
  existing meet's status to `scheduled`.
- `swimtrends dispatch` — invoke the dispatcher now (normal due-check cycle).
- `swimtrends dispatch <meet_id> [--force]` — dispatch a specific meet now;
  `--force` skips the grace/completeness gates.
- `swimtrends dispatch --all --force` — backfill: dispatch every `scheduled`
  meet immediately (used to load historical meets without waiting).

CLI needs `lambda:InvokeFunction` (dispatcher) and `dynamodb:PutItem/UpdateItem`.

### Historical backfill

To load historical data: `register` the old meets (their `end_date` is in the
past) and `dispatch --all --force` — they scrape immediately, no waiting and no
completeness polling.

## Observability & failure handling

- **SNS topic** (email subscription) on: scrape **succeeded** (`meet_id`,
  #results, #races), **failed** (`meet_id`, error), **deadline-forced** scrape.
- Failure → `status=failed` + alert; the dispatcher re-picks `failed` meets until
  `max_attempts` (default 3), then stops and alerts (manual `--rescrape` to reset).
- CloudWatch alarm on dispatcher errors. Lambda + Fargate logs in CloudWatch.

## IaC structure (CDK)

- **New `SwimtrendsIngestionStack`** for all ingestion resources: DynamoDB
  registry, ECR repo + image (`ecs.ContainerImage.from_asset` building
  `st-scrape/Dockerfile`), ECS cluster + Fargate task definition/role, dispatcher
  Lambda + role, EventBridge schedule, SNS topic, security group.
- **Reuse** the existing `swimtrends-meet-data` bucket (import by name).
- Leave the existing stack's Glue/Athena resources untouched (Spec 2/3 will
  revisit; possibly remove as premature).

## Cost / scale-to-zero

- Fargate runs only during a scrape (per-second billing, no cluster, no NAT).
- Lambda + EventBridge + DynamoDB on-demand + SNS are effectively free at this
  volume.
- Idle cost ≈ S3 storage of the raw JSONL only.

## Assumptions

- Scrapes run 15–25+ min (past Lambda's 15-min limit) → Fargate is required for
  the scrape itself; the dispatcher's work is trivial and fits in Lambda.
- The meet page reliably shows all completed races within `end_date + 6h`.
- Meet IDs and categories are known/configured manually (no auto-discovery).
- The scraper code (`st-scrape`) is the single source of truth, shared by the
  Fargate task and the dispatcher's completeness helper.
