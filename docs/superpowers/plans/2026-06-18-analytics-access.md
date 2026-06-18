# Analytics Access (Spec 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local DuckDB analytics layer that queries the curated Parquet directly from S3, plus a version-controlled library of analytical views, runnable via a `swimtrends query` REPL and from notebooks.

**Architecture:** A new `st-scrape/analytics/` package. `bootstrap.sql` loads the DuckDB S3 extensions + credential secret and defines source-binding views (`cur_*`) over `s3://swimtrends-meet-data/curated/`. `views/*.sql` define base hygiene views and the analytical catalog, depending only on the `cur_*` names. A thin `loader.py` executes the SQL against a `duckdb` connection; tests swap the S3 source-binding for in-memory fixture tables, so the whole catalog is testable with no AWS.

**Tech Stack:** Python 3.12, `duckdb` (Python package), pytest. No AWS resources, no CDK.

**Conventions for this repo:**
- Run tests with `.venv/bin/python -m pytest` from `st-scrape/`.
- Commit messages end with the trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- The branch is `analytics-access`.

**Key data facts (from Spec 2 `curate/parquet.py`):**
- The one-big-table `obt_result` carries everything analytical: `result_id, race_id, meet_id, rank, name, swimmer_id, nationality, club, birth_year, completed_time, completed_centiseconds, points, points_fixed, season, course, meet_name, venue, meet_date, number, race_name, distance, stroke, gender, relay_count, type, class`.
- `dim_meet` carries `category` as a **list of strings** (`VARCHAR[]`); it is NOT on `obt_result`.
- `fact_split` carries lap-level `result_id, race_id, distance, split_time, split_centiseconds, cumulative_time, cumulative_centiseconds, season, course`.
- DQs use `rank = -1`. Relays use `relay_count > 1` and `swimmer_id IS NULL`.
- `type` values include `Heats`, `Final`, `Timed final` (para maps to `Timed final`).
- **Important:** `season` and `course` exist BOTH in the partition path (`season=…/course=…`) and as columns inside each Parquet file. Read with `hive_partitioning` **disabled** and take them from the file columns to avoid a duplicate-column bind error.

---

## File Structure

```
st-scrape/
  requirements.txt                     # MODIFY: add duckdb
  analytics/
    __init__.py                        # CREATE: empty package marker
    bootstrap.sql                      # CREATE: S3 extensions + secret + cur_* views
    loader.py                          # CREATE: create_views / bind_s3 / assemble_sql / connect
    views/
      00_base.sql                      # CREATE: results, individual_results
      10_best_times.sql                # CREATE: personal_best, season_best, event_leaderboard
      20_progression.sql               # CREATE: swimmer_progression, biggest_improvers, cross_era_best
      30_aggregates.sql                # CREATE: club_leaderboard, age_group_ranking, meet_summary
      40_splits.sql                    # CREATE: pacing
      50_field_evolution.sql           # CREATE: results_by_category, event_standard_by_season,
                                       #         prelim_ranked, final_cutline_by_season, cutline_at()
  ingestion/cli.py                     # MODIFY: add `query` subcommand
  tests/
    analytics_fixtures.py              # CREATE: build in-memory cur_* tables from row dicts
    test_analytics_loader.py           # CREATE: loader + base hygiene tests
    test_analytics_best_times.py       # CREATE
    test_analytics_progression.py      # CREATE
    test_analytics_aggregates.py       # CREATE
    test_analytics_splits.py           # CREATE
    test_analytics_field_evolution.py  # CREATE
    test_cli_query.py                  # CREATE
docs/analytics.md                      # CREATE: usage notes
```

Each `views/*.sql` file is loaded in filename order, so the numeric prefixes guarantee `00_base` is created before any view that depends on it.

---

## Task 1: Package scaffold, loader, fixtures, and base views

**Files:**
- Modify: `requirements.txt`
- Create: `analytics/__init__.py`, `analytics/loader.py`, `analytics/views/00_base.sql`
- Create: `tests/analytics_fixtures.py`, `tests/test_analytics_loader.py`

- [ ] **Step 1: Add the dependency and install it**

Append to `requirements.txt`:

```
duckdb>=1.0
```

Run: `.venv/bin/python -m pip install "duckdb>=1.0"`
Expected: installs cleanly; `.venv/bin/python -c "import duckdb; print(duckdb.__version__)"` prints a 1.x version.

- [ ] **Step 2: Create the package marker and the fixture helper**

Create `analytics/__init__.py` (empty file).

Create `tests/analytics_fixtures.py`:

```python
"""Build in-memory curated base tables for analytics view tests (no S3).

Mirrors the Spec 2 curated schema (curate/parquet.py). Each builder creates a
`cur_*` table that the analytics views bind to, so view SQL is exercised exactly
as in production but against hand-built rows instead of S3 Parquet.
"""

OBT_COLS = [
    ("result_id", "VARCHAR"), ("race_id", "BIGINT"), ("meet_id", "VARCHAR"),
    ("rank", "BIGINT"), ("name", "VARCHAR"), ("swimmer_id", "VARCHAR"),
    ("nationality", "VARCHAR"), ("club", "VARCHAR"), ("birth_year", "BIGINT"),
    ("completed_time", "VARCHAR"), ("completed_centiseconds", "BIGINT"),
    ("points", "BIGINT"), ("points_fixed", "BIGINT"), ("season", "BIGINT"),
    ("course", "VARCHAR"), ("meet_name", "VARCHAR"), ("venue", "VARCHAR"),
    ("meet_date", "VARCHAR"), ("number", "BIGINT"), ("race_name", "VARCHAR"),
    ("distance", "BIGINT"), ("stroke", "VARCHAR"), ("gender", "VARCHAR"),
    ("relay_count", "BIGINT"), ("type", "VARCHAR"), ("class", "VARCHAR"),
]
MEET_COLS = [
    ("meet_id", "VARCHAR"), ("meet_name", "VARCHAR"), ("venue", "VARCHAR"),
    ("course", "VARCHAR"), ("season", "BIGINT"), ("meet_date", "VARCHAR"),
    ("category", "VARCHAR[]"),
]
SPLIT_COLS = [
    ("result_id", "VARCHAR"), ("race_id", "BIGINT"), ("distance", "BIGINT"),
    ("split_time", "VARCHAR"), ("split_centiseconds", "BIGINT"),
    ("cumulative_time", "VARCHAR"), ("cumulative_centiseconds", "BIGINT"),
    ("season", "BIGINT"), ("course", "VARCHAR"),
]


def _create(con, name, cols, rows):
    coldef = ", ".join(f"{c} {t}" for c, t in cols)
    con.execute(f"CREATE OR REPLACE TABLE {name} ({coldef})")
    if rows:
        names = [c for c, _ in cols]
        placeholders = ", ".join("?" for _ in cols)
        con.executemany(
            f"INSERT INTO {name} VALUES ({placeholders})",
            [[r.get(n) for n in names] for r in rows],
        )


def build_curated(con, *, obt=None, meets=None, splits=None):
    """Create cur_obt / cur_dim_meet / cur_fact_split from lists of dicts.

    Every view in the catalog binds to these three names, so all three are
    always created (empty by default) to keep create_views() resolvable."""
    _create(con, "cur_obt", OBT_COLS, obt or [])
    _create(con, "cur_dim_meet", MEET_COLS, meets or [])
    _create(con, "cur_fact_split", SPLIT_COLS, splits or [])
    return con
```

- [ ] **Step 3: Write the loader**

Create `analytics/loader.py`:

```python
"""Assemble and execute the analytics SQL against a DuckDB connection.

create_views() depends only on the cur_* names existing (S3 views in
production, fixture tables in tests). bind_s3() supplies the production cur_*
views from S3. connect() is the production entry point used by the CLI.
"""
from pathlib import Path

import duckdb

_DIR = Path(__file__).resolve().parent
BOOTSTRAP_SQL = _DIR / "bootstrap.sql"
VIEWS_DIR = _DIR / "views"


def _view_files():
    return sorted(VIEWS_DIR.glob("*.sql"))


def create_views(con):
    """Define the base + analytical views. Requires cur_* to already exist."""
    for path in _view_files():
        con.execute(path.read_text(encoding="utf-8"))
    return con


def bind_s3(con):
    """Load S3 extensions + secret and define the cur_* source-binding views."""
    con.execute(BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    return con


def assemble_sql():
    """Full bootstrap + views SQL as one script (for notebooks / duckdb CLI -init)."""
    parts = [BOOTSTRAP_SQL.read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in _view_files()]
    return "\n\n".join(parts)


def connect():
    """Production: an in-memory DuckDB bound to the curated zone with all views."""
    con = duckdb.connect()
    bind_s3(con)
    create_views(con)
    return con
```

- [ ] **Step 4: Write the base views**

Create `analytics/views/00_base.sql`:

```sql
-- One row per result, with universal derivations. NO category here: category is
-- a list on dim_meet and unnesting it would multiply rows and break aggregates.
-- Category lives in 50_field_evolution.sql's results_by_category instead.
CREATE OR REPLACE VIEW results AS
SELECT
    o.*,
    o.season - o.birth_year AS age,
    o.relay_count > 1       AS is_relay,
    o.rank = -1             AS is_dq,
    CASE o.type
        WHEN 'Heats' THEN 'heats'
        WHEN 'Final' THEN 'final'
        ELSE 'timed_final'
    END                     AS phase,
    concat_ws(' ', o.gender, o.distance || 'm', o.stroke, '(' || o.course || ')') AS event
FROM cur_obt o;

-- The default base for swimmer-level analysis: real individual swims only.
CREATE OR REPLACE VIEW individual_results AS
SELECT * FROM results
WHERE NOT is_relay AND swimmer_id IS NOT NULL AND NOT is_dq;
```

- [ ] **Step 5: Write the loader + base hygiene tests**

Create `tests/test_analytics_loader.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated


def _con(**rows):
    con = duckdb.connect()
    build_curated(con, **rows)
    loader.create_views(con)
    return con


def test_create_views_defines_base_views():
    con = _con()
    names = {r[0] for r in con.execute(
        "SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    assert {"results", "individual_results"} <= names


def test_individual_results_excludes_dq_and_relays():
    con = _con(obt=[
        dict(result_id="r1", swimmer_id="s1", rank=1, relay_count=1, type="Final",
             season=2024, birth_year=2008),
        dict(result_id="r2", swimmer_id="s2", rank=-1, relay_count=1, type="Final",
             season=2024, birth_year=2009),                       # DQ
        dict(result_id="r3", swimmer_id=None, rank=1, relay_count=4, type="Final",
             season=2024, birth_year=None),                        # relay
    ])
    ids = [r[0] for r in con.execute(
        "SELECT result_id FROM individual_results ORDER BY result_id").fetchall()]
    assert ids == ["r1"]


def test_results_derives_age_and_phase():
    con = _con(obt=[
        dict(result_id="r1", swimmer_id="s1", rank=1, relay_count=1, type="Heats",
             season=2024, birth_year=2008),
    ])
    age, phase = con.execute(
        "SELECT age, phase FROM results WHERE result_id = 'r1'").fetchone()
    assert age == 16
    assert phase == "heats"
```

- [ ] **Step 6: Run the tests to verify they fail, then pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_loader.py -v`
Expected first run: had they been run before the files existed, FAIL with import/file errors. With Steps 2–4 in place, all three PASS.

(If you are following strict TDD: create `tests/test_analytics_loader.py` and `analytics/__init__.py`/`loader.py` skeletons first, watch the assertions fail on missing views, then add `00_base.sql` and watch them pass.)

- [ ] **Step 7: Commit**

```bash
git add requirements.txt analytics/__init__.py analytics/loader.py \
        analytics/views/00_base.sql tests/analytics_fixtures.py \
        tests/test_analytics_loader.py
git commit -m "feat: add analytics package, loader, and base curated views

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Best-times & ranking views

**Files:**
- Create: `analytics/views/10_best_times.sql`
- Create: `tests/test_analytics_best_times.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analytics_best_times.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=200,
             stroke="Breast", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_personal_best_picks_fastest_swim():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=2, completed_centiseconds=15000,
             completed_time="2:30.00", points=600, meet_name="M1", meet_date="2024-03-01",
             season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=14800,
             completed_time="2:28.00", points=620, meet_name="M2", meet_date="2024-05-01",
             season=2024, birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT best_centiseconds, best_time, meet_name FROM personal_best "
        "WHERE swimmer_id = 's1'").fetchone()
    assert row == (14800, "2:28.00", "M2")


def test_event_leaderboard_ranks_by_points_desc():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=14800,
             points=620, season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s2", rank=2, completed_centiseconds=15000,
             points=600, season=2024, birth_year=2007, **EVENT),
    ])
    rows = con.execute(
        "SELECT swimmer_id, points_rank FROM event_leaderboard ORDER BY points_rank"
    ).fetchall()
    assert rows == [("s1", 1), ("s2", 2)]
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_best_times.py -v`
Expected: FAIL — `Catalog Error: Table with name personal_best does not exist`.

- [ ] **Step 3: Write the views**

Create `analytics/views/10_best_times.sql`:

```sql
-- Fastest individual swim per swimmer, event, course (all seasons).
CREATE OR REPLACE VIEW personal_best AS
SELECT
    swimmer_id,
    any_value(name)                                  AS name,
    gender, distance, stroke, course,
    min(completed_centiseconds)                      AS best_centiseconds,
    arg_min(completed_time, completed_centiseconds)  AS best_time,
    arg_min(points,         completed_centiseconds)  AS points,
    arg_min(meet_name,      completed_centiseconds)  AS meet_name,
    arg_min(meet_date,      completed_centiseconds)  AS meet_date,
    arg_min(season,         completed_centiseconds)  AS season
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
GROUP BY swimmer_id, gender, distance, stroke, course;

-- Fastest individual swim per swimmer, event, course, season.
CREATE OR REPLACE VIEW season_best AS
SELECT
    swimmer_id,
    any_value(name)                                  AS name,
    season, gender, distance, stroke, course,
    min(completed_centiseconds)                      AS best_centiseconds,
    arg_min(completed_time, completed_centiseconds)  AS best_time,
    arg_min(points,         completed_centiseconds)  AS points,
    arg_min(meet_name,      completed_centiseconds)  AS meet_name,
    arg_min(meet_date,      completed_centiseconds)  AS meet_date
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
GROUP BY swimmer_id, season, gender, distance, stroke, course;

-- Ranked leaderboard by World Aquatics points per event/season.
-- Emits a points_rank column; filter `WHERE points_rank <= 8` for a top-8.
CREATE OR REPLACE VIEW event_leaderboard AS
SELECT
    season, gender, distance, stroke, course,
    swimmer_id, name, club, points, completed_time, meet_name, meet_date,
    rank() OVER (
        PARTITION BY season, gender, distance, stroke, course
        ORDER BY points DESC
    ) AS points_rank
FROM individual_results
WHERE points IS NOT NULL;
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_best_times.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add analytics/views/10_best_times.sql tests/test_analytics_best_times.py
git commit -m "feat: add best-times and event-leaderboard views

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Progression & cross-era views

**Files:**
- Create: `analytics/views/20_progression.sql`
- Create: `tests/test_analytics_progression.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analytics_progression.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="F", distance=100,
             stroke="Free", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_swimmer_progression_delta_vs_previous_swim():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=6000,
             points=600, meet_date="2024-03-01", season=2024, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=5900,
             points=620, meet_date="2024-06-01", season=2024, birth_year=2010, **EVENT),
    ])
    rows = con.execute(
        "SELECT meet_date, delta_centiseconds FROM swimmer_progression "
        "WHERE swimmer_id='s1' ORDER BY meet_date").fetchall()
    assert rows == [("2024-03-01", None), ("2024-06-01", -100)]


def test_cross_era_best_ranks_by_points_fixed():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=5900,
             points=620, points_fixed=700, season=2024, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s2", rank=1, completed_centiseconds=5950,
             points=610, points_fixed=720, season=2020, birth_year=2006, **EVENT),
    ])
    rows = con.execute(
        "SELECT swimmer_id, era_rank FROM cross_era_best ORDER BY era_rank").fetchall()
    assert rows == [("s2", 1), ("s1", 2)]  # s2 wins on points_fixed despite slower time


def test_biggest_improvers_season_over_season():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=6200,
             points=560, season=2023, birth_year=2010, **EVENT),
        dict(result_id="b", swimmer_id="s1", rank=1, completed_centiseconds=6000,
             points=600, season=2024, birth_year=2010, **EVENT),
    ])
    row = con.execute(
        "SELECT season, improvement_centiseconds, improvement_points "
        "FROM biggest_improvers WHERE swimmer_id='s1'").fetchone()
    assert row == (2024, 200, 40)  # 200cs faster, +40 points vs 2023
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_progression.py -v`
Expected: FAIL — `swimmer_progression does not exist`.

- [ ] **Step 3: Write the views**

Create `analytics/views/20_progression.sql`:

```sql
-- One swimmer's swims over time per event, with delta vs their previous swim.
-- delta_centiseconds < 0 means faster (an improvement).
CREATE OR REPLACE VIEW swimmer_progression AS
SELECT
    swimmer_id, name, gender, distance, stroke, course,
    season, meet_date, meet_name,
    completed_centiseconds, completed_time, points,
    completed_centiseconds - lag(completed_centiseconds) OVER w AS delta_centiseconds,
    points - lag(points) OVER w                                 AS delta_points
FROM individual_results
WHERE completed_centiseconds IS NOT NULL
WINDOW w AS (
    PARTITION BY swimmer_id, gender, distance, stroke, course
    ORDER BY meet_date
);

-- Best performances of all time, era-normalised via points_fixed.
CREATE OR REPLACE VIEW cross_era_best AS
SELECT
    gender, distance, stroke, course,
    swimmer_id, name, club, season, meet_name, meet_date,
    completed_time, points, points_fixed,
    rank() OVER (
        PARTITION BY gender, distance, stroke, course
        ORDER BY points_fixed DESC
    ) AS era_rank
FROM individual_results
WHERE points_fixed IS NOT NULL;

-- Largest season-over-season improvement per swimmer/event.
-- improvement_centiseconds > 0 means this season's best was faster than last.
CREATE OR REPLACE VIEW biggest_improvers AS
WITH best AS (
    SELECT
        swimmer_id, any_value(name) AS name,
        season, gender, distance, stroke, course,
        min(completed_centiseconds) AS best_cs,
        max(points)                 AS best_points
    FROM individual_results
    WHERE completed_centiseconds IS NOT NULL
    GROUP BY swimmer_id, season, gender, distance, stroke, course
)
SELECT
    swimmer_id, name, gender, distance, stroke, course, season,
    best_cs,
    lag(best_cs) OVER w                  AS prev_best_cs,
    lag(best_cs) OVER w - best_cs        AS improvement_centiseconds,
    best_points - lag(best_points) OVER w AS improvement_points
FROM best
WINDOW w AS (
    PARTITION BY swimmer_id, gender, distance, stroke, course
    ORDER BY season
)
QUALIFY prev_best_cs IS NOT NULL;
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_progression.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add analytics/views/20_progression.sql tests/test_analytics_progression.py
git commit -m "feat: add progression, cross-era, and improver views

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Club, age-group, and meet aggregate views

**Files:**
- Create: `analytics/views/30_aggregates.sql`
- Create: `tests/test_analytics_aggregates.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analytics_aggregates.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=50,
             stroke="Free", course="LCM")


def _con(obt):
    con = duckdb.connect()
    build_curated(con, obt=obt)
    loader.create_views(con)
    return con


def test_club_leaderboard_counts_podiums_and_points():
    con = _con([
        dict(result_id="a", swimmer_id="s1", club="AC", rank=1, points=600,
             completed_centiseconds=2600, season=2024, birth_year=2008, **EVENT),
        dict(result_id="b", swimmer_id="s2", club="AC", rank=4, points=500,
             completed_centiseconds=2700, season=2024, birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT swims, swimmers, podiums, total_points, best_points "
        "FROM club_leaderboard WHERE club='AC' AND season=2024").fetchone()
    assert row == (2, 2, 1, 1100, 600)


def test_age_group_ranking_buckets_and_ranks():
    con = _con([
        dict(result_id="a", swimmer_id="s1", rank=1, completed_centiseconds=2600,
             season=2024, birth_year=2010, **EVENT),  # age 14 -> 13-14
        dict(result_id="b", swimmer_id="s2", rank=1, completed_centiseconds=2500,
             season=2024, birth_year=2009, **EVENT),  # age 15 -> 15-16
    ])
    rows = con.execute(
        "SELECT swimmer_id, age_group, age_group_rank FROM age_group_ranking "
        "ORDER BY swimmer_id").fetchall()
    assert rows == [("s1", "13-14", 1), ("s2", "15-16", 1)]


def test_meet_summary_counts():
    con = _con([
        dict(result_id="a", race_id=1, swimmer_id="s1", meet_id="m1", meet_name="M1",
             rank=1, points=600, completed_centiseconds=2600, season=2024,
             birth_year=2008, **EVENT),
        dict(result_id="b", race_id=1, swimmer_id="s2", meet_id="m1", meet_name="M1",
             rank=2, points=580, completed_centiseconds=2650, season=2024,
             birth_year=2008, **EVENT),
    ])
    row = con.execute(
        "SELECT results, races, swimmers, top_points, top_points_swimmer "
        "FROM meet_summary WHERE meet_id='m1'").fetchone()
    assert row == (2, 1, 2, 600, "s1")
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_aggregates.py -v`
Expected: FAIL — `club_leaderboard does not exist`.

- [ ] **Step 3: Write the views**

Create `analytics/views/30_aggregates.sql`:

```sql
-- Per club per season: volume, distinct swimmers, podiums, points.
CREATE OR REPLACE VIEW club_leaderboard AS
SELECT
    club, season,
    count(*)                                      AS swims,
    count(DISTINCT swimmer_id)                    AS swimmers,
    count(*) FILTER (WHERE rank BETWEEN 1 AND 3)  AS podiums,
    sum(points)                                   AS total_points,
    max(points)                                   AS best_points
FROM individual_results
WHERE club IS NOT NULL
GROUP BY club, season;

-- Age-group rankings: bucket by competition-season age, rank within band.
CREATE OR REPLACE VIEW age_group_ranking AS
WITH banded AS (
    SELECT *,
        CASE
            WHEN age <= 12 THEN '<=12'
            WHEN age <= 14 THEN '13-14'
            WHEN age <= 16 THEN '15-16'
            WHEN age <= 18 THEN '17-18'
            ELSE '19+'
        END AS age_group
    FROM individual_results
    WHERE age IS NOT NULL AND completed_centiseconds IS NOT NULL
)
SELECT
    season, gender, distance, stroke, course, age_group,
    swimmer_id, name, club, age, completed_time, points,
    rank() OVER (
        PARTITION BY season, gender, distance, stroke, course, age_group
        ORDER BY completed_centiseconds
    ) AS age_group_rank
FROM banded;

-- Per-meet summary: volume + the standout swim.
CREATE OR REPLACE VIEW meet_summary AS
SELECT
    meet_id,
    any_value(meet_name)        AS meet_name,
    any_value(meet_date)        AS meet_date,
    any_value(season)           AS season,
    count(*)                    AS results,
    count(DISTINCT race_id)     AS races,
    count(DISTINCT swimmer_id)  AS swimmers,
    max(points)                 AS top_points,
    arg_max(swimmer_id, points) AS top_points_swimmer
FROM results
GROUP BY meet_id;
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_aggregates.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add analytics/views/30_aggregates.sql tests/test_analytics_aggregates.py
git commit -m "feat: add club, age-group, and meet-summary views

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Pacing (splits) view

**Files:**
- Create: `analytics/views/40_splits.sql`
- Create: `tests/test_analytics_splits.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_analytics_splits.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, type="Final", gender="M", distance=100,
             stroke="Free", course="LCM")


def test_pacing_flags_negative_split():
    con = duckdb.connect()
    build_curated(
        con,
        obt=[dict(result_id="r1", swimmer_id="s1", rank=1, completed_centiseconds=5800,
                  season=2024, birth_year=2008, **EVENT)],
        # 4 laps; second half (laps 3-4) faster than first half (laps 1-2).
        splits=[
            dict(result_id="r1", race_id=1, distance=25, split_centiseconds=1500,
                 cumulative_centiseconds=1500),
            dict(result_id="r1", race_id=1, distance=50, split_centiseconds=1500,
                 cumulative_centiseconds=3000),
            dict(result_id="r1", race_id=1, distance=75, split_centiseconds=1400,
                 cumulative_centiseconds=4400),
            dict(result_id="r1", race_id=1, distance=100, split_centiseconds=1400,
                 cumulative_centiseconds=5800),
        ],
    )
    loader.create_views(con)
    row = con.execute(
        "SELECT first_half_cs, second_half_cs, back_half_delta_cs, negative_split "
        "FROM pacing WHERE result_id='r1'").fetchone()
    assert row == (3000, 2800, -200, True)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_splits.py -v`
Expected: FAIL — `pacing does not exist`.

- [ ] **Step 3: Write the view**

Create `analytics/views/40_splits.sql`:

```sql
-- Pacing per individual result: first-half vs second-half time from splits.
-- Laps are ordered by cumulative time; for an odd lap count the middle lap
-- falls into the second half (integer division). negative_split = faster back half.
CREATE OR REPLACE VIEW pacing AS
WITH ordered AS (
    SELECT
        result_id, split_centiseconds,
        row_number() OVER (PARTITION BY result_id ORDER BY cumulative_centiseconds) AS lap,
        count(*)     OVER (PARTITION BY result_id) AS laps
    FROM cur_fact_split
    WHERE split_centiseconds IS NOT NULL
),
halves AS (
    SELECT
        result_id,
        sum(split_centiseconds) FILTER (WHERE lap <= laps / 2) AS first_half_cs,
        sum(split_centiseconds) FILTER (WHERE lap >  laps / 2) AS second_half_cs
    FROM ordered
    WHERE laps >= 2
    GROUP BY result_id
)
SELECT
    h.result_id,
    r.name, r.gender, r.distance, r.stroke, r.course, r.season, r.meet_name,
    h.first_half_cs, h.second_half_cs,
    h.second_half_cs - h.first_half_cs AS back_half_delta_cs,
    h.second_half_cs < h.first_half_cs AS negative_split
FROM halves h
JOIN individual_results r USING (result_id);
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_splits.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add analytics/views/40_splits.sql tests/test_analytics_splits.py
git commit -m "feat: add splits-based pacing view

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Field-evolution views (championship trends)

**Files:**
- Create: `analytics/views/50_field_evolution.sql`
- Create: `tests/test_analytics_field_evolution.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analytics_field_evolution.py`:

```python
import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated

EVENT = dict(relay_count=1, gender="M", distance=200, stroke="Breast", course="LCM")


def _heats(n, season, cs_base):
    """n heat swims for one event/season at meet m1 (category DM-L)."""
    return [
        dict(result_id=f"{season}-{i}", swimmer_id=f"s{i}", rank=i + 1, type="Heats",
             completed_centiseconds=cs_base + i * 10, completed_time=f"t{i}",
             meet_id="m1", season=season, birth_year=2005, **EVENT)
        for i in range(n)
    ]


def _con(obt, meets):
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets)
    loader.create_views(con)
    return con


MEETS = [dict(meet_id="m1", season=2024, course="LCM", category=["DM-L"])]


def test_two_category_meet_pools_into_each_category():
    con = _con(
        obt=[dict(result_id="r1", swimmer_id="s1", rank=1, type="Final",
                  completed_centiseconds=15000, meet_id="m1", season=2024,
                  birth_year=2005, **EVENT)],
        meets=[dict(meet_id="m1", season=2024, course="LCM",
                    category=["DM-L", "DMJ-L"])],
    )
    cats = [r[0] for r in con.execute(
        "SELECT category FROM results_by_category WHERE result_id='r1' "
        "ORDER BY category").fetchall()]
    assert cats == ["DM-L", "DMJ-L"]


def test_final_cutline_is_eighth_fastest_heat_swim():
    # 10 heat swims; rank-8 fastest is the cut-line.
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT cutline_centiseconds FROM final_cutline_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15000 + 7 * 10,)  # 8th fastest = index 7


def test_cutline_at_macro_supports_other_n():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT cutline_centiseconds FROM cutline_at(6) "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (15000 + 5 * 10,)  # 6th fastest = index 5


def test_event_standard_by_season_best_and_count():
    con = _con(obt=_heats(10, 2024, 15000), meets=MEETS)
    row = con.execute(
        "SELECT swims, best_cs FROM event_standard_by_season "
        "WHERE category='DM-L' AND season=2024").fetchone()
    assert row == (10, 15000)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_field_evolution.py -v`
Expected: FAIL — `results_by_category does not exist`.

- [ ] **Step 3: Write the views**

Create `analytics/views/50_field_evolution.sql`:

```sql
-- Individual swims exploded to one row per (swim, meet category) for
-- championship trends. A meet tagged with multiple categories contributes to
-- each; counts here are per-category and intentionally NOT 1:1 with
-- individual_results. Meets with no category are excluded (not championships).
CREATE OR REPLACE VIEW results_by_category AS
SELECT r.*, cat.category AS category
FROM individual_results r
JOIN cur_dim_meet m USING (meet_id)
CROSS JOIN UNNEST(m.category) AS cat(category);

-- How an event's standard moves across seasons, per championship category.
CREATE OR REPLACE VIEW event_standard_by_season AS
SELECT
    category, season, course, gender, distance, stroke,
    count(*)                                       AS swims,
    min(completed_centiseconds)                    AS best_cs,
    quantile_cont(completed_centiseconds, 0.5)     AS median_cs,
    quantile_cont(completed_centiseconds, 0.25)    AS p25_cs,
    quantile_cont(completed_centiseconds, 0.75)    AS p75_cs,
    avg(completed_centiseconds) FILTER (WHERE time_rank <= 8) AS top8_avg_cs
FROM (
    SELECT *,
        rank() OVER (
            PARTITION BY category, season, course, gender, distance, stroke
            ORDER BY completed_centiseconds
        ) AS time_rank
    FROM results_by_category
    WHERE completed_centiseconds IS NOT NULL
)
GROUP BY category, season, course, gender, distance, stroke;

-- Preliminary swims ranked by time within championship/event/season.
CREATE OR REPLACE VIEW prelim_ranked AS
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds, completed_time, swimmer_id, name,
    row_number() OVER (
        PARTITION BY category, season, course, gender, distance, stroke
        ORDER BY completed_centiseconds
    ) AS heat_rank
FROM results_by_category
WHERE phase = 'heats' AND completed_centiseconds IS NOT NULL;

-- The cut-line to make an 8-lane final: the 8th-fastest prelim swim.
CREATE OR REPLACE VIEW final_cutline_by_season AS
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds AS cutline_centiseconds,
    completed_time         AS cutline_time,
    swimmer_id, name
FROM prelim_ranked
WHERE heat_rank = 8;

-- Same cut-line for an arbitrary final size: SELECT * FROM cutline_at(6).
CREATE OR REPLACE MACRO cutline_at(n) AS TABLE
SELECT
    category, season, course, gender, distance, stroke,
    completed_centiseconds AS cutline_centiseconds,
    completed_time         AS cutline_time,
    swimmer_id, name
FROM prelim_ranked
WHERE heat_rank = n;
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_field_evolution.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add analytics/views/50_field_evolution.sql tests/test_analytics_field_evolution.py
git commit -m "feat: add field-evolution and final-cutline views

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: S3 source binding (`bootstrap.sql`)

**Files:**
- Create: `analytics/bootstrap.sql`
- Modify: `tests/test_analytics_loader.py` (add assemble/bind tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_loader.py`:

```python
def test_assemble_sql_includes_s3_source_binding():
    sql = loader.assemble_sql()
    assert "read_parquet('s3://swimtrends-meet-data/curated/obt_result/" in sql
    assert "credential_chain" in sql
    assert "hive_partitioning = false" in sql  # season/course come from file columns
    # base views must come after the source binding
    assert sql.index("CREATE SECRET") < sql.index("CREATE OR REPLACE VIEW results")


def test_assemble_sql_binds_all_five_curated_tables():
    sql = loader.assemble_sql()
    for table in ["obt_result", "dim_meet", "dim_race", "fact_result", "fact_split"]:
        assert f"curated/{table}/" in sql
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_analytics_loader.py -k assemble -v`
Expected: FAIL — `FileNotFoundError` / missing `bootstrap.sql`.

- [ ] **Step 3: Write the bootstrap SQL**

Create `analytics/bootstrap.sql`:

```sql
-- S3 access for DuckDB: extensions + a credential-chain secret using the
-- 'swimtrends' AWS profile in eu-west-1.
INSTALL httpfs;
LOAD httpfs;
INSTALL aws;
LOAD aws;

CREATE OR REPLACE SECRET swimtrends_s3 (
    TYPE s3,
    PROVIDER credential_chain,
    CHAIN 'sso;sts;env;config',
    PROFILE 'swimtrends',
    REGION 'eu-west-1'
);

-- Source-binding views over the Spec 2 curated zone. hive_partitioning is OFF:
-- season and course are stored as columns INSIDE each Parquet file as well as in
-- the season=/course= path, so enabling hive partitioning would bind them twice.
CREATE OR REPLACE VIEW cur_obt AS
    SELECT * FROM read_parquet(
        's3://swimtrends-meet-data/curated/obt_result/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_dim_meet AS
    SELECT * FROM read_parquet(
        's3://swimtrends-meet-data/curated/dim_meet/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_dim_race AS
    SELECT * FROM read_parquet(
        's3://swimtrends-meet-data/curated/dim_race/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_fact_result AS
    SELECT * FROM read_parquet(
        's3://swimtrends-meet-data/curated/fact_result/**/*.parquet',
        hive_partitioning = false);
CREATE OR REPLACE VIEW cur_fact_split AS
    SELECT * FROM read_parquet(
        's3://swimtrends-meet-data/curated/fact_split/**/*.parquet',
        hive_partitioning = false);
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_loader.py -v`
Expected: PASS (all loader tests, including the two new assemble tests).

- [ ] **Step 5: Commit**

```bash
git add analytics/bootstrap.sql tests/test_analytics_loader.py
git commit -m "feat: add S3 source-binding bootstrap for the curated zone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `swimtrends query` CLI subcommand

**Files:**
- Modify: `ingestion/cli.py`
- Create: `tests/test_cli_query.py`

First read `ingestion/cli.py` to confirm the current `run(...)`/`main()` signatures and argparse structure before editing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_query.py`:

```python
import duckdb

from ingestion import cli


def test_query_runs_one_shot_sql_and_prints(capsys):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT 42 AS answer")
    rc = cli.run(
        ["query", "--sql", "SELECT answer FROM t"],
        registry=None, invoke=None, connect=lambda: con,
    )
    assert rc == 0
    assert "42" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_cli_query.py -v`
Expected: FAIL — `run() got an unexpected keyword argument 'connect'` (or the `query` subcommand is unknown).

- [ ] **Step 3: Wire the subcommand**

In `ingestion/cli.py`:

1. Add `connect=None` to the `run(...)` keyword-only parameters.
2. Register a `query` subparser with `--sql` (optional one-shot) in the argparse setup, mirroring how existing subcommands are added.
3. Add the handler branch:

```python
    if args.command == "query":
        con = (connect or _default_query_connect)()
        if args.sql:
            print(con.sql(args.sql))
            return 0
        import code
        banner = ("swimtrends analytics — DuckDB ready. "
                  "`con` is the connection; sql('SELECT …') prints a result.\n"
                  "Views: personal_best, event_leaderboard, swimmer_progression, "
                  "cross_era_best, club_leaderboard, age_group_ranking, pacing, "
                  "event_standard_by_season, final_cutline_by_season, …")
        code.interact(banner=banner, local={"con": con, "sql": lambda q: print(con.sql(q))})
        return 0
```

4. Add the default connect helper (import lazily so non-query commands don't import duckdb):

```python
def _default_query_connect():
    from analytics import loader
    return loader.connect()
```

5. In `main()`, pass `connect=_default_query_connect` into `run(...)` (or rely on the `or` fallback inside `run`).

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/python -m pytest tests/test_cli_query.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ingestion/cli.py tests/test_cli_query.py
git commit -m "feat: add swimtrends query CLI subcommand

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Usage docs and full-suite verification

**Files:**
- Create: `docs/analytics.md`

- [ ] **Step 1: Write the usage doc**

Create `docs/analytics.md`:

```markdown
# Analytics (Spec 3): local DuckDB over the curated zone

Read-only ad-hoc analysis of the curated Parquet, straight from S3.

## Prerequisites
- `pip install -r st-scrape/requirements.txt` (provides `duckdb`).
- AWS credentials for the `swimtrends` profile (eu-west-1); DuckDB reads S3 via a
  credential-chain secret. First run downloads the `httpfs`/`aws` extensions.

## Interactive REPL
```bash
cd st-scrape
swimtrends query
```
`con` is the DuckDB connection; `sql("…")` prints a result. All views are loaded.

One-shot:
```bash
swimtrends query --sql "SELECT * FROM final_cutline_by_season \
  WHERE category='DM-L' AND distance=200 AND stroke='Breast' ORDER BY season"
```

## From a notebook / Python
```python
from analytics import loader
con = loader.connect()
con.sql("SELECT * FROM event_standard_by_season WHERE category='DM-L'")
```

## View catalog
- **Best times / ranking:** `personal_best`, `season_best`, `event_leaderboard`
- **Progression:** `swimmer_progression`, `biggest_improvers`, `cross_era_best`
- **Aggregates:** `club_leaderboard`, `age_group_ranking`, `meet_summary`
- **Pacing:** `pacing`
- **Field evolution:** `event_standard_by_season`, `final_cutline_by_season`,
  `cutline_at(n)` (cut-line for an arbitrary final size), `results_by_category`,
  `prelim_ranked`

Base views: `results` (1 row per result, with `age`/`phase`/`is_relay`/`is_dq`)
and `individual_results` (real individual swims only).

## Notes
- New meets are queryable the moment they are curated — no refresh step.
- `category` (DM-L, DMJ-L, …) is meet-level; a meet in two categories pools into
  both in the field-evolution views.
```

- [ ] **Step 2: Run the full analytics + CLI suite**

Run: `.venv/bin/python -m pytest tests/test_analytics_*.py tests/test_cli_query.py -v`
Expected: PASS (all analytics + query tests).

- [ ] **Step 3: Run the entire repo suite to confirm no regressions**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all tests pass (the existing ingestion/curate suites plus the new analytics tests).

- [ ] **Step 4: Smoke-test against real S3 (manual, optional but recommended)**

Run:
```bash
cd st-scrape
AWS_PROFILE=swimtrends swimtrends query --sql "SELECT count(*) FROM cur_obt"
AWS_PROFILE=swimtrends swimtrends query --sql \
  "SELECT category, season, cutline_time FROM final_cutline_by_season \
   WHERE distance=200 AND stroke='Breast' AND gender='M' ORDER BY season"
```
Expected: a non-zero `cur_obt` count, and cut-line rows for any seasons present. (Data depth grows as more meets are curated.)

- [ ] **Step 5: Commit**

```bash
git add docs/analytics.md
git commit -m "docs: add analytics usage guide

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review (completed)

**Spec coverage:**
- `analytics/` package + source-binding views → Tasks 1, 7. ✓
- Base hygiene views → Task 1. ✓
- Starter catalog (best-times, rankings, progression, club/age/meet, pacing) → Tasks 2–5. ✓
- Field-evolution (`event_standard_by_season`, `final_cutline_by_season`, category via meet qualifier) → Task 6. ✓
- `swimtrends query` CLI + notebook bootstrap → Task 8, docs Task 9. ✓
- In-memory fixture testing, no AWS → Task 1 fixtures, used throughout. ✓
- Read-only, no CDK/AWS resources → nothing in the plan creates infrastructure. ✓
- Out-of-scope items (Athena, dashboards, auto-discovery, CURATOR_FUNCTION) → not implemented. ✓

**Placeholder scan:** No TBD/TODO; every code/test/SQL step is complete and runnable.

**Type/name consistency:** View names, columns (`points_rank`, `heat_rank`, `cutline_centiseconds`, `improvement_centiseconds`, `back_half_delta_cs`, `age_group_rank`), the `cur_obt`/`cur_dim_meet`/`cur_fact_split` binding names, and `loader.create_views/bind_s3/assemble_sql/connect` are used identically across tasks and tests.

**Known design choices baked in:** `hive_partitioning = false` (avoids the season/course duplicate-column clash); category unnest isolated to `results_by_category` (avoids double-counting in aggregates); `event_leaderboard`/`cutline_at(n)` parameterize N instead of hardcoding.
