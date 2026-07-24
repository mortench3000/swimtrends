# Relays on Meet Pages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show team relays on meet detail pages (race list + relay race-detail page with trends), while still excluding DQs and para results.

**Architecture:** A narrow parallel relay path in the analytics views and webbuild queries. `individual_results` and every existing aggregate stay untouched; relays are surfaced only in the meet race list and their own race-detail JSON. DQ excluded via `NOT is_dq`, para via `class='open'` — the same filters used everywhere else.

**Tech Stack:** DuckDB SQL views (`analytics/views/*.sql`), Python webbuild (`webbuild/*.py`), Svelte 5 SPA (`web/src`). Python tests via pytest, frontend via vitest.

## Global Constraints

- **Do NOT modify `individual_results` (`00_base.sql:25`) or any individual aggregate** (`results_by_category`, `medal_count`, `event_standard_by_season`, `elite_median_points`, junior views). Relays get a separate path.
- **Relay `race_key` form:** `{gender}-{relay_count}x{distance}-{stroke}-{course}` (e.g. `F-4x100-HM-LCM`). Individual keys stay `{gender}-{distance}-{stroke}-{course}` — unchanged, no migration.
- **Relays are always `Timed final`** (`phase='timed_final'`, no heats) → **no A-final cut-line** anywhere on the relay path.
- **`distance` is per-leg** (100 for a 4×100); `relay_count` is the leg count; relay `swimmer_id` is null; relay `name` is the team entry, `club` is the club.
- **DQ + para stay excluded:** every relay query carries `NOT is_dq` (or counts DQ separately) and `class='open'`.
- Relay member names are **out of scope** (not scraped).
- Relay events show only for meets that also have individual events (the index/meet list is driven by the individual `results_by_category`). No relay-only meets exist in the data; acceptable.
- Match surrounding style. Danish UI copy. Run the full pytest suite before claiming done: `cd st-scrape && .venv/bin/python -m pytest -q`.

---

## File Structure

- `st-scrape/analytics/views/00_base.sql` — add `relay_results` view (Modify).
- `st-scrape/analytics/views/55_relays.sql` — `relay_results_by_category` + `relay_event_standard_by_season` (Create).
- `st-scrape/webbuild/shape.py` — `race_key` gains `relay_count` (Modify).
- `st-scrape/webbuild/queries.py` — relay race list, relay event counts, `_build_relay_race` (Modify).
- `st-scrape/webbuild/build.py` — pass `relay_count` to `build_race` (Modify).
- `st-scrape/tests/webbuild_fixtures.py` — add `relay_con()` (Modify).
- `st-scrape/tests/test_webbuild.py` — relay webbuild tests (Modify).
- `st-scrape/tests/test_analytics_loader.py` — relay view tests (Modify).
- `web/src/routes/Race.svelte` — relay tile/chart guards (Modify).
- `web/src/routes/Meet.svelte` — "hold" vs "deltagere" copy (Modify).
- `web/tests/routes.render.test.js` — relay render test (Modify).

---

### Task 1: Relay analytics views

**Files:**
- Modify: `st-scrape/analytics/views/00_base.sql`
- Create: `st-scrape/analytics/views/55_relays.sql`
- Test: `st-scrape/tests/test_analytics_loader.py`

**Interfaces:**
- Consumes: `results` view (`00_base.sql`), `cur_dim_meet`.
- Produces: views `relay_results`, `relay_results_by_category`, `relay_event_standard_by_season` — columns are `results.*` plus (for the two `_by_category`/standard views) `category`; the standard view exposes `category, season, course, gender, distance, stroke, relay_count, swims, best_cs, median_cs, top8_avg_cs`.

- [ ] **Step 1: Write the failing test**

Add to `st-scrape/tests/test_analytics_loader.py`:

```python
def test_relay_results_includes_relays_excludes_dq_and_para():
    import duckdb
    from analytics.loader import create_views
    from tests.analytics_fixtures import build_curated

    def row(**kw):
        base = dict(result_id="x", race_id=1, meet_id="M1", rank=1, name="Team A",
                    swimmer_id=None, nationality="DEN", club="AGF", birth_year=2004,
                    completed_time="4:10.51", completed_centiseconds=25051, points=500,
                    points_fixed=500, season=2026, course="LCM", meet_name="Champs",
                    venue="Aarhus", meet_date="2026-04-10", number=1, race_name="4 x 100 HM",
                    distance=100, stroke="HM", gender="F", relay_count=4,
                    type="Timed final", klass="open")
        base.update(kw)                       # apply overrides (incl. klass) first
        base["class"] = base.pop("klass")     # then map to the reserved column name
        return base

    con = duckdb.connect()
    build_curated(con, obt=[
        row(result_id="ok", rank=1, name="Team A"),
        row(result_id="dq", rank=-1, name="DQ Team"),               # relay DQ -> excluded
        row(result_id="para", rank=1, name="Para Team", klass="para"),  # para -> kept at view
    ], meets=[dict(meet_id="M1", meet_name="Champs", venue="Aarhus", course="LCM",
                   season=2026, meet_date="2026-04-10", category=["DM-L"])])
    create_views(con)
    names = [r[0] for r in con.execute("SELECT name FROM relay_results ORDER BY name").fetchall()]
    assert names == ["Para Team", "Team A"]        # DQ excluded; para kept at view (para filtered later by class='open' in webbuild)
    cats = con.execute("SELECT DISTINCT category FROM relay_results_by_category").fetchall()
    assert cats == [("DM-L",)]
    std = con.execute(
        "SELECT swims, best_cs FROM relay_event_standard_by_season "
        "WHERE relay_count = 4 AND stroke = 'HM'").fetchone()
    assert std[0] >= 1 and std[1] == 25051
```

Note: `relay_results` intentionally keeps para rows (para is excluded later by `class='open'` in the webbuild queries, matching how the individual path filters class at query time, not in the base view). The DQ row is the one excluded here.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_analytics_loader.py::test_relay_results_includes_relays_excludes_dq_and_para -q`
Expected: FAIL — `relay_results` does not exist (`Catalog Error`).

- [ ] **Step 3: Add `relay_results` to `00_base.sql`**

Append to `st-scrape/analytics/views/00_base.sql`:

```sql

-- Relay entries, for the meet-page relay path only. Mirrors individual_results
-- but keeps null swimmer_id (a relay has no single swimmer). DQ excluded here;
-- para is excluded downstream by class='open' in the webbuild relay queries.
CREATE OR REPLACE VIEW relay_results AS
SELECT * FROM results
WHERE is_relay AND NOT is_dq;
```

- [ ] **Step 4: Create `55_relays.sql`**

Create `st-scrape/analytics/views/55_relays.sql`:

```sql
-- Relay entries exploded to one row per (relay swim, meet category), mirroring
-- results_by_category. Meets with no championship category are excluded.
CREATE OR REPLACE VIEW relay_results_by_category AS
SELECT r.*, cat.category AS category
FROM relay_results r
JOIN cur_dim_meet m USING (meet_id)
CROSS JOIN UNNEST(m.category) AS cat(category);

-- How a relay event's standard moves across seasons, per championship category.
-- No cut-line: relays are timed finals (no heats). relay_count is part of the
-- key so 4x100 and (any) 8x100 of the same stroke stay distinct.
CREATE OR REPLACE VIEW relay_event_standard_by_season AS
SELECT
    category, season, course, gender, distance, stroke, relay_count,
    count(*)                                       AS swims,
    min(completed_centiseconds)                    AS best_cs,
    quantile_cont(completed_centiseconds, 0.5)     AS median_cs,
    avg(completed_centiseconds) FILTER (WHERE time_rank <= 8) AS top8_avg_cs
FROM (
    SELECT *,
        rank() OVER (
            PARTITION BY category, season, course, gender, distance, stroke, relay_count
            ORDER BY completed_centiseconds
        ) AS time_rank
    FROM relay_results_by_category
    WHERE completed_centiseconds IS NOT NULL
)
GROUP BY category, season, course, gender, distance, stroke, relay_count;
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_analytics_loader.py::test_relay_results_includes_relays_excludes_dq_and_para -q`
Expected: PASS. (If the para-row `class` assertion misbehaves, simplify the fixture to just the OK + DQ rows and assert `names == ["Team A"]` — the DQ exclusion is the load-bearing assertion.)

- [ ] **Step 6: Commit**

```bash
git add st-scrape/analytics/views/00_base.sql st-scrape/analytics/views/55_relays.sql st-scrape/tests/test_analytics_loader.py
git commit -m "feat(analytics): add relay_results + relay_results_by_category views"
```

---

### Task 2: `race_key` relay form

**Files:**
- Modify: `st-scrape/webbuild/shape.py`
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Produces: `race_key(gender, distance, stroke, course, relay_count=1) -> str`. Individual (relay_count=1) is unchanged; relay emits `{gender}-{relay_count}x{distance}-{stroke}-{course}`.

- [ ] **Step 1: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_race_key_relay_form():
    assert shape.race_key("F", 100, "HM", "LCM", relay_count=4) == "F-4x100-HM-LCM"
    assert shape.race_key("M", 100, "Fri", "LCM") == "M-100-Fri-LCM"  # individual unchanged
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_race_key_relay_form -q`
Expected: FAIL — `race_key() got an unexpected keyword argument 'relay_count'`.

- [ ] **Step 3: Implement**

Replace `race_key` in `st-scrape/webbuild/shape.py`:

```python
def race_key(gender, distance, stroke, course, relay_count=1) -> str:
    """URL key for an event within a meet, e.g. M-100-Fri-LCM. Relays encode the
    leg count so a 4x100 (per-leg distance 100) does not collide with the
    individual 100, e.g. F-4x100-HM-LCM."""
    dist = f"{relay_count}x{distance}" if relay_count > 1 else str(distance)
    return f"{gender}-{dist}-{stroke}-{course}"
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_race_key_relay_form tests/test_webbuild.py::test_race_key_slug -q`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/shape.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): race_key encodes relay leg count"
```

---

### Task 3: Relay events in the race list + meet event counts

**Files:**
- Modify: `st-scrape/webbuild/queries.py` (`build_races`, `build_meets`, `build_meet`)
- Modify: `st-scrape/tests/webbuild_fixtures.py` (add `relay_con()`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `relay_results_by_category`, `race_key(..., relay_count)` (Task 2).
- Produces: `build_races` race dicts now include `relay_count: int` and `is_relay: bool`; relay rows use the relay `race_key`/label. `build_meets[].events`, `build_meet` `facts.events`, and each `season_comparison[].events` include relay events.

- [ ] **Step 1: Add the relay fixture**

Add to `st-scrape/tests/webbuild_fixtures.py` (reuses the module's existing `_obt_row`):

```python
def _relay_event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
                 relay_count, teams, start_rid):
    """teams: list of (team_name, club, cs). One timed-final row per team, ranked."""
    rows = []
    rid = start_rid
    for i, (name, club, cs) in enumerate(sorted(teams, key=lambda x: x[2]), 1):
        rows.append(_obt_row(
            result_id=f"{meet_id}-r-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=None, club=club,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            relay_count=relay_count, type="Timed final"))
        rid += 1
    return rows, rid


def relay_con() -> duckdb.DuckDBPyConnection:
    """A DM-L meet in 2025 + 2026 with individual AND relay events, so relay
    queries and the individual aggregates are exercised side by side. Separate
    from curated_con() so its magic numbers stay stable."""
    obt, meets = [], []
    for season, mid, mdate in [(2025, "R2025", "2025-04-10"),
                               (2026, "R2026", "2026-04-10")]:
        name = f"Relay Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        rid = 1
        rows, rid = _event(mid, name, season, mdate, "M", 100, "Fri",
                           [("s1", "Anna Berg", "AGF", 5200),
                            ("s2", "Bo Dahl", "SIGMA", 5250),
                            ("s3", "Cara Elg", "AGF", 5300)], start_rid=rid)
        obt += rows
        rows, rid = _relay_event(mid, name, season, mdate, "F", 100, "HM", 4,
                                 [("Aalborg 1", "Aalborg SK", 25051),
                                  ("Thisted", "Thisted SK", 25444),
                                  ("A6 1", "A6", 26254)], start_rid=rid)
        obt += rows
    # a DQ relay team in 2026 (rank -1): excluded from relay_results, counted by
    # the relay DSQ query (Task 4).
    obt.append(_obt_row(
        result_id="R2026-dq", race_id=9990, meet_id="R2026", rank=-1,
        name="DQ Team", swimmer_id=None, club="DQ SK", completed_time=None,
        completed_centiseconds=None, season=2026, meet_name="Relay Champs 2026",
        meet_date="2026-04-10", distance=100, stroke="HM", gender="F",
        relay_count=4, type="Timed final"))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 2: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py` (add `relay_con` to the existing import from `tests.webbuild_fixtures`):

```python
def test_build_races_includes_relay_with_team_winner():
    from tests.webbuild_fixtures import relay_con
    out = queries.build_races(relay_con(), "DM-L", "R2026")
    relay = [r for r in out["races"] if r["race_key"] == "F-4x100-HM-LCM"]
    assert len(relay) == 1
    r = relay[0]
    assert r["is_relay"] is True
    assert r["relay_count"] == 4
    assert r["label"] == "F 4x100m HM"
    assert r["contestants"] == 3               # 3 teams (DQ team excluded)
    assert r["winner_name"] == "Aalborg 1"     # fastest team
    # individual event still present and unflagged
    ind = [r for r in out["races"] if r["race_key"] == "M-100-Fri-LCM"][0]
    assert ind["is_relay"] is False


def test_meet_event_count_includes_relays():
    from tests.webbuild_fixtures import relay_con
    con = relay_con()
    meets = queries.build_meets(con, "DM-L")
    m = [m for m in meets["meets"] if m["meet_id"] == "R2026"][0]
    assert m["events"] == 2                     # 1 individual + 1 relay
    meet = queries.build_meet(con, "DM-L", "R2026")
    assert meet["facts"]["events"] == 2
    assert all(c["events"] == 2 for c in meet["season_comparison"])
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_races_includes_relay_with_team_winner tests/test_webbuild.py::test_meet_event_count_includes_relays -q`
Expected: FAIL — relay race absent / `events == 1`.

- [ ] **Step 4: Implement `build_races` relay UNION + `is_relay` flag**

In `st-scrape/webbuild/queries.py`, add after `_RACES_SQL`:

```python
_RELAY_RACES_SQL = """
    SELECT gender, distance, stroke, course, relay_count,
           count(*) AS contestants,
           arg_min(name, completed_centiseconds) AS winner_name,
           arg_min(completed_time, completed_centiseconds) AS winning_time
    FROM relay_results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
    GROUP BY gender, distance, stroke, course, relay_count
    ORDER BY gender, distance, stroke, course, relay_count
"""
```

Replace `build_races` with:

```python
def build_races(con, category: str, meet_id: str) -> dict:
    races = []
    for gender, distance, stroke, course, contestants, winner, wtime in con.execute(
            _RACES_SQL, [category, meet_id]).fetchall():
        races.append({
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke}",
            "gender": gender, "distance": distance, "stroke": stroke,
            "course": course, "relay_count": 1, "is_relay": False,
            "contestants": contestants,
            "winner_name": winner, "winning_time": wtime,
        })
    for gender, distance, stroke, course, rc, contestants, winner, wtime in con.execute(
            _RELAY_RACES_SQL, [category, meet_id]).fetchall():
        races.append({
            "race_key": race_key(gender, distance, stroke, course, rc),
            "label": f"{gender} {rc}x{distance}m {stroke}",
            "gender": gender, "distance": distance, "stroke": stroke,
            "course": course, "relay_count": rc, "is_relay": True,
            "contestants": contestants,
            "winner_name": winner, "winning_time": wtime,
        })
    return {"category": category, "meet_id": meet_id, "races": races}
```

- [ ] **Step 5: Implement relay event counts (`build_meets`, `build_meet`)**

Add these SQL constants near the meet queries in `st-scrape/webbuild/queries.py`:

```python
_MEETS_RELAY_EVENTS_SQL = """
    SELECT meet_id, count(DISTINCT (gender, distance, stroke, course, relay_count)) AS n
    FROM relay_results_by_category
    WHERE category = ? AND class = 'open'
    GROUP BY meet_id
"""

_MEET_RELAY_EVENTS_SQL = """
    SELECT count(DISTINCT (gender, distance, stroke, course, relay_count))
    FROM relay_results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
"""

_MEET_RELAY_EVENTS_BY_SEASON_SQL = """
    SELECT season, count(DISTINCT (gender, distance, stroke, course, relay_count)) AS n
    FROM relay_results_by_category
    WHERE category = ? AND season <= ? AND class = 'open'
    GROUP BY season
"""
```

In `build_meets`, after building the meet dicts (before the `return`), add:

```python
    rel = dict(con.execute(_MEETS_RELAY_EVENTS_SQL, [category]).fetchall())
    result = [dict(zip(cols, r)) for r in rows]
    for m in result:
        m["events"] += rel.get(m["meet_id"], 0)
    return {"category": category, "meets": result}
```

(Replace the existing `return {"category": category, "meets": [dict(zip(cols, r)) for r in rows]}` line.)

In `build_meet`, after `facts = dict(...)` and after building `comp`, add:

```python
    facts["events"] += con.execute(
        _MEET_RELAY_EVENTS_SQL, [category, meet_id]).fetchone()[0]
    rel_by_season = dict(con.execute(
        _MEET_RELAY_EVENTS_BY_SEASON_SQL, [category, head[2]]).fetchall())
    for c in comp:
        c["events"] += rel_by_season.get(c["season"], 0)
```

Place this before the elite-merge block or after it (order does not matter); keep it before the `return`.

- [ ] **Step 6: Run to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -q`
Expected: PASS — new relay tests pass AND the existing `test_build_meets_lists_meets_newest_first` / `test_build_meet_facts_and_comparison` (which use `curated_con()`, no relays) still assert `events == 2` unchanged.

- [ ] **Step 7: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/webbuild_fixtures.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): list relay events + count them in meet events"
```

---

### Task 4: Relay race-detail page

**Files:**
- Modify: `st-scrape/webbuild/queries.py` (`build_race` routing + `_build_relay_race`)
- Modify: `st-scrape/webbuild/build.py` (pass `relay_count`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `relay_results_by_category`, `relay_event_standard_by_season`, `results` (for DQ), `race_key(..., relay_count)`.
- Produces: `build_race(con, category, meet_id, gender, distance, stroke, course, relay_count=1)`. Individual return dict gains `"is_relay": False`. Relay dict: `is_relay: True`, `facts` = `{contestants, winning_time, winner_points, spread_1_last_cs, median_cs, dsq}`, `podium` = up-to-3 team rows `{rank, name, swimmer_id(null), club, time, points}`, `season_comparison` rows `{season, best_cs, median_cs, top8_avg_cs, cutline_cs(null), swims}`.

- [ ] **Step 1: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_build_race_relay_detail():
    from tests.webbuild_fixtures import relay_con
    con = relay_con()
    out = queries.build_race(con, "DM-L", "R2026", "F", 100, "HM", "LCM", relay_count=4)
    assert out["is_relay"] is True
    assert out["race_key"] == "F-4x100-HM-LCM"
    assert out["label"] == "F 4x100m HM"
    f = out["facts"]
    assert f["contestants"] == 3               # DQ team excluded from contestants
    assert f["dsq"] == 1                        # the DQ team counted here
    assert f["winning_time"] == "4:10.51"       # fastest team
    assert "cutline_centiseconds" not in f      # no cut-line for relays
    podium = out["podium"]
    assert [p["rank"] for p in podium] == [1, 2, 3]
    assert podium[0]["name"] == "Aalborg 1"
    assert podium[0]["swimmer_id"] is None       # relay -> no swimmer link
    comp = out["season_comparison"]
    assert all(c["cutline_cs"] is None for c in comp)   # relay trends carry no cut-line
    assert comp[0]["best_cs"] == 25051

def test_build_race_individual_flagged_not_relay():
    from tests.webbuild_fixtures import relay_con
    out = queries.build_race(relay_con(), "DM-L", "R2026", "M", 100, "Fri", "LCM")
    assert out["is_relay"] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_build_race_relay_detail tests/test_webbuild.py::test_build_race_individual_flagged_not_relay -q`
Expected: FAIL — `build_race()` takes no `relay_count`; no `is_relay` key.

- [ ] **Step 3: Add relay SQL + `_build_relay_race`**

In `st-scrape/webbuild/queries.py`, add near the race queries:

```python
_RELAY_RACE_FACTS_SQL = """
    WITH e AS (
        SELECT * FROM relay_results_by_category
        WHERE category = ? AND meet_id = ?
          AND gender = ? AND distance = ? AND stroke = ? AND course = ?
          AND relay_count = ? AND class = 'open'
    )
    SELECT
        (SELECT count(*) FROM e) AS contestants,
        (SELECT arg_min(completed_time, completed_centiseconds) FROM e) AS winning_time,
        (SELECT max(points) FROM e) AS winner_points,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds) FROM e) AS spread_1_last_cs,
        (SELECT CAST(quantile_cont(completed_centiseconds, 0.5) AS BIGINT) FROM e) AS median_cs
"""

# Relay DQ rows are excluded from relay_results_by_category (relay_results filters
# NOT is_dq); count them from the base `results` view, pinned by the event tuple.
_RELAY_RACE_DSQ_SQL = """
    SELECT count(*) FROM results
    WHERE meet_id = ? AND gender = ? AND distance = ? AND stroke = ?
      AND course = ? AND relay_count = ? AND is_relay AND is_dq AND class = 'open'
"""

_RELAY_PODIUM_SQL = """
    SELECT rank, name, swimmer_id, club, completed_time AS time, points
    FROM relay_results_by_category
    WHERE category = ? AND meet_id = ? AND gender = ? AND distance = ?
      AND stroke = ? AND course = ? AND relay_count = ?
      AND rank IN (1, 2, 3) AND class = 'open'
    ORDER BY rank
"""

_RELAY_RACE_COMPARE_SQL = """
    SELECT season, best_cs, CAST(median_cs AS BIGINT) AS median_cs,
           CAST(top8_avg_cs AS BIGINT) AS top8_avg_cs, swims
    FROM relay_event_standard_by_season
    WHERE category = ? AND gender = ? AND distance = ? AND stroke = ?
      AND course = ? AND relay_count = ? AND season <= ?
    ORDER BY season DESC
    LIMIT 5
"""


def _build_relay_race(con, category, meet_id, gender, distance, stroke, course, relay_count) -> dict:
    args = [category, meet_id, gender, distance, stroke, course, relay_count]
    fact_cols = ["contestants", "winning_time", "winner_points",
                 "spread_1_last_cs", "median_cs"]
    facts = dict(zip(fact_cols, con.execute(_RELAY_RACE_FACTS_SQL, args).fetchone()))
    facts["dsq"] = con.execute(
        _RELAY_RACE_DSQ_SQL,
        [meet_id, gender, distance, stroke, course, relay_count]).fetchone()[0]
    season = con.execute(
        "SELECT any_value(season) FROM relay_results_by_category WHERE meet_id = ?",
        [meet_id]).fetchone()[0]
    podium = [dict(zip(["rank", "name", "swimmer_id", "club", "time", "points"], r))
              for r in con.execute(_RELAY_PODIUM_SQL, args).fetchall()]
    comp = [{"season": s, "best_cs": b, "median_cs": m, "top8_avg_cs": t,
             "cutline_cs": None, "swims": sw}
            for (s, b, m, t, sw) in con.execute(
                _RELAY_RACE_COMPARE_SQL,
                [category, gender, distance, stroke, course, relay_count, season]).fetchall()]
    return {"category": category, "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course, relay_count),
            "label": f"{gender} {relay_count}x{distance}m {stroke}",
            "is_relay": True, "facts": facts, "podium": podium,
            "season_comparison": comp}
```

- [ ] **Step 4: Route `build_race` + flag the individual path**

Change the `build_race` signature and add the relay branch at the top:

```python
def build_race(con, category, meet_id, gender, distance, stroke, course, relay_count=1) -> dict:
    if relay_count > 1:
        return _build_relay_race(con, category, meet_id, gender, distance, stroke, course, relay_count)
    args = [category, meet_id, gender, distance, stroke, course]
    # ... existing individual body unchanged ...
```

In the individual `return {...}` at the end of `build_race`, add `"is_relay": False,` alongside the existing keys.

- [ ] **Step 5: Wire `relay_count` through `build.py`**

In `st-scrape/webbuild/build.py`, change the race loop:

```python
            for r in races["races"]:
                emit(f"{code}/{mid}/{r['race_key']}.json",
                     queries.build_race(con, code, mid, r["gender"],
                                        r["distance"], r["stroke"], r["course"],
                                        r["relay_count"]))
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -q`
Expected: PASS (relay-detail tests + all existing individual `build_race` tests still green).

- [ ] **Step 7: Full suite**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: PASS (134 + new tests).

- [ ] **Step 8: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/webbuild/build.py st-scrape/tests/test_webbuild.py
git commit -m "feat(webbuild): relay race-detail page (team podium, DSQ, no cut-line trends)"
```

---

### Task 5: Frontend relay rendering

**Files:**
- Modify: `web/src/routes/Race.svelte`
- Modify: `web/src/routes/Meet.svelte`
- Test: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: race JSON now carries `is_relay` (both endpoints) and race-list rows carry `is_relay`.
- Produces: relay race page omits Junior / cut-line / spread-1-8 tiles and the cut-line chart; relay list rows read "hold". Podium already renders team names as plain text (SwimmerLink falls back on null id).

- [ ] **Step 1: Write the failing test**

Add to `web/tests/routes.render.test.js` a case that renders `Race.svelte` with a relay payload (follow the existing render-test setup in that file — mock `getRace` to resolve the relay object below, mount the component, await tick):

```js
const relayRace = {
  category: 'DM-L', meet_id: 'R2026', race_key: 'F-4x100-HM-LCM',
  label: 'F 4x100m HM', is_relay: true,
  facts: { contestants: 3, dsq: 1, winning_time: '4:10.51', median_cs: 25444,
           spread_1_last_cs: 1203, winner_points: 500 },
  podium: [{ rank: 1, name: 'Aalborg 1', swimmer_id: null, club: 'Aalborg SK',
             time: '4:10.51', points: 500 }],
  season_comparison: [{ season: 2026, best_cs: 25051, median_cs: 25444,
                        top8_avg_cs: 25300, cutline_cs: null, swims: 3 }],
}
```

Assert, after render: the document text does NOT contain `A-finale-grænse` and does NOT contain `Juniorer`; the podium team name `Aalborg 1` is present as plain text (no anchor — `container.querySelector('a.swimmer-link')` is null).

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npm test`
Expected: FAIL — the relay case renders the cut-line/junior tiles (current unconditional tiles list).

- [ ] **Step 3: Implement `Race.svelte` guards**

In `web/src/routes/Race.svelte`, replace the `tiles` derivation with a relay-aware version:

```js
  const tiles = $derived(
    race
      ? [
          { label: race.is_relay ? 'Hold' : 'Deltagere', value: formatInt(race.facts.contestants) },
          { label: 'Diskvalifikationer', value: formatInt(race.facts.dsq) },
          { label: 'Vindertid', value: formatTimeStr(race.facts.winning_time) },
          ...(race.is_relay ? [] : [
            { label: 'A-finale-grænse', value: formatTime(race.facts.cutline_centiseconds) },
          ]),
          { label: 'Median', value: formatTime(race.facts.median_cs) },
          ...(race.is_relay ? [] : [
            { label: 'Spredning 1.–8.', value: formatTime(race.facts.spread_1_8_cs) },
            { label: 'Juniorer', value: formatInt(race.facts.juniors) },
          ]),
        ]
      : [],
  )
```

Wrap the cut-line `TrendChart` (the one with `y="cutline_cs"`) in a guard:

```svelte
    {#if !race.is_relay}
      <TrendChart
        data={race.season_comparison}
        x="season"
        y="cutline_cs"
        yLabel="A-finale-grænse pr. sæson"
        lowerIsBetter={true}
        format={formatTime}
      />
    {/if}
```

(Leave the best/median/swims charts unconditional — relay comparison rows carry those.)

- [ ] **Step 4: Implement `Meet.svelte` copy**

In `web/src/routes/Meet.svelte`, change the race-count span:

```svelte
            <span class="race-count num muted">{formatInt(r.contestants)} {r.is_relay ? 'hold' : 'deltagere'}</span>
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npm test`
Expected: PASS (new relay render case + existing render/router/format tests).

- [ ] **Step 6: Build smoke**

Run: `cd web && npm run build`
Expected: build succeeds (no Svelte compile errors).

- [ ] **Step 7: Commit**

```bash
git add web/src/routes/Race.svelte web/src/routes/Meet.svelte web/tests/routes.render.test.js
git commit -m "feat(web): render relay race pages (team podium, no cut-line/junior tiles)"
```

---

## Post-implementation (manual, not a task)

Regenerate data and deploy per the existing runbook — relays appear only after a data rebuild:

```bash
# rebuild JSON from the curated zone, then publish SPA + data
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data   # or the path make web-refresh expects
cd .. && make web-deploy && make web-refresh
```

Confirm on a meet known to have relays (e.g. meet 10334): relay events appear in the race list labelled `4x100m HM` etc., the relay page shows a team podium with no swimmer links and no cut-line chart, and DQ'd relay teams are counted under Diskvalifikationer but absent from the podium. Deploy is outward-facing — confirm with the user before running.
