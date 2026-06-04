# Swimtrends Curated Zone — Design Spec

- **Date:** 2026-06-04
- **Status:** Approved (design); pending implementation plan
- **Spec:** 2 of 3 (Curated data lake)
- **Depends on:** Spec 1 (Ingestion platform — raw zone live)

## Context & goal

Spec 1 lands faithful, scraper-native JSONL in the raw zone — three entities at
their natural cardinality (`meet_info`, `races`, `results`), splits nested inside
results, **no points**, and `class` as a best-effort scraper guess. Everything
derived or destructive was deliberately deferred to here.

Spec 2 turns that raw zone into a **curated, query-optimized data lake**:
partitioned Parquet, World Aquatics points, a flattened lap-level splits fact,
**authoritative** para classification, and a Glue Data Catalog so Spec 3
(Athena in the cloud + Dockerized DuckDB locally) can query it without bespoke
parsing.

The split Spec 1 drew holds: **raw = faithful source mirror; curated = derived,
denormalized, analytics-shaped.** All derived logic (points, class authority,
surrogate keys, splits explosion) lives in this spec.

### Platform decomposition (this spec is #2)

1. **Ingestion platform** *(Spec 1, live)* — Fargate scraper, meet registry +
   dispatcher, raw JSONL → S3.
2. **Curated data lake** *(this spec)* — raw → partitioned Parquet + points +
   authoritative class + flattened splits, Glue catalog, schema contract.
3. **Analytics access** *(later)* — Athena (cloud) + Dockerized DuckDB (local)
   over the curated Parquet.

All three share the `swimtrends-meet-data` bucket and the raw layout from Spec 1.

### Live code this spec absorbs

The points/base-times logic exists today as local scripts and becomes the core
of the curated transform:

- `st-scrape/calc_points.py` — World Aquatics points (`points`, `points_fixed`).
- `st-scrape/gen_base_times.py` — builds the base-times table from the source
  markdown.
- `st-scrape/wa-points/*.md` — the World Aquatics base-times source documents.

These run locally today (which is why local `db/` files show points but the raw
zone does not). Spec 2 moves them into the deployed curated transform.

## Scope

### In scope
- A **curated transform**: raw JSONL → partitioned Parquet (Snappy).
- **World Aquatics points** on every individual result (`points` season-relative
  + `points_fixed` cross-era), porting `calc_points.py`.
- A **base-times reference dataset** (porting `gen_base_times.py` +
  `wa-points/*.md`) as a managed, versioned input.
- **Authoritative `class`** (open/para) with per-(meet,race) overrides,
  superseding the raw heuristic.
- **Splits flattening** into a lap-level `fact_split` with a stable surrogate
  key (solving the relay `Swimmer_id = null` non-uniqueness problem).
- Both a **conformed fact/dim** model and a denormalized **one-big-table** view.
- A **Glue Data Catalog** database + tables over the curated Parquet.
- An explicit, **versioned schema contract**.
- CLI/operational hooks to run the transform and edit reference data.

### Out of scope (Spec 3)
Athena workgroups/queries, the Dockerized DuckDB local query path,
dashboards/notebooks, and auto-discovery of meets. (Spec 3 only *reads* the
catalog and Parquet this spec produces.)

## Architecture

### Components

| Component | Service | Role |
|-----------|---------|------|
| Curated transform | ECS Fargate task (Python) | raw JSONL → curated Parquet, points, class, splits |
| Incremental trigger | S3 event → Lambda → RunTask | transform one meet when its raw lands |
| Batch trigger | CLI / Lambda | full rebuild over all meets |
| Base-times reference | S3 (versioned object) | WA base times, edited via CLI |
| Class overrides | DynamoDB `swimtrends-class-overrides` | per-(meet,race) authoritative class |
| Curated store | S3 `curated/` prefix | partitioned Parquet (fact/dim + OBT) |
| Catalog | Glue Data Catalog | `swimtrends_curated` database + tables |
| Alerts | SNS (reuse Spec 1 topic) | transform success/failure |

### Decision: compute engine — Fargate Python (not Glue/Spark)

The transform runs as a **containerized Python Fargate task** reusing the
existing, validated `calc_points.py` / `gen_base_times.py` logic and writing
Parquet via **pyarrow**. Rationale:

- The points and class logic already exist as plain Python; Glue/Spark would
  reimplement (and re-test) it for no benefit at this data volume (tens of meets,
  thousands of rows each — comfortably single-node).
- Consistency with Spec 1 (Fargate, scale-to-zero, same ECR/CDK patterns,
  same SNS topic).
- DuckDB/pyarrow in-process handles the joins and Parquet writes trivially; this
  same container image underpins Spec 3's local DuckDB path later.

A NAT-free public-subnet task (as in Spec 1) is fine: the transform reads/writes
S3 and DynamoDB only (S3/DynamoDB gateway endpoints or public egress).

### Decision: trigger model — incremental + on-demand full rebuild

Both, because they serve different events:

- **Incremental (default).** Spec 1 writes `raw/meet=<id>/results.jsonl` last;
  an **S3 `ObjectCreated` event** on that suffix invokes a thin Lambda that
  `ecs:RunTask`s the transform for that one `meet_id`. Cheap, scale-to-zero,
  keeps curated fresh within minutes of a scrape.
- **Full rebuild (on demand).** A CLI command (`swimtrends curate --all`)
  re-transforms every meet. Required because edits to **base times** or **class
  overrides** are global inputs that invalidate previously-computed points/class
  across all meets — incremental-per-meet can't capture that. Also the disaster-
  recovery / schema-migration path.

Both run the same idempotent transform; re-running a meet overwrites its curated
partition deterministically.

## Curated data model

Two layers over the same transform output.

### Conformed fact/dim (normalized, mirrors raw cardinality)

- **`dim_meet`** — 1 row/meet: `meet_id`, `meet_name`, `venue`, `course`,
  `season`, `start_date`, `end_date`, `category[]`.
- **`dim_race`** — 1 row/race: `race_id`, `meet_id`, `number`, `name`,
  `distance`, `stroke`, `gender`, `relay_count`,
  `type` ∈ {`Heats`, `Final`, `Timed final`, `Swim-off`}, **authoritative
  `class`** ∈ {`open`, `para`}.
- **`fact_result`** — 1 row/swim: surrogate **`result_id`**, `race_id`,
  `meet_id`, `Rank`, `Name`, `Swimmer_id` (nullable for relays), `nationality`,
  `club`, `birth_year`, `completed_time`, `completed_centiseconds`,
  **`points`**, **`points_fixed`**.
- **`fact_split`** — 1 row/lap: `result_id` (FK), `race_id`, `distance`,
  `split_time`, `split_centiseconds`, `cumulative_time`, `cumulative_centiseconds`.

### One Big Table (`obt_result`)

`fact_result` denormalized with all `dim_meet` + `dim_race` attributes inlined —
the friction-free single-table surface for the core analytics questions ("how
world-class for its era, by stroke / club / season / class"). Splits are **not**
inlined (cardinality explosion); they remain in `fact_split`, joinable on
`result_id`.

### The surrogate key (Spec 1 explicitly deferred this)

Relays carry `Swimmer_id = null`, so `race_id + Swimmer_id` is **not unique** and
cannot key splits. The transform mints a **deterministic** `result_id` =
`hash(race_id, Rank)` (stable per meet, idempotent across re-runs) and attaches
it to both `fact_result` and every child `fact_split` row. Determinism means a
re-transform of the same raw produces identical keys, so curated overwrites are
safe and joins are stable.

## Points (porting `calc_points.py`)

- **Formula (World Aquatics):** `points = trunc(1000 * (basetime / swimtime)³)`.
- **`points`** — scored against the **meet's own season** base times
  (era-relative: "how world-class for its time"). `null` when that
  season+course+event has no base time.
- **`points_fixed`** — scored against a single fixed reference season
  (`FIXED_REF_SEASON = 2026`): one stationary scale across all eras, the metric
  for long-term trend analysis. `null` only when the event has no base time in
  the reference season.
- Base times keyed `(season, course, gender, relay_count, distance, stroke)`;
  Danish scraper stroke codes (`Fri/Ryg/Bryst/Fly/IM/HM`) map to WA codes
  (`FREE/BACK/BREAST/FLY/MEDLEY`) — IM and team medley (HM) both → `MEDLEY`.

### Para exclusion (why points + class are colocated here)

World Aquatics able-bodied base times do not apply to para swims. Any result on
a race whose **authoritative `class = para`** gets `points = points_fixed =
null` — it is never scored against able-bodied references. This is the concrete
reason class authority lives in the same transform as points: the points
calculation *consumes* the authoritative class.

Authoritative class resolution per race:
1. If a **class override** exists for `(meet_id, race_id)` → use it.
2. Else apply the raw heuristic carried from Spec 1: a `Timed final` whose
   `name` also appears as a `Heats`/`Final` event in the same meet is `para`;
   plain distance (800/1500 free) and relay timed finals are `open`.

(See the project's para-classification note: the `Direkte finale` + duplicate-
event signal, validated on meet 9775.)

## Reference data (managed inputs)

Two small, human-curated inputs the transform reads on every run.

### Base times — versioned S3 object

Generated from `wa-points/*.md` via the ported `gen_base_times.py`; each
transcribed row self-validates (seconds recomputed from the time string must
match the source). Stored as a **versioned** object
(`s3://swimtrends-meet-data/reference/point_base_times.jsonl`); bucket versioning
gives free history. Edited via `swimtrends basetimes build` (regenerate from
markdown) → upload. A change here is a global input → triggers a full rebuild.

### Class overrides — DynamoDB `swimtrends-class-overrides`

Partition key `meet_id` (S), sort key `race_id` (N), attribute `class`
(`open`|`para`) + `reason`. For edge cases the heuristic can't catch (e.g. a
para-only event with no open twin to duplicate). Edited via
`swimtrends class set <meet_id> <race_id> para --reason "..."`. DynamoDB (not a
file) because overrides are sparse, point-edited, and keyed — and the transform
already talks to DynamoDB. A change here triggers a rebuild of the affected meet
(or `--all`).

## Data contracts

### S3 curated layout

```
s3://swimtrends-meet-data/
  raw/                          # Spec 1 (input, untouched)
    meet=<id>/{meet_info,races,results}.jsonl
  reference/
    point_base_times.jsonl      # versioned
  curated/
    dim_meet/season=<s>/course=<c>/part-*.parquet
    dim_race/season=<s>/course=<c>/part-*.parquet
    fact_result/season=<s>/course=<c>/part-*.parquet
    fact_split/season=<s>/course=<c>/part-*.parquet
    obt_result/season=<s>/course=<c>/part-*.parquet
```

- **Partitioning: `season` then `course`.** Matches how analytics slices time and
  pool length, and how base times are keyed; keeps Athena scans (Spec 3) cheap.
- Snappy-compressed Parquet. Re-transforming a meet rewrites only its rows within
  the affected partitions (overwrite-by-meet within partition).
- Bucket versioning retains prior curated outputs (audit/rollback), as in raw.

### Glue Data Catalog

A `swimtrends_curated` database with one table per curated dataset above
(`dim_meet`, `dim_race`, `fact_result`, `fact_split`, `obt_result`), partitioned
by `season`/`course`. Catalog is created/updated by the transform (or a Glue
crawler on the curated prefix — TBD at plan time; explicit `CreateTable` from the
known schema is preferred over crawler guesswork).

### Schema contract (versioned)

The curated schemas (column names, types, nullability, the `result_id`
derivation, the `type`/`class` enums) are pinned in a versioned contract checked
into the repo alongside this spec. Spec 3 codes against the contract, not against
inferred Parquet. Breaking changes bump the contract version and require a full
rebuild.

## IaC structure (CDK)

- **New `SwimtrendsCuratedStack`**: curated transform Fargate task definition +
  role, the incremental-trigger Lambda + S3 notification, the
  `swimtrends-class-overrides` DynamoDB table, the Glue database/tables, and
  curated-prefix IAM.
- **Reuse** from Spec 1: the `swimtrends-meet-data` bucket (import by name), the
  ECS cluster, the SNS alert topic, the ECR patterns.
- Curated transform image is a sibling entrypoint in the same `st-scrape`
  container (it already carries `calc_points.py`/`gen_base_times.py`), or a thin
  second image — decided at plan time.

## Observability & failure handling

- **SNS** (reuse Spec 1 topic) on transform **succeeded** (`meet_id`, row counts
  per table) and **failed** (`meet_id`, error).
- Transform is **idempotent** and safe to re-run; failures don't corrupt curated
  (write to a temp prefix then atomic-move per partition, or overwrite-by-meet).
- CloudWatch logs + an alarm on transform errors and on the incremental Lambda.

## Cost / scale-to-zero

- Curated transform runs only on a scrape event or an explicit rebuild
  (per-second Fargate billing, no idle compute).
- S3 (Parquet + versioned reference), DynamoDB on-demand (sparse overrides), Glue
  catalog, and SNS are negligible at this volume.
- Idle cost ≈ S3 storage of raw + curated Parquet.

## Assumptions

- Data volume stays single-node-friendly (tens of meets, low-thousands of rows
  each) → Python/pyarrow, not Spark.
- `st-scrape` remains the single source of truth for points/base-times logic,
  shared by the curated transform.
- World Aquatics base times are senior/able-bodied only; para results are
  unscored by design.
- `result_id = hash(race_id, Rank)` is unique within a race (Rank is unique per
  race in the source); revisit if a meet ever ties ranks.

## Open questions for plan phase

- Glue table creation: explicit `CreateTable` vs crawler.
- Single shared `st-scrape` image with multiple entrypoints vs a dedicated
  curated image.
- Exact atomicity strategy for partition overwrites (temp-prefix move vs
  per-meet delete+write).
