# Web App Data Build Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python job that turns the curated analytics data into the static JSON files the web SPA fetches (Category → Meet → Race + season comparisons).

**Architecture:** A new `st-scrape/webbuild/` package queries a DuckDB connection that already has the analytics views bound (via `analytics.loader`), shapes the results into plain dicts, and writes them as JSON under an output directory mirroring the URL layout. It reuses the existing views verbatim — **no new analytics math**. Tested against the in-memory curated fixture (no S3); run in prod against the S3-bound connection.

**Tech Stack:** Python 3.12, DuckDB, the existing `st-scrape/analytics` view catalog. Stdlib `json`/`pathlib` only — no new dependencies.

## Global Constraints

- Python 3.12; app venv `st-scrape/.venv`.
- Reuse `analytics.loader.create_views` + the SQL views in `st-scrape/analytics/views/`. Do **not** add or duplicate analytics logic in Python; if a fact needs SQL not yet in a view, compute it inline in a `webbuild` query against the existing views — never edit the shared views for web-only needs.
- All JSON written UTF-8 with `ensure_ascii=False` (Danish `ø/å/æ` must survive) and `sort_keys=True`, trailing newline.
- A "race" = an **event within a meet**: the tuple `(gender, distance, stroke, course)`. Its URL key is the slug `f"{gender}-{distance}-{stroke}-{course}"` (e.g. `M-100-Fri-LCM`).
- Category scoping: meet/race **facts** are computed from `results` by `meet_id` (category-independent). **Season-comparison** arrays are category-scoped (from the `*_by_category` / `*_by_season` views). A meet appears under every category in its `dim_meet.category[]`.
- Season comparison emits up to the **5 most recent seasons** (inclusive of the meet's season); the frontend chooses how many (3–5) to show.
- Output layout (paths relative to the build's `--out` dir):
  ```
  index.json
  <category>/meets.json
  <category>/<meet_id>/meet.json
  <category>/<meet_id>/races.json
  <category>/<meet_id>/<race_key>.json
  ```
- Tests build the curated fixture with `tests/analytics_fixtures.build_curated` + `analytics.loader.create_views`, then call `webbuild` functions against that connection. No S3, no network.

---

## File Structure

- Create `st-scrape/webbuild/__init__.py` — package marker + public exports.
- Create `st-scrape/webbuild/shape.py` — pure helpers (race_key slug, JSON write, row→dict). One responsibility: shaping/IO.
- Create `st-scrape/webbuild/queries.py` — one function per JSON payload, each takes `con` and returns a dict/list. One responsibility: data.
- Create `st-scrape/webbuild/build.py` — orchestrator + `__main__` CLI (`python -m webbuild --out DIR [--s3]`).
- Create `st-scrape/tests/test_webbuild.py` — all tests for this plan.
- Create `st-scrape/tests/webbuild_fixtures.py` — one shared curated fixture (a small DM-L meet across 2 seasons) used by every test.

---

## Task 1: Shared test fixture + shape helpers

**Files:**
- Create: `st-scrape/webbuild/__init__.py`
- Create: `st-scrape/webbuild/shape.py`
- Create: `st-scrape/tests/webbuild_fixtures.py`
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Produces: `shape.race_key(gender, distance, stroke, course) -> str`; `shape.write_json(path: Path, data) -> None`; `webbuild_fixtures.curated_con() -> duckdb.DuckDBPyConnection` (a connection with `cur_*` tables + all analytics views, holding a 2-season DM-L meet dataset).

- [ ] **Step 1: Write the failing test**

```python
# st-scrape/tests/test_webbuild.py
import json
from pathlib import Path

from webbuild import shape
from tests.webbuild_fixtures import curated_con


def test_race_key_slug():
    assert shape.race_key("M", 100, "Fri", "LCM") == "M-100-Fri-LCM"


def test_write_json_roundtrip_keeps_danish(tmp_path: Path):
    p = tmp_path / "sub" / "x.json"
    shape.write_json(p, {"club": "Svømmeklubben Åræø"})
    text = p.read_text(encoding="utf-8")
    assert "Åræø" in text            # not \u-escaped
    assert json.loads(text)["club"] == "Svømmeklubben Åræø"


def test_fixture_has_views_and_two_seasons():
    con = curated_con()
    seasons = [r[0] for r in con.execute(
        "SELECT DISTINCT season FROM results_by_category "
        "WHERE category='DM-L' ORDER BY season").fetchall()]
    assert seasons == [2025, 2026]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'webbuild'`.

- [ ] **Step 3: Write minimal implementation**

```python
# st-scrape/webbuild/__init__.py
"""Build static JSON for the Swimtrends web app from the curated analytics views."""
```

```python
# st-scrape/webbuild/shape.py
"""Pure shaping + IO helpers for the web JSON build."""
import json
from pathlib import Path


def race_key(gender, distance, stroke, course) -> str:
    """URL key for an event within a meet, e.g. M-100-Fri-LCM."""
    return f"{gender}-{distance}-{stroke}-{course}"


def write_json(path: Path, data) -> None:
    """Write UTF-8 JSON, Danish chars intact, deterministic ordering."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write("\n")
```

```python
# st-scrape/tests/webbuild_fixtures.py
"""One curated fixture for webbuild tests: a DM-L meet in 2025 and 2026.

Two events (M 100 Fri LCM, F 200 Ryg LCM), each with heats + final rows so
podium, cut-line and heats->final facts are all exercised. Rows are minimal but
schema-complete for the views.
"""
import duckdb

from analytics.loader import create_views
from tests.analytics_fixtures import build_curated


def _obt_row(**kw):
    base = dict(
        result_id=None, race_id=None, meet_id=None, rank=None, name=None,
        swimmer_id=None, nationality="DEN", club=None, birth_year=2005,
        completed_time=None, completed_centiseconds=None, points=500,
        points_fixed=500, season=None, course="LCM", meet_name=None, venue="Aarhus",
        meet_date=None, number=1, race_name=None, distance=None, stroke=None,
        gender=None, relay_count=1, type=None, class="open",
    )
    base.update(kw)
    return base


def _event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
           finalists):
    """finalists: list of (swimmer_id, name, club, final_cs). Heats mirror them
    plus one extra swimmer so an 8th-place cut-line exists when >=8."""
    rows = []
    rid = 0
    # heats: everyone + a filler field so entrants can reach 8
    field = finalists + [(f"h{i}", f"Heat Swimmer {i}", "HeatKlub", 6000 + i * 30)
                         for i in range(1, 9)]
    for i, (sid, name, club, cs) in enumerate(sorted(field, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Heats"))
    # final: the finalists only, faster times, ranked
    for i, (sid, name, club, cs) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        fcs = cs - 50
        rows.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club,
            completed_time=f"{fcs//6000}:{(fcs%6000)//100:02d}.{fcs%100:02d}",
            completed_centiseconds=fcs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Final"))
    return rows


def curated_con() -> duckdb.DuckDBPyConnection:
    obt, meets = [], []
    for season, mid, mdate in [(2025, "M2025", "2025-04-10"),
                               (2026, "M2026", "2026-04-10")]:
        name = f"Danish Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        obt += _event(mid, name, season, mdate, "M", 100, "Fri",
                      [("s1", "Anna Berg", "AGF", 5200),
                       ("s2", "Bo Dahl", "SIGMA", 5250),
                       ("s3", "Cara Elg", "AGF", 5300)])
        obt += _event(mid, name, season, mdate, "F", 200, "Ryg",
                      [("s4", "Dina Fog", "SIGMA", 13000),
                       ("s5", "Eva Gru", "AGF", 13100),
                       ("s6", "Fia Hald", "VEST", 13200)])
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/__init__.py st-scrape/webbuild/shape.py \
        st-scrape/tests/webbuild_fixtures.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): shape helpers + curated test fixture"
```

---

## Task 2: index.json — categories + seasons

**Files:**
- Create: `st-scrape/webbuild/queries.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Consumes: `curated_con()` from Task 1.
- Produces: `queries.build_index(con) -> dict` with shape
  `{"categories": [{"code": str, "seasons": [int, ...]}], "attribution": "Data fra svømmetider.dk"}`.

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
from webbuild import queries


def test_build_index_lists_category_and_seasons():
    idx = queries.build_index(curated_con())
    assert idx["attribution"] == "Data fra svømmetider.dk"
    dm_l = [c for c in idx["categories"] if c["code"] == "DM-L"][0]
    assert dm_l["seasons"] == [2026, 2025]      # newest first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_index_lists_category_and_seasons -q`
Expected: FAIL — `AttributeError: module 'webbuild.queries' has no attribute 'build_index'` (or ImportError).

- [ ] **Step 3: Write minimal implementation**

```python
# st-scrape/webbuild/queries.py
"""One function per JSON payload. Each takes a bound DuckDB connection."""

ATTRIBUTION = "Data fra svømmetider.dk"


def build_index(con) -> dict:
    rows = con.execute(
        "SELECT category, list(DISTINCT season ORDER BY season DESC) AS seasons "
        "FROM results_by_category GROUP BY category ORDER BY category"
    ).fetchall()
    return {
        "attribution": ATTRIBUTION,
        "categories": [{"code": cat, "seasons": seasons} for cat, seasons in rows],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_index_lists_category_and_seasons -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): index.json (categories + seasons)"
```

---

## Task 3: meets.json — meet list per category

**Files:**
- Modify: `st-scrape/webbuild/queries.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Produces: `queries.build_meets(con, category: str) -> dict` with shape
  `{"category": str, "meets": [{"meet_id", "meet_name", "meet_date", "season", "entrants", "events", "clubs"}]}` — newest season first.

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
def test_build_meets_lists_meets_newest_first():
    out = queries.build_meets(curated_con(), "DM-L")
    assert out["category"] == "DM-L"
    seasons = [m["season"] for m in out["meets"]]
    assert seasons == [2026, 2025]
    m = out["meets"][0]
    assert m["meet_id"] == "M2026"
    assert m["events"] == 2                 # 100 Fri + 200 Ryg
    assert m["entrants"] == 22              # 11 distinct swimmers/event x 2
    assert m["clubs"] >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_meets_lists_meets_newest_first -q`
Expected: FAIL — `AttributeError: ... has no attribute 'build_meets'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to st-scrape/webbuild/queries.py
def build_meets(con, category: str) -> dict:
    rows = con.execute(
        """
        SELECT meet_id, any_value(meet_name) AS meet_name,
               any_value(meet_date) AS meet_date, any_value(season) AS season,
               count(DISTINCT swimmer_id) AS entrants,
               count(DISTINCT (gender, distance, stroke, course)) AS events,
               count(DISTINCT club) AS clubs
        FROM results_by_category
        WHERE category = ?
        GROUP BY meet_id
        ORDER BY season DESC, meet_date DESC
        """,
        [category],
    ).fetchall()
    cols = ["meet_id", "meet_name", "meet_date", "season", "entrants", "events", "clubs"]
    return {"category": category,
            "meets": [dict(zip(cols, r)) for r in rows]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_meets_lists_meets_newest_first -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): meets.json per category"
```

---

## Task 4: meet.json — meet facts + season comparison

**Files:**
- Modify: `st-scrape/webbuild/queries.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Produces: `queries.build_meet(con, category: str, meet_id: str) -> dict` with shape
  ```
  {"category", "meet_id", "meet_name", "meet_date", "season",
   "facts": {"entrants","swims","events","clubs","juniors","median_points","top_points"},
   "season_comparison": [ {"season","entrants","events","clubs","median_points","top_points"} ]}
  ```
  `season_comparison` = up to 5 most recent seasons of this category (this meet's season inclusive), newest first.

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
def test_build_meet_facts_and_comparison():
    out = queries.build_meet(curated_con(), "DM-L", "M2026")
    assert out["meet_id"] == "M2026"
    f = out["facts"]
    assert f["events"] == 2
    assert f["entrants"] == 22
    assert f["swims"] > 0
    assert f["top_points"] >= f["median_points"]
    comp_seasons = [c["season"] for c in out["season_comparison"]]
    assert comp_seasons == [2026, 2025]        # <=5, newest first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_meet_facts_and_comparison -q`
Expected: FAIL — no attribute `build_meet`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to st-scrape/webbuild/queries.py
_MEET_FACTS_SQL = """
    SELECT count(*) AS swims,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           count(DISTINCT swimmer_id) FILTER (WHERE is_junior) AS juniors,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM results_by_category
    WHERE category = ? AND meet_id = ?
"""

_MEET_COMPARE_SQL = """
    SELECT season,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM results_by_category
    WHERE category = ? AND season <= ?
    GROUP BY season
    ORDER BY season DESC
    LIMIT 5
"""


def build_meet(con, category: str, meet_id: str) -> dict:
    head = con.execute(
        "SELECT any_value(meet_name), any_value(meet_date), any_value(season) "
        "FROM results_by_category WHERE category = ? AND meet_id = ?",
        [category, meet_id],
    ).fetchone()
    fact_cols = ["swims", "entrants", "events", "clubs", "juniors",
                 "median_points", "top_points"]
    facts = dict(zip(fact_cols, con.execute(
        _MEET_FACTS_SQL, [category, meet_id]).fetchone()))
    comp_cols = ["season", "entrants", "events", "clubs", "median_points", "top_points"]
    comp = [dict(zip(comp_cols, r)) for r in con.execute(
        _MEET_COMPARE_SQL, [category, head[2]]).fetchall()]
    return {"category": category, "meet_id": meet_id, "meet_name": head[0],
            "meet_date": head[1], "season": head[2],
            "facts": facts, "season_comparison": comp}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_meet_facts_and_comparison -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): meet.json facts + season comparison"
```

---

## Task 5: races.json — event list in a meet

**Files:**
- Modify: `st-scrape/webbuild/queries.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Consumes: `shape.race_key`.
- Produces: `queries.build_races(con, category: str, meet_id: str) -> dict` with shape
  `{"category","meet_id","races":[{"race_key","label","gender","distance","stroke","course","contestants","winner_name","winning_time"}]}`.

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
def test_build_races_lists_events_with_winner():
    out = queries.build_races(curated_con(), "DM-L", "M2026")
    keys = {r["race_key"] for r in out["races"]}
    assert "M-100-Fri-LCM" in keys
    fri = [r for r in out["races"] if r["race_key"] == "M-100-Fri-LCM"][0]
    assert fri["label"] == "M 100m Fri (LCM)"
    assert fri["contestants"] == 11         # 3 finalists + 8 heat fillers
    assert fri["winner_name"] == "Anna Berg"   # fastest final
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_races_lists_events_with_winner -q`
Expected: FAIL — no attribute `build_races`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to st-scrape/webbuild/queries.py
from webbuild.shape import race_key

_RACES_SQL = """
    SELECT gender, distance, stroke, course,
           count(DISTINCT swimmer_id) AS contestants,
           arg_min(name, completed_centiseconds)
               FILTER (WHERE phase IN ('final','timed_final')) AS winner_name,
           min(completed_time)
               FILTER (WHERE phase IN ('final','timed_final')) AS winning_time
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND NOT is_dq
    GROUP BY gender, distance, stroke, course
    ORDER BY gender, distance, stroke, course
"""


def build_races(con, category: str, meet_id: str) -> dict:
    rows = con.execute(_RACES_SQL, [category, meet_id]).fetchall()
    races = []
    for gender, distance, stroke, course, contestants, winner, wtime in rows:
        races.append({
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke} ({course})",
            "gender": gender, "distance": distance, "stroke": stroke,
            "course": course, "contestants": contestants,
            "winner_name": winner, "winning_time": wtime,
        })
    return {"category": category, "meet_id": meet_id, "races": races}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_races_lists_events_with_winner -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): races.json event list"
```

---

## Task 6: race JSON — full race key facts + season comparison

**Files:**
- Modify: `st-scrape/webbuild/queries.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Produces: `queries.build_race(con, category, meet_id, gender, distance, stroke, course) -> dict`:
  ```
  {"category","meet_id","race_key","label","facts","podium","season_comparison"}
  facts: {"contestants","dsq","winning_time","winner_points","cutline_time","cutline_centiseconds",
          "spread_1_8_cs","spread_1_last_cs","median_cs","median_points","juniors"}
  podium: [{"rank","name","club","time","points"}]  (finals rank 1..3)
  season_comparison: [{"season","best_cs","median_cs","top8_avg_cs","cutline_cs","entrants"}]  # <=5 newest first
  ```

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
def test_build_race_facts_podium_and_comparison():
    out = queries.build_race(curated_con(), "DM-L", "M2026", "M", 100, "Fri", "LCM")
    assert out["race_key"] == "M-100-Fri-LCM"
    f = out["facts"]
    assert f["contestants"] == 11
    assert f["cutline_centiseconds"] is not None   # 8th heat swim exists
    assert f["winning_time"] is not None
    podium = out["podium"]
    assert [p["rank"] for p in podium] == [1, 2, 3]
    assert podium[0]["name"] == "Anna Berg"
    comp_seasons = [c["season"] for c in out["season_comparison"]]
    assert comp_seasons == [2026, 2025]
    assert out["season_comparison"][0]["best_cs"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_race_facts_podium_and_comparison -q`
Expected: FAIL — no attribute `build_race`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to st-scrape/webbuild/queries.py
_RACE_FACTS_SQL = """
    WITH e AS (
        SELECT * FROM results_by_category
        WHERE category = ? AND meet_id = ?
          AND gender = ? AND distance = ? AND stroke = ? AND course = ?
    ),
    fin AS (SELECT * FROM e WHERE phase IN ('final','timed_final') AND NOT is_dq),
    heats AS (
        SELECT completed_centiseconds,
               row_number() OVER (ORDER BY completed_centiseconds) AS hr
        FROM e WHERE phase = 'heats' AND NOT is_dq
    )
    SELECT
        (SELECT count(DISTINCT swimmer_id) FROM e WHERE NOT is_dq) AS contestants,
        (SELECT count(*) FROM e WHERE is_dq) AS dsq,
        (SELECT min(completed_time) FROM fin) AS winning_time,
        (SELECT max(points) FROM fin) AS winner_points,
        (SELECT completed_centiseconds FROM heats WHERE hr = 8) AS cutline_cs,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds)
         FROM (SELECT completed_centiseconds FROM heats WHERE hr <= 8)) AS spread_1_8_cs,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds) FROM e WHERE NOT is_dq) AS spread_1_last_cs,
        (SELECT CAST(quantile_cont(completed_centiseconds, 0.5) AS BIGINT) FROM e WHERE NOT is_dq) AS median_cs,
        (SELECT CAST(quantile_cont(points, 0.5) AS BIGINT) FROM e WHERE NOT is_dq) AS median_points,
        (SELECT count(DISTINCT swimmer_id) FROM e WHERE is_junior) AS juniors
"""

_PODIUM_SQL = """
    SELECT rank, name, club, completed_time AS time, points
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND gender = ? AND distance = ?
      AND stroke = ? AND course = ? AND phase IN ('final','timed_final')
      AND rank IN (1, 2, 3)
    ORDER BY rank
"""

_RACE_COMPARE_SQL = """
    SELECT s.season, s.best_cs, CAST(s.median_cs AS BIGINT) AS median_cs,
           CAST(s.top8_avg_cs AS BIGINT) AS top8_avg_cs,
           c.cutline_centiseconds AS cutline_cs, s.swims AS entrants
    FROM event_standard_by_season s
    LEFT JOIN final_cutline_by_season c USING (category, season, course, gender, distance, stroke)
    WHERE s.category = ? AND s.gender = ? AND s.distance = ? AND s.stroke = ?
      AND s.course = ? AND s.season <= ?
    ORDER BY s.season DESC
    LIMIT 5
"""


def build_race(con, category, meet_id, gender, distance, stroke, course) -> dict:
    args = [category, meet_id, gender, distance, stroke, course]
    fact_cols = ["contestants", "dsq", "winning_time", "winner_points",
                 "cutline_centiseconds", "spread_1_8_cs", "spread_1_last_cs",
                 "median_cs", "median_points", "juniors"]
    facts = dict(zip(fact_cols, con.execute(_RACE_FACTS_SQL, args).fetchone()))
    facts["cutline_time"] = None  # centiseconds is the comparable value; label formatted client-side
    season = con.execute(
        "SELECT any_value(season) FROM results_by_category WHERE meet_id = ?",
        [meet_id]).fetchone()[0]
    podium = [dict(zip(["rank", "name", "club", "time", "points"], r))
              for r in con.execute(_PODIUM_SQL, args).fetchall()]
    comp_cols = ["season", "best_cs", "median_cs", "top8_avg_cs", "cutline_cs", "entrants"]
    comp = [dict(zip(comp_cols, r)) for r in con.execute(
        _RACE_COMPARE_SQL,
        [category, gender, distance, stroke, course, season]).fetchall()]
    return {"category": category, "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke} ({course})",
            "facts": facts, "podium": podium, "season_comparison": comp}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_race_facts_podium_and_comparison -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): race JSON facts, podium, season comparison"
```

---

## Task 7: build.py orchestrator + CLI

**Files:**
- Create: `st-scrape/webbuild/build.py`
- Test: `st-scrape/tests/test_webbuild.py` (append)

**Interfaces:**
- Consumes: all `queries.build_*` + `shape.write_json`.
- Produces: `build.build_all(con, out: Path) -> list[Path]` (writes every JSON file, returns the paths written); `python -m webbuild --out DIR [--s3]` CLI (default source = `analytics.loader.connect()`; `--s3` is the same thing, made explicit).

- [ ] **Step 1: Write the failing test**

```python
# append to st-scrape/tests/test_webbuild.py
from webbuild import build


def test_build_all_writes_full_tree(tmp_path: Path):
    written = build.build_all(curated_con(), tmp_path)
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "DM-L" / "meets.json").exists()
    assert (tmp_path / "DM-L" / "M2026" / "meet.json").exists()
    assert (tmp_path / "DM-L" / "M2026" / "races.json").exists()
    assert (tmp_path / "DM-L" / "M2026" / "M-100-Fri-LCM.json").exists()
    # every returned path was actually written
    assert all(p.exists() for p in written)
    # spot-check content wiring
    meet = json.loads((tmp_path / "DM-L" / "M2026" / "meet.json").read_text("utf-8"))
    assert meet["facts"]["events"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_all_writes_full_tree -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'webbuild.build'`.

- [ ] **Step 3: Write minimal implementation**

```python
# st-scrape/webbuild/build.py
"""Orchestrate the full JSON build and expose a CLI."""
import argparse
from pathlib import Path

from webbuild import queries
from webbuild.shape import race_key, write_json


def build_all(con, out: Path) -> list[Path]:
    out = Path(out)
    written = []

    def emit(rel, data):
        p = out / rel
        write_json(p, data)
        written.append(p)

    index = queries.build_index(con)
    emit("index.json", index)
    for cat in index["categories"]:
        code = cat["code"]
        meets = queries.build_meets(con, code)
        emit(f"{code}/meets.json", meets)
        for m in meets["meets"]:
            mid = m["meet_id"]
            emit(f"{code}/{mid}/meet.json", queries.build_meet(con, code, mid))
            races = queries.build_races(con, code, mid)
            emit(f"{code}/{mid}/races.json", races)
            for r in races["races"]:
                emit(f"{code}/{mid}/{r['race_key']}.json",
                     queries.build_race(con, code, mid, r["gender"],
                                        r["distance"], r["stroke"], r["course"]))
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build web JSON from the curated zone.")
    ap.add_argument("--out", required=True, type=Path, help="output directory")
    ap.add_argument("--s3", action="store_true",
                    help="(default) read the curated zone from S3 via analytics.loader")
    args = ap.parse_args(argv)
    from analytics.loader import connect
    con = connect()
    paths = build_all(con, args.out)
    print(f"wrote {len(paths)} files to {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -q`
Expected: PASS (all webbuild tests green).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/build.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): build_all orchestrator + CLI"
```

---

## Task 8: Full-suite check + docs pointer

**Files:**
- Modify: `docs/analytics.md` (add a short "Web JSON build" subsection)

- [ ] **Step 1: Run the whole app test suite**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: PASS — the pre-existing suite plus the new `test_webbuild.py` tests, no regressions.

- [ ] **Step 2: Document the build command**

Add to `docs/analytics.md`:

```markdown
## Web JSON build
Generate the static JSON the web app serves (reads the curated zone from S3):

    cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data

Output mirrors the app's URL layout (index.json, <category>/meets.json,
<category>/<meet_id>/{meet,races}.json, <category>/<meet_id>/<race_key>.json).
```

- [ ] **Step 3: Commit**

```bash
git add docs/analytics.md
git commit -m "docs: document the web JSON build command"
```

---

## Self-Review

**Spec coverage** (checked against `2026-07-19-web-app-mvp-design.md`):
- JSON layout (index/meets/meet/races/race) → Tasks 2–7. ✔
- Meet key facts (entrants, events, clubs, juniors, median/top points) → Task 4. ✔
- Race key facts (contestants, DSQ, podium, winning time, cutline, spread, median, juniors) → Task 6. ✔
- Season comparison at meet + race level (≤5 newest) → Tasks 4, 6. ✔
- Reuse existing views, no new analytics math → all queries bind to existing views. ✔
- Danish characters preserved; attribution string → Task 1 (`write_json`), Task 2 (index). ✔
- `dataClient`-friendly layout / seam for future API → paths mirror resource shape (Global Constraints). ✔
- Heats→final drop (spec race table): **partially deferred** — `spread_1_8_cs` and cutline are covered; the explicit qualifying-vs-final delta and split/negative-split facts are **not** in this plan. Rationale: they need `pacing`/split fixture rows and add scope; captured as a follow-up in Plan 2's data needs. *(If required in the MVP, add a Task 6b mirroring Task 6 using the `pacing` view.)*

**Placeholder scan:** none — every step has runnable code/commands. `facts["cutline_time"]=None` is intentional (centiseconds is the comparable value; the client formats the label), documented inline.

**Type consistency:** `race_key(gender, distance, stroke, course)` used identically in Tasks 1, 5, 6, 7. `build_*` signatures match their Interfaces blocks and their call sites in `build_all`. Column-name lists match the SELECT orders.

**Open item for reviewer:** confirm whether heats→final drop and split facts are MVP-required; if so add Task 6b before starting Plan 2.
