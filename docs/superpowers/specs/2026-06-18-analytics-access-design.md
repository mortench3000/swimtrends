# Analytics access — local DuckDB over the curated zone (Spec 3 of 3)

## Context

Spec 1 lands faithful raw JSONL in S3. Spec 2 turns it into a curated,
query-optimized Parquet data lake (World Aquatics points, authoritative class,
flattened splits, a Glue catalog, and a versioned schema contract). Spec 3 is the
**read path**: it lets a single analyst run SQL over the curated zone, plus a
starter library of analytical views that double as worked examples for learning
columnar analytics.

The split the earlier specs drew holds: **raw = faithful source mirror; curated =
derived, analytics-shaped; analytics = read-only query surface over curated.**
Spec 3 writes nothing back.

### Platform decomposition (this spec is #3)

1. **Ingestion platform** *(Spec 1, live)* — Fargate scraper, meet registry +
   dispatcher, raw JSONL → S3.
2. **Curated data lake** *(Spec 2, live)* — raw → partitioned Parquet + points +
   authoritative class + flattened splits, Glue catalog, schema contract.
3. **Analytics access** *(this spec)* — local DuckDB reading the curated Parquet
   directly from S3, with a version-controlled library of analytical views.

All three share the `swimtrends-meet-data` bucket and the curated layout from
Spec 2.

### Decisions taken during brainstorming

- **Scope = query enablement + a starter analytics layer** (not just raw query
  access, not a full dashboard product). Consumer = a single analyst (the author)
  running ad-hoc analysis while the dataset is still growing.
- **Engine = native local DuckDB reading directly from S3.** Athena and any
  Dockerized path are deferred (see Out of scope). DuckDB-local is free,
  interactive, offline-capable for analysis sessions, and always current.
- **Championship identity = the meet `category` qualifier** (`DM-L`, `DMJ-L`, …)
  for the "field evolution over time" views.
- The two gaps Spec 2 left for "Spec 3" — unloaded Glue partitions and the
  `CURATOR_FUNCTION` rebuild Lambda — are **not** needed here (the first is an
  Athena concern that DuckDB's direct S3 globbing sidesteps; the second is a
  curated-zone write operation, out of the analytics read path).

## Scope

### In scope

- An **`analytics/` package** in `st-scrape/` that, against a DuckDB connection,
  loads the S3 extensions/credentials and defines views over the curated zone.
- A **source-binding layer**: hive-partitioned `read_parquet` views over
  `s3://swimtrends-meet-data/curated/<table>/**/*.parquet` for the five curated
  tables, so new meets are queryable the instant they are curated — no partition
  loading, no crawler.
- **Base hygiene views** that apply the universal filters and derivations once.
- A **starter analytical view catalog** (below), authored as version-controlled
  SQL, covering best-times, rankings, progression, club/age aggregates, pacing,
  and field-evolution-over-time.
- A **`swimtrends query`** CLI subcommand that opens an interactive DuckDB
  session with everything pre-loaded, and a two-line bootstrap usable from a
  notebook/Python.
- **Tests** that exercise the analytical view logic against synthetic fixtures in
  an in-memory DuckDB (no S3, no AWS).

### Out of scope (deferred)

- **Athena** workgroup, results bucket, and Glue **partition projection** (a
  future "cloud SQL / multi-consumer" enablement). The curated Glue catalog from
  Spec 2 remains as-is.
- **Dashboards / BI / notebooks as a delivered product** (QuickSight, a reporting
  kit). Ad-hoc analysis only; notebooks are a usage pattern, not a deliverable.
- **Meet auto-discovery** from a site calendar — an ingestion (Spec 1) concern,
  its own future spec.
- The **`CURATOR_FUNCTION` rebuild Lambda** (a Spec 2 operational gap).
- Carrying per-result `category` into the curated zone — a possible small Spec 2
  follow-up; Spec 3 joins `dim_meet` for category instead (see Known limitations).
- Any **write-back** to S3 or DynamoDB. Spec 3 is strictly read-only.

## Architecture

```
                 ┌──────────────────────────────────────────────┐
   s3://…/curated/  (Spec 2 Parquet, hive-partitioned season/course)
                 └───────────────────────┬──────────────────────┘
                                         │ read_parquet (httpfs + aws secret)
                 ┌───────────────────────▼──────────────────────┐
 analytics/      │  Source-binding views: cur_obt, cur_dim_meet, │
 (this spec)     │  cur_dim_race, cur_fact_result, cur_fact_split│
                 ├───────────────────────────────────────────────┤
                 │  Base hygiene views: results, individual_results│
                 ├───────────────────────────────────────────────┤
                 │  Analytical catalog: personal_best, …,         │
                 │  event_standard_by_season, final_cutline_by_…  │
                 └───────────────────────┬──────────────────────┘
                          ┌──────────────┴───────────────┐
                  `swimtrends query` REPL      notebook / Python
```

Three layers, each a thin SQL file (or set of files) so a reader can understand
each independently:

### 1. Source binding (`analytics/bootstrap.sql`)

- `INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;`
- `CREATE SECRET (TYPE s3, PROVIDER credential_chain, PROFILE 'swimtrends', REGION 'eu-west-1');`
- One view per curated table, e.g.:
  ```sql
  CREATE OR REPLACE VIEW cur_obt AS
    SELECT * FROM read_parquet(
      's3://swimtrends-meet-data/curated/obt_result/**/*.parquet',
      hive_partitioning = true);
  ```
  (Likewise `cur_dim_meet`, `cur_dim_race`, `cur_fact_result`, `cur_fact_split`.)

Because the views glob S3 live, no Glue/partition step is needed and the data is
always current. `hive_partitioning` recovers `season`/`course` as columns.

### 2. Base hygiene views (`analytics/views/00_base.sql`)

- **`results`** — `cur_obt` LEFT JOIN `cur_dim_meet` for `category` (a list),
  `UNNEST` to one row per (result, category), plus derived columns:
  - `age = season - birth_year` (approximate competition-season age),
  - `is_relay = relay_count > 1`,
  - `is_dq = rank = -1`,
  - `phase` = `CASE` over `type`: `'heats'` for `Heats`, `'final'` for `Final`,
    `'timed_final'` for `Timed final` (and para's mapped `Timed final`),
  - `event` key = (`gender`, `distance`, `stroke`, `course`).
- **`individual_results`** — `results` WHERE `NOT is_relay AND swimmer_id IS NOT
  NULL AND NOT is_dq`. The default base for swimmer-level analysis.

Every analytical view builds on these two, so universal rules (DQ exclusion,
relay handling, category attribution, age/phase derivation) live in exactly one
place.

### 3. Analytical catalog (`analytics/views/*.sql`)

Each is `CREATE OR REPLACE VIEW`, grouped into files by theme. The technique each
view showcases is noted because the catalog is also a teaching surface.

**Best times & rankings**
- `personal_best` — fastest swim per `swimmer_id × distance × stroke × course`,
  with the meet/date/points where set. *(`arg_min`)*
- `season_best` — same, per `season`. *(grouping)*
- `event_leaderboard` — top-N by `points` per `event × season`, gendered.
  *(`QUALIFY ROW_NUMBER() OVER …`)*

**Progression & comparison**
- `swimmer_progression` — one swimmer's swims over time per event with delta vs
  previous. *(`LAG` window)*
- `biggest_improvers` — largest season-over-season time drop / points gain.
  *(window + diff)*
- `cross_era_best` — best performances ever ranked by `points_fixed`
  (era-normalized). *(showcases why `points_fixed` exists)*

**Aggregates: club, age, meet**
- `club_leaderboard` — per `club × season`: total points, podiums (`rank ≤ 3`),
  distinct swimmers, best single swim. *(multi-aggregate)*
- `age_group_ranking` — bucket `age` into bands, rank within band per event.
  *(`CASE` bucketing + window)*
- `meet_summary` — per meet: #results, #races, distinct swimmers, fastest /
  top-points swim. *(`arg_max`)*

**Splits (advanced)**
- `pacing` — from `cur_fact_split`: first-half vs second-half time, negative-split
  / fade flags per result. *(window over laps)*

**Field evolution over time** (championship = meet `category`)
- `event_standard_by_season` — grain (`category, season, course, gender,
  distance, stroke`): `min`, `median`, `p25`, `p75`, top-8 average, `#swims`.
  Answers "how does 200 Breast improve overall over the years." *(`quantile`,
  aggregates)*
- `final_cutline_by_season` — same grain, **heats phase only**: the time at rank
  `N` (default 8) among preliminary swims, computed by ordering heat times
  ascending (not trusting the `rank` column, whose prelim semantics vary).
  Answers "how fast to make the final at DM-L over the years." *(ranked window /
  `QUALIFY`)*

## Data flow

1. Analyst runs `swimtrends query` (or loads `bootstrap.sql` in a notebook).
2. The launcher opens a DuckDB connection, executes `bootstrap.sql` (extensions +
   S3 secret + source-binding views), then executes the `views/*.sql` in name
   order (`00_base.sql` first).
3. Analyst writes ad-hoc SQL, freely using any catalog view; every query reads the
   current curated Parquet from S3.

Nothing is materialized; there is no refresh step. Adding meets upstream (Spec 1
→ Spec 2) makes them appear in the next query automatically.

## Components & boundaries

| Unit | Purpose | Depends on |
|------|---------|-----------|
| `analytics/bootstrap.sql` | Load extensions + S3 secret + source-binding views | curated S3 layout, `swimtrends` AWS profile |
| `analytics/views/00_base.sql` | Hygiene + derivations (`results`, `individual_results`) | source-binding view names |
| `analytics/views/*.sql` | Analytical catalog | base view names only |
| `analytics/loader.py` | Assemble + execute the SQL against a `duckdb` connection; expose `bootstrap(con)` | `duckdb` package |
| `swimtrends query` (CLI) | Open an interactive session with everything loaded | `analytics.loader` |

The analytical SQL references only base-view names, never `read_parquet`/S3
directly. This is the seam that makes testing trivial: bind the base names to
fixtures instead of S3 and the catalog is unchanged.

## Testing strategy

- **In-memory DuckDB + synthetic fixtures.** A pytest fixture creates the curated
  base tables (`cur_obt`, `cur_dim_meet`, `cur_fact_split`, …) as in-memory tables
  with the exact Spec 2 schema, populated with a handful of hand-built rows, then
  runs `00_base.sql` + the catalog DDL. No S3, no AWS, no network.
- **Behavioral assertions per view**, e.g.: `personal_best` returns the minimum
  centiseconds and its meet; `final_cutline_by_season` returns the 8th-fastest
  heat time for a constructed field; `swimmer_progression` deltas match the
  hand-computed `LAG`; DQ rows (`rank = -1`) and relays are excluded from
  `individual_results`; a two-category meet contributes to both categories.
- **Loader test** — `bootstrap(con)` on an in-memory connection defines all
  expected views (assert via `duckdb_views()` / `SHOW TABLES`), with the S3
  source-binding statements stubbed/skipped so no credentials are required.

## Known limitations

- **Category attribution is meet-level.** `category` is a list on `dim_meet`; a
  meet tagged `["DM-L","DMJ-L"]` contributes its swims to *both* categories in the
  field-evolution views. Precise per-result category would require carrying it
  into the curated zone (a deferred Spec 2 enhancement).
- **Age is derived as `season - birth_year`**, a competition-season approximation,
  not an exact age on race day.
- **Trend views are only as deep as the data.** With the dataset still being
  backfilled, season-over-season views gain meaning as more historical meets land;
  the SQL is season-parameterized and needs no change as data grows.

## Dependencies

- Add **`duckdb`** to `st-scrape/requirements.txt`. The Python package covers the
  CLI launcher, notebook use, and tests; the standalone `duckdb` CLI is optional.
- Reuses the existing `swimtrends` AWS profile / `eu-west-1` region for S3 reads.
- No new AWS resources, no CDK changes — Spec 3 is purely local tooling over the
  data Spec 2 already produces.
