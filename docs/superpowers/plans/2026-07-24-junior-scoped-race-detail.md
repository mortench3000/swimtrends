# Junior-scoped race detail for combined DMJ-L meets — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a combined senior+junior meet (tagged both `DM-L` and `DMJ-L`), make the DMJ-L race detail page show the junior championship — podium, stat tiles, and season graphs derived from juniors' qualifying swims — instead of duplicating the senior page.

**Architecture:** `webbuild/queries.py:build_race` gains a branch: when `category == 'DMJ-L'` AND the meet is combined, build the payload from the existing `junior_championship` view (`analytics/views/60_junior.sql`) instead of the senior queries. A `junior_scoped` boolean travels in the race JSON so `web/src/routes/Race.svelte` can drop the tiles/chart that describe a senior heats→final structure juniors don't have. No new analytics views, no infra change.

**Tech Stack:** Python 3.12 + DuckDB (webbuild, pytest); Svelte 5 SPA (vitest + @testing-library/svelte).

## Global Constraints

- Run backend tests from `st-scrape/`: `.venv/bin/python -m pytest -q` (must stay green; 134 existing + new).
- Run frontend tests from `web/`: `npm test` (vitest).
- Domain rule (do not alter): junior title decided from the **qualifying** swim — `junior_championship` uses `phase IN ('heats','timed_final')`, `category='DMJ-L'`, `is_junior`, `class='open'`.
- `is_junior` = `(season - birth_year) BETWEEN 16 AND 18`. For a season-2026 meet a junior is born 2008–2010; use `birth_year = season - 17` in fixtures to keep swimmers junior across seasons.
- Trigger is **combined-ness**, not category: junior path fires only when the meet's `cur_dim_meet.category` list contains a non-`DMJ` tag. Non-combined DMJ-L and all DMJ-K meets stay byte-for-byte unchanged.
- Curated view/table bindings in webbuild: `cur_obt`, `cur_dim_meet`, `cur_fact_split`; analytics views `results`, `results_by_category`, `junior_championship`.
- Keep `race_key`, `label`, `is_relay`, `facts`, `podium`, `season_comparison` shapes identical to the existing `build_race` return; only add `junior_scoped`.

## File structure

- `st-scrape/tests/webbuild_fixtures.py` — add `_combined_event`, `combined_con`, `junior_only_con` (curated fixtures).
- `st-scrape/webbuild/queries.py` — add `_meet_is_combined`, `_build_junior_race`, junior SQL constants; branch in `build_race`; add `junior_scoped` to existing returns.
- `st-scrape/tests/test_webbuild.py` — new assertions for the junior path + regressions.
- `web/src/routes/Race.svelte` — drop cutline/1–8/juniors tiles and cutline chart when `junior_scoped`.
- `web/tests/routes.render.test.js` — assert tile/chart hiding.

---

### Task 1: Combined detection + junior podium

**Files:**
- Modify: `st-scrape/tests/webbuild_fixtures.py` (add `_combined_event`, `combined_con`)
- Modify: `st-scrape/webbuild/queries.py` (add `_meet_is_combined`, `_JUNIOR_PODIUM_SQL`, junior branch in `build_race`, `_build_junior_race` returning at least podium)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Produces: `queries._meet_is_combined(con, meet_id) -> bool`; `queries._build_junior_race(con, meet_id, gender, distance, stroke, course) -> dict` (this task: `category`, `meet_id`, `race_key`, `label`, `is_relay=False`, `junior_scoped=True`, `podium`; `facts`/`season_comparison` added in Tasks 2–3); `build_race(...)` returns the junior payload when `category=='DMJ-L'` and the meet is combined.
- Consumes: `junior_championship` view; `webbuild_fixtures.combined_con()`.

- [ ] **Step 1: Add the combined fixture**

Add to `st-scrape/tests/webbuild_fixtures.py` (after `_relay_event`, before `relay_con`):

```python
def _combined_event(meet_id, meet_name, season, meet_date, gender, distance, stroke,
                    finalists, heat_only):
    """Combined senior+junior event. finalists: (sid, name, club, final_cs, birth_year)
    -> heats (final_cs+50) AND final. heat_only: (sid, name, club, heat_cs, birth_year)
    -> heats only, e.g. juniors who never reach the senior final. Returns rows."""
    rows = []
    rid = 0
    field = [(sid, name, club, cs + 50, by) for sid, name, club, cs, by in finalists]
    field += list(heat_only)
    for i, (sid, name, club, cs, by) in enumerate(sorted(field, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-h-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Heats"))
    for i, (sid, name, club, cs, by) in enumerate(sorted(finalists, key=lambda x: x[3]), 1):
        rid += 1
        rows.append(_obt_row(
            result_id=f"{meet_id}-f-{rid}", race_id=rid, meet_id=meet_id,
            rank=i, name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=f"{cs//6000}:{(cs%6000)//100:02d}.{cs%100:02d}",
            completed_centiseconds=cs, season=season, meet_name=meet_name,
            meet_date=meet_date, distance=distance, stroke=stroke, gender=gender,
            type="Final"))
    return rows


def combined_con() -> duckdb.DuckDBPyConnection:
    """A meet tagged BOTH DM-L and DMJ-L (a combined senior+junior championship),
    2025 + 2026. In M 100 Fri three seniors (born 2000) fill the final and take the
    senior podium; four juniors (born season-17 -> age 17) swim heats only and never
    reach the final, so the junior championship (ranked on the qualifying heat swim)
    is a different podium. This is the case webbuild must junior-scope."""
    obt, meets = [], []
    for season, mid, mdate in [(2025, "C2025", "2025-04-10"),
                               (2026, "C2026", "2026-04-10")]:
        name = f"Combined Champs {season}"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L", "DMJ-L"]))
        seniors = [("cs1", "Senior Ace", "AGF", 5300, 2000),
                   ("cs2", "Senior Two", "SIGMA", 5350, 2000),
                   ("cs3", "Senior Three", "VEST", 5400, 2000)]
        fillers = [(f"cf{i}", f"Filler {i}", "FILL", 5450 + i * 30, 2000)
                   for i in range(5)]                 # 5 fillers -> final has 8
        juniors = [("cj1", "Junior Fast", "AGF", 5700, season - 17),
                   ("cj2", "Junior Mid", "SIGMA", 5750, season - 17),
                   ("cj3", "Junior Slow", "VEST", 5800, season - 17),
                   ("cj4", "Junior Last", "AGF", 5850, season - 17)]
        obt += _combined_event(mid, name, season, mdate, "M", 100, "Fri",
                               seniors + fillers, juniors)
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 2: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_combined_dmjl_podium_is_junior_not_senior():
    from tests.webbuild_fixtures import combined_con
    con = combined_con()
    # senior page: unchanged, senior final podium
    dm = queries.build_race(con, "DM-L", "C2026", "M", 100, "Fri", "LCM")
    assert [p["name"] for p in dm["podium"]] == ["Senior Ace", "Senior Two", "Senior Three"]
    assert dm["junior_scoped"] is False
    # junior page: junior championship podium (heat times), different swimmers
    jr = queries.build_race(con, "DMJ-L", "C2026", "M", 100, "Fri", "LCM")
    assert jr["junior_scoped"] is True
    assert [p["rank"] for p in jr["podium"]] == [1, 2, 3]
    assert [p["name"] for p in jr["podium"]] == ["Junior Fast", "Junior Mid", "Junior Slow"]
    assert jr["podium"][0]["swimmer_id"] == "cj1"      # profile link
    assert jr["podium"][0]["time"] == "0:57.00"        # 5700 cs, the qualifying swim
    assert jr["race_key"] == "M-100-Fri-LCM"
    assert jr["label"] == "M 100m Fri"


def test_meet_is_combined_detects_senior_tag():
    from tests.webbuild_fixtures import combined_con, curated_con
    assert queries._meet_is_combined(combined_con(), "C2026") is True
    assert queries._meet_is_combined(curated_con(), "M2026") is False   # DM-L only
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_podium_is_junior_not_senior tests/test_webbuild.py::test_meet_is_combined_detects_senior_tag -v`
Expected: FAIL — `AttributeError: module 'webbuild.queries' has no attribute '_meet_is_combined'` (and `KeyError: 'junior_scoped'`).

- [ ] **Step 4: Implement detection, junior podium SQL, and the branch**

In `st-scrape/webbuild/queries.py`, add near the other race SQL constants (after `_RACE_COMPARE_SQL`):

```python
def _meet_is_combined(con, meet_id) -> bool:
    """True when the meet is tagged with a senior (non-junior) category alongside a
    junior one. At such a meet juniors have no separate final, so the junior title
    comes from the qualifying swim (see analytics/views/60_junior.sql). Detected via
    the raw category list on cur_dim_meet: any tag not starting with 'DMJ'."""
    row = con.execute(
        "SELECT category FROM cur_dim_meet WHERE meet_id = ?", [meet_id]).fetchone()
    return bool(row) and any(not c.startswith("DMJ") for c in row[0])


_JUNIOR_PODIUM_SQL = """
    SELECT junior_rank AS rank, name, swimmer_id, club, completed_time AS time, points
    FROM junior_championship
    WHERE meet_id = ? AND gender = ? AND distance = ? AND stroke = ? AND course = ?
      AND junior_rank IN (1, 2, 3)
    ORDER BY junior_rank
"""


def _build_junior_race(con, meet_id, gender, distance, stroke, course) -> dict:
    args = [meet_id, gender, distance, stroke, course]
    podium = [dict(zip(["rank", "name", "swimmer_id", "club", "time", "points"], r))
              for r in con.execute(_JUNIOR_PODIUM_SQL, args).fetchall()]
    return {"category": "DMJ-L", "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke}",
            "is_relay": False, "junior_scoped": True,
            "facts": {}, "podium": podium, "season_comparison": []}
```

In `build_race`, add the branch immediately after the relay check, and add `junior_scoped` to the normal return:

```python
def build_race(con, category, meet_id, gender, distance, stroke, course, relay_count=1) -> dict:
    if relay_count > 1:
        return _build_relay_race(con, category, meet_id, gender, distance, stroke, course, relay_count)
    if category == "DMJ-L" and _meet_is_combined(con, meet_id):
        return _build_junior_race(con, meet_id, gender, distance, stroke, course)
    args = [category, meet_id, gender, distance, stroke, course]
    # ... unchanged body ...
    return {"category": category, "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke}",
            "is_relay": False, "junior_scoped": False,
            "facts": facts, "podium": podium, "season_comparison": comp}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_podium_is_junior_not_senior tests/test_webbuild.py::test_meet_is_combined_detects_senior_tag -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/tests/webbuild_fixtures.py st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(web): junior-championship podium on combined DMJ-L race pages"
```

---

### Task 2: Junior stat tiles + junior_scoped flag everywhere

**Files:**
- Modify: `st-scrape/webbuild/queries.py` (add `_JUNIOR_FACTS_SQL`, `_JUNIOR_DSQ_SQL`; fill `facts` in `_build_junior_race`; add `junior_scoped: False` to `_build_relay_race`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `_build_junior_race` from Task 1, `combined_con`, `junior_only_con`.
- Produces: `_build_junior_race` now returns a full `facts` dict with keys `contestants`, `winning_time`, `winner_points`, `median_cs`, `median_points`, `spread_1_last_cs`, `dsq`, and explicit-`None` `cutline_centiseconds`, `cutline_time`, `spread_1_8_cs`, `juniors`.

- [ ] **Step 1: Add the non-combined junior fixture**

Add to `st-scrape/tests/webbuild_fixtures.py` (after `combined_con`):

```python
def junior_only_con() -> duckdb.DuckDBPyConnection:
    """A DMJ-L meet NOT combined with any senior category: juniors race their own
    heats + final, medals from the final. webbuild must leave this untouched
    (junior_scoped == False, all senior-structure tiles present)."""
    mid, name, season, mdate = "J2026", "Junior Champs 2026", 2026, "2026-04-10"
    meets = [dict(meet_id=mid, meet_name=name, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DMJ-L"])]
    rows, _ = _event(mid, name, season, mdate, "M", 100, "Fri",
                     [("j1", "Ung Anna", "AGF", 5600),
                      ("j2", "Ung Bo", "SIGMA", 5650),
                      ("j3", "Ung Cara", "VEST", 5700)], start_rid=1)
    con = duckdb.connect()
    build_curated(con, obt=rows, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 2: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_combined_dmjl_facts_are_junior_scoped():
    from tests.webbuild_fixtures import combined_con
    jr = queries.build_race(combined_con(), "DMJ-L", "C2026", "M", 100, "Fri", "LCM")
    f = jr["facts"]
    assert f["contestants"] == 4                 # four juniors, not the senior field
    assert f["winning_time"] == "0:57.00"        # junior gold qualifying swim (5700)
    assert f["median_cs"] == 5775                # median(5700,5750,5800,5850)
    assert f["spread_1_last_cs"] == 150          # 5850 - 5700
    # senior heats->final tiles do not apply to a junior championship: dropped
    assert f["cutline_centiseconds"] is None
    assert f["spread_1_8_cs"] is None
    assert f["juniors"] is None


def test_combined_dmjl_dsq_is_junior_scoped():
    from tests.webbuild_fixtures import combined_con
    jr = queries.build_race(combined_con(), "DMJ-L", "C2026", "M", 100, "Fri", "LCM")
    assert jr["facts"]["dsq"] == 0               # no DQ rows in the fixture


def test_noncombined_dmjl_is_unchanged():
    from tests.webbuild_fixtures import junior_only_con
    out = queries.build_race(junior_only_con(), "DMJ-L", "J2026", "M", 100, "Fri", "LCM")
    assert out["junior_scoped"] is False
    assert out["facts"]["cutline_centiseconds"] is not None    # real junior final
    assert out["facts"]["juniors"] is not None
    assert [p["rank"] for p in out["podium"]] == [1, 2, 3]
    assert out["podium"][0]["name"] == "Ung Anna"              # from the final
```

Note: junior-DSQ SQL correctness (the `is_junior` filter) is only lightly exercised here — the fixture has no DQ rows, so this asserts the query runs and returns 0. Deeper junior-DQ counting mirrors the existing `test_build_race_facts_dsq_counted_from_results` pattern and needs no new fixture (YAGNI).

- [ ] **Step 3: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_facts_are_junior_scoped tests/test_webbuild.py::test_noncombined_dmjl_is_unchanged tests/test_webbuild.py::test_combined_dmjl_dsq_is_junior_scoped -v`
Expected: FAIL — `KeyError: 'contestants'` (facts is `{}` from Task 1).

- [ ] **Step 4: Implement junior facts**

In `st-scrape/webbuild/queries.py`, add the SQL constants near `_JUNIOR_PODIUM_SQL`:

```python
_JUNIOR_FACTS_SQL = """
    WITH j AS (
        SELECT * FROM junior_championship
        WHERE meet_id = ? AND gender = ? AND distance = ? AND stroke = ? AND course = ?
    )
    SELECT
        (SELECT count(DISTINCT swimmer_id) FROM j) AS contestants,
        (SELECT arg_min(completed_time, completed_centiseconds) FROM j) AS winning_time,
        (SELECT arg_min(points, completed_centiseconds) FROM j) AS winner_points,
        (SELECT CAST(quantile_cont(completed_centiseconds, 0.5) AS BIGINT) FROM j) AS median_cs,
        (SELECT CAST(quantile_cont(points, 0.5) AS BIGINT) FROM j) AS median_points,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds) FROM j) AS spread_1_last_cs
"""

# Junior DQs: base `results` carries is_junior + is_dq (analytics/views/00_base.sql);
# junior_championship excludes DQ rows, so count them here instead.
_JUNIOR_DSQ_SQL = """
    SELECT count(*) FROM results
    WHERE meet_id = ? AND gender = ? AND distance = ? AND stroke = ? AND course = ?
      AND is_dq AND NOT is_relay AND is_junior AND class = 'open'
"""
```

Replace the `facts`/return in `_build_junior_race` so it fills facts:

```python
def _build_junior_race(con, meet_id, gender, distance, stroke, course) -> dict:
    args = [meet_id, gender, distance, stroke, course]
    fact_cols = ["contestants", "winning_time", "winner_points",
                 "median_cs", "median_points", "spread_1_last_cs"]
    facts = dict(zip(fact_cols, con.execute(_JUNIOR_FACTS_SQL, args).fetchone()))
    facts["dsq"] = con.execute(_JUNIOR_DSQ_SQL, args).fetchone()[0]
    # These describe the senior heats->final structure a combined-meet junior
    # championship has no equivalent for; Race.svelte drops them via junior_scoped.
    facts["cutline_centiseconds"] = None
    facts["cutline_time"] = None
    facts["spread_1_8_cs"] = None
    facts["juniors"] = None
    podium = [dict(zip(["rank", "name", "swimmer_id", "club", "time", "points"], r))
              for r in con.execute(_JUNIOR_PODIUM_SQL, args).fetchall()]
    return {"category": "DMJ-L", "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke}",
            "is_relay": False, "junior_scoped": True,
            "facts": facts, "podium": podium, "season_comparison": []}
```

Add `junior_scoped: False` to `_build_relay_race`'s return dict (find the `return {"category": category, ... "is_relay": True, ...}` and insert `"junior_scoped": False,`).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -k "junior or noncombined or combined" -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/tests/webbuild_fixtures.py st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(web): junior-scoped stat tiles for combined DMJ-L race pages"
```

---

### Task 3: Junior season-comparison graphs

**Files:**
- Modify: `st-scrape/webbuild/queries.py` (add `_JUNIOR_COMPARE_SQL`; fill `season_comparison` in `_build_junior_race`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `_build_junior_race`, `combined_con`.
- Produces: `_build_junior_race` returns `season_comparison` as a list of `{season, best_cs, median_cs, top8_avg_cs, cutline_cs, swims}`, newest-first, ≤5 seasons, `cutline_cs` always `None`.

- [ ] **Step 1: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_combined_dmjl_graphs_reflect_juniors_only():
    from tests.webbuild_fixtures import combined_con
    jr = queries.build_race(combined_con(), "DMJ-L", "C2026", "M", 100, "Fri", "LCM")
    comp = jr["season_comparison"]
    assert [c["season"] for c in comp] == [2026, 2025]     # newest first, both seasons
    row = comp[0]
    assert row["best_cs"] == 5700          # fastest junior qualifying swim, not senior
    assert row["swims"] == 4               # four juniors, not the full field
    assert row["cutline_cs"] is None       # no junior final -> no cutline curve
    assert row["top8_avg_cs"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_graphs_reflect_juniors_only -v`
Expected: FAIL — `season_comparison` is `[]`, so `comp[0]` raises `IndexError`.

- [ ] **Step 3: Implement the junior season query**

In `st-scrape/webbuild/queries.py`, add near the other junior SQL:

```python
# Per-season junior standard for the trend charts. Aggregates junior_championship
# (qualifying swims across all DMJ-L meets) for the event. Same window as
# _RACE_COMPARE_SQL: seasons <= the meet's, newest 5. No cutline (no junior final).
_JUNIOR_COMPARE_SQL = """
    WITH j AS (
        SELECT season, completed_centiseconds,
               row_number() OVER (PARTITION BY season ORDER BY completed_centiseconds) AS rn
        FROM junior_championship
        WHERE gender = ? AND distance = ? AND stroke = ? AND course = ? AND season <= ?
    )
    SELECT season,
           min(completed_centiseconds) AS best_cs,
           CAST(quantile_cont(completed_centiseconds, 0.5) AS BIGINT) AS median_cs,
           CAST(avg(completed_centiseconds) FILTER (WHERE rn <= 8) AS BIGINT) AS top8_avg_cs,
           NULL AS cutline_cs,
           count(*) AS swims
    FROM j
    GROUP BY season
    ORDER BY season DESC
    LIMIT 5
"""
```

In `_build_junior_race`, replace `"season_comparison": []` by computing it (add before the `return`):

```python
    season = con.execute(
        "SELECT any_value(season) FROM junior_championship WHERE meet_id = ?",
        [meet_id]).fetchone()[0]
    comp_cols = ["season", "best_cs", "median_cs", "top8_avg_cs", "cutline_cs", "swims"]
    comp = [dict(zip(comp_cols, r)) for r in con.execute(
        _JUNIOR_COMPARE_SQL,
        [gender, distance, stroke, course, season]).fetchall()]
```

and change the return to `"season_comparison": comp`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_graphs_reflect_juniors_only -v`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: all pass (existing 134 + new).

- [ ] **Step 6: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(web): junior-scoped season-trend graphs for combined DMJ-L race pages"
```

---

### Task 4: Frontend — hide senior-structure tiles/chart when junior_scoped

**Files:**
- Modify: `web/src/routes/Race.svelte`
- Test: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: `race.junior_scoped` boolean in the race JSON (from Tasks 1–3).
- Produces: no new module exports; UI omits the "A-finale-grænse" tile, "Spredning 1.–8." tile, "Juniorer" tile, and the cutline `<TrendChart>` when `race.junior_scoped` is true.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/routes.render.test.js` (after the existing Race tests):

```javascript
const juniorRace = {
  category: 'DMJ-L', meet_id: 'C2026', race_key: 'M-100-Fri-LCM',
  label: 'M 100m Fri', is_relay: false, junior_scoped: true,
  facts: {
    contestants: 4, dsq: 0, winning_time: '0:57.00', median_cs: 5775,
    spread_1_last_cs: 150, winner_points: 500,
    cutline_centiseconds: null, spread_1_8_cs: null, juniors: null,
  },
  podium: [{ rank: 1, name: 'Junior Fast', swimmer_id: 'cj1', club: 'AGF',
             time: '0:57.00', points: 500 }],
  season_comparison: [{ season: 2026, best_cs: 5700, median_cs: 5775,
                        top8_avg_cs: 5775, cutline_cs: null, swims: 4 }],
}

test('junior-scoped race hides senior-structure tiles', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(juniorRace)
  render(Race, { params: { cat: 'DMJ-L', meetId: 'C2026', raceKey: 'M-100-Fri-LCM' } })
  await waitFor(() => expect(screen.getByText('Junior Fast')).toBeInTheDocument())
  expect(screen.queryByText('A-finale-grænse')).toBeNull()
  expect(screen.queryByText('Spredning 1.–8.')).toBeNull()
  expect(screen.queryByText('Juniorer')).toBeNull()
  expect(screen.getByText('Deltagere')).toBeInTheDocument()   // kept
})

test('non-junior race still shows the A-finale-grænse tile', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(raceJson)
  render(Race, { params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
  await waitFor(() => expect(screen.getByText(raceJson.podium[0].name)).toBeInTheDocument())
  expect(screen.getByText('A-finale-grænse')).toBeInTheDocument()
})
```

Note: `StatTile` renders the label as text, so `getByText('A-finale-grænse')` matches the tile label. If `raceJson` (fixture) lacks `cutline_centiseconds`, the second test still passes because the tile label renders regardless of value — verify `web/tests/fixtures/race.json` has `is_relay: false` (it does; it's the individual race fixture).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- routes.render`
Expected: FAIL — junior-scoped test finds "A-finale-grænse"/"Juniorer" because they still render.

- [ ] **Step 3: Implement the conditionals**

In `web/src/routes/Race.svelte`, add a derived flag after line 12 (`let { params = {} } = $props()`):

```javascript
  const jr = $derived(race?.junior_scoped === true)
```

Change the `tiles` derivation (lines 32–48) so the cutline, 1–8 spread, and juniors tiles are omitted when `jr`:

```javascript
  const tiles = $derived(
    race
      ? [
          { label: race.is_relay ? 'Hold' : 'Deltagere', value: formatInt(race.facts.contestants) },
          { label: 'Diskvalifikationer', value: formatInt(race.facts.dsq) },
          { label: 'Vindertid', value: formatTimeStr(race.facts.winning_time) },
          ...(race.is_relay || jr ? [] : [
            { label: 'A-finale-grænse', value: formatTime(race.facts.cutline_centiseconds) },
          ]),
          { label: 'Median', value: formatTime(race.facts.median_cs) },
          ...(race.is_relay || jr ? [] : [
            { label: 'Spredning 1.–8.', value: formatTime(race.facts.spread_1_8_cs) },
            { label: 'Juniorer', value: formatInt(race.facts.juniors) },
          ]),
        ]
      : [],
  )
```

Change the cutline chart guard (line 105) from `{#if !race.is_relay}` to:

```svelte
    {#if !race.is_relay && !jr}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- routes.render`
Expected: PASS.

- [ ] **Step 5: Run the full frontend suite**

Run: `cd web && npm test`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/Race.svelte web/tests/routes.render.test.js
git commit -m "feat(web): drop senior-structure tiles/chart on junior-scoped race pages"
```

---

## Verification (after all tasks)

- [ ] Backend: `cd st-scrape && .venv/bin/python -m pytest -q` — green.
- [ ] Frontend: `cd web && npm test` — green.
- [ ] Visual smoke via the `run-web` skill: regenerate `web/public/data` if the skill does so, then screenshot `#/c/DMJ-L/m/12486/r/M-200-Bryst-LCM` and the DM-L equivalent — confirm the DMJ-L podium/tiles/graphs now differ (junior standings) and the DM-L page is unchanged. Data regeneration requires AWS creds for the curated zone; if unavailable, note it and rely on the unit tests.

---

## Addendum (2026-07-24): junior-scope the whole meet page

The final whole-branch review found the meet page one level up (`#/c/DMJ-L/m/<id>`) was still senior-scoped, so its race list showed senior winners/counts while the detail pages (Tasks 1–4) show juniors, and no-junior events opened empty detail pages. User approved junior-scoping the **whole meet page** (race list + header tiles/trends) for combined DMJ-L meets. The category meet-list cards (`build_meets`) are a deliberate follow-up, not in this plan. Relays stay senior-scoped everywhere (no junior-relay title; `junior_championship` excludes relays) — documented, intentional.

All three tasks reuse the combined fixture. Task 5 extends `combined_con` with a **seniors-only** event (F 200 Ryg, no juniors) so the "no-junior event is dropped from the junior list" behavior is testable. Existing junior tests query only the M-100-Fri event and assert no event counts, so they stay green — the implementer runs the full suite to confirm.

### Task 5: Junior-scope the meet-page race list (`build_races`)

**Files:**
- Modify: `st-scrape/tests/webbuild_fixtures.py` (add a seniors-only event to `combined_con`)
- Modify: `st-scrape/webbuild/queries.py` (add `_JUNIOR_RACES_SQL`; branch in `build_races`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `_meet_is_combined`, `junior_championship`, `combined_con`.
- Produces: `build_races(con, 'DMJ-L', combined_meet_id)` returns individual races sourced from `junior_championship` (junior winner/count, no-junior events absent); relay rows unchanged. Because `build_all` emits per-race detail files by iterating `build_races` output, dropped events also stop generating detail JSON.

- [ ] **Step 1: Extend `combined_con` with a seniors-only event**

In `st-scrape/tests/webbuild_fixtures.py`, inside `combined_con`'s season loop, after the existing `obt += _combined_event(... "M", 100, "Fri", ...)` line, add a second event with no juniors:

```python
        seniors_ryg = [("rs1", "Ryg Senior A", "AGF", 13000, 2000),
                       ("rs2", "Ryg Senior B", "SIGMA", 13100, 2000),
                       ("rs3", "Ryg Senior C", "VEST", 13200, 2000)]
        obt += _combined_event(mid, name, season, mdate, "F", 200, "Ryg",
                               seniors_ryg, [])          # no juniors in this event
```

- [ ] **Step 2: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_combined_dmjl_race_list_is_junior_scoped():
    from tests.webbuild_fixtures import combined_con
    con = combined_con()
    # DM-L list: both events, senior winners
    dm = {r["race_key"]: r for r in queries.build_races(con, "DM-L", "C2026")["races"]}
    assert dm["M-100-Fri-LCM"]["winner_name"] == "Senior Ace"
    assert "F-200-Ryg-LCM" in dm                         # seniors-only event listed
    # DMJ-L list: junior winner/count on the junior event, seniors-only event dropped
    jr = {r["race_key"]: r for r in queries.build_races(con, "DMJ-L", "C2026")["races"]}
    assert jr["M-100-Fri-LCM"]["winner_name"] == "Junior Fast"
    assert jr["M-100-Fri-LCM"]["contestants"] == 4
    assert "F-200-Ryg-LCM" not in jr                     # no juniors -> not listed


def test_noncombined_dmjl_race_list_unchanged():
    from tests.webbuild_fixtures import junior_only_con
    out = queries.build_races(junior_only_con(), "DMJ-L", "J2026")
    fri = [r for r in out["races"] if r["race_key"] == "M-100-Fri-LCM"][0]
    assert fri["winner_name"] == "Ung Anna"              # from the final, unchanged path
    assert fri["contestants"] == 11                      # full field (3 + 8 heat fillers)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_race_list_is_junior_scoped -v`
Expected: FAIL — `assert 'Senior Ace' == 'Junior Fast'` (list still senior) and `'F-200-Ryg-LCM' not in jr` fails.

- [ ] **Step 4: Implement**

In `st-scrape/webbuild/queries.py`, add near `_RACES_SQL`:

```python
# Junior race list for a combined DMJ-L meet: individual events sourced from
# junior_championship (juniors ranked by qualifying swim). Events with no juniors
# produce no rows and so drop from the list — and, via build_all, get no detail file.
_JUNIOR_RACES_SQL = """
    SELECT gender, distance, stroke, course,
           count(DISTINCT swimmer_id) AS contestants,
           arg_min(name, completed_centiseconds) AS winner_name,
           arg_min(completed_time, completed_centiseconds) AS winning_time
    FROM junior_championship
    WHERE meet_id = ?
    GROUP BY gender, distance, stroke, course
    ORDER BY gender, distance, stroke, course
"""
```

Change `build_races` to pick the individual-race source based on combined-ness (relay loop unchanged):

```python
def build_races(con, category: str, meet_id: str) -> dict:
    combined_junior = category == "DMJ-L" and _meet_is_combined(con, meet_id)
    ind_sql = _JUNIOR_RACES_SQL if combined_junior else _RACES_SQL
    ind_args = [meet_id] if combined_junior else [category, meet_id]
    races = []
    for gender, distance, stroke, course, contestants, winner, wtime in con.execute(
            ind_sql, ind_args).fetchall():
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

- [ ] **Step 5: Run test to verify it passes; then the full suite**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_race_list_is_junior_scoped tests/test_webbuild.py::test_noncombined_dmjl_race_list_unchanged -v`
Then: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: new tests PASS; full suite green (the seniors-only event added to `combined_con` must not break the Task 1–3 junior tests).

- [ ] **Step 6: Commit**

```bash
git add st-scrape/tests/webbuild_fixtures.py st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(web): junior-scope the meet-page race list for combined DMJ-L meets"
```

---

### Task 6: Junior-scope the meet header (`build_meet` facts + trends)

**Files:**
- Modify: `st-scrape/webbuild/queries.py` (add `_JUNIOR_MEET_FACTS_SQL`, `_JUNIOR_MEET_COMPARE_SQL`, `_JUNIOR_MEET_ELITE_SQL`; branch in `build_meet`; add `junior_scoped`)
- Test: `st-scrape/tests/test_webbuild.py`

**Interfaces:**
- Consumes: `_meet_is_combined`, `junior_championship`, `combined_con` (now with the seniors-only event from Task 5).
- Produces: `build_meet(con, 'DMJ-L', combined_meet_id)` returns `facts`/`season_comparison` computed over juniors, plus `"junior_scoped": True`. Relay-event counts stay senior (added on top, as today). Non-combined/DM-L returns get `"junior_scoped": False`.

- [ ] **Step 1: Write the failing test**

Add to `st-scrape/tests/test_webbuild.py`:

```python
def test_combined_dmjl_meet_header_is_junior_scoped():
    from tests.webbuild_fixtures import combined_con
    out = queries.build_meet(combined_con(), "DMJ-L", "C2026")
    assert out["junior_scoped"] is True
    f = out["facts"]
    assert f["entrants"] == 4               # four juniors, not the full senior field
    assert f["events"] == 1                 # only M-100-Fri has juniors (F-200-Ryg dropped)
    assert f["top_points"] == 500           # fixture points are uniform 500
    comp_seasons = [c["season"] for c in out["season_comparison"]]
    assert comp_seasons == [2026, 2025]
    assert all(c["entrants"] == 4 for c in out["season_comparison"])


def test_noncombined_dmjl_meet_header_unchanged():
    from tests.webbuild_fixtures import junior_only_con
    out = queries.build_meet(junior_only_con(), "DMJ-L", "J2026")
    assert out["junior_scoped"] is False
    assert out["facts"]["entrants"] == 11   # full field, unchanged path


def test_dml_meet_header_unchanged():
    out = queries.build_meet(curated_con(), "DM-L", "M2026")
    assert out["junior_scoped"] is False
    assert out["facts"]["entrants"] == 22
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py::test_combined_dmjl_meet_header_is_junior_scoped -v`
Expected: FAIL — `KeyError: 'junior_scoped'` (build_meet has no such key yet).

- [ ] **Step 3: Implement**

In `st-scrape/webbuild/queries.py`, add junior meet SQL near the senior meet SQL. These mirror `_MEET_FACTS_SQL`, `_MEET_COMPARE_SQL`, `_MEET_ELITE_SQL` but read from `junior_championship` (juniors, qualifying swims). `junior_championship` has no `class` column (already `class='open'` internally) and no relay rows.

```python
_JUNIOR_MEET_FACTS_SQL = """
    SELECT count(*) AS swims,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           count(DISTINCT swimmer_id) AS juniors,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM junior_championship
    WHERE meet_id = ?
"""

_JUNIOR_MEET_COMPARE_SQL = """
    SELECT season,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM junior_championship
    WHERE season <= ?
    GROUP BY season
    ORDER BY season DESC
    LIMIT 5
"""

_JUNIOR_MEET_ELITE_SQL = """
    WITH best AS (
        SELECT season, gender, distance, stroke, course, swimmer_id,
               max(points) AS pts
        FROM junior_championship
        WHERE season <= ? AND points IS NOT NULL AND swimmer_id IS NOT NULL
        GROUP BY season, gender, distance, stroke, course, swimmer_id
    ),
    ranked AS (
        SELECT season, pts,
               row_number() OVER (
                   PARTITION BY season, gender, distance, stroke, course
                   ORDER BY pts DESC) AS rk
        FROM best
    )
    SELECT season, CAST(quantile_cont(pts, 0.5) AS BIGINT) AS elite_median_points
    FROM ranked
    WHERE rk <= 10
    GROUP BY season
"""
```

Refactor `build_meet` to select junior vs senior SQL. Keep everything else (head lookup, relay-event addition, elite merge) identical:

```python
def build_meet(con, category: str, meet_id: str) -> dict:
    combined_junior = category == "DMJ-L" and _meet_is_combined(con, meet_id)
    head = con.execute(
        "SELECT any_value(meet_name), any_value(meet_date), any_value(season) "
        "FROM results_by_category WHERE category = ? AND meet_id = ?",
        [category, meet_id],
    ).fetchone()
    fact_cols = ["swims", "entrants", "events", "clubs", "juniors",
                 "median_points", "top_points"]
    if combined_junior:
        facts = dict(zip(fact_cols, con.execute(
            _JUNIOR_MEET_FACTS_SQL, [meet_id]).fetchone()))
    else:
        facts = dict(zip(fact_cols, con.execute(
            _MEET_FACTS_SQL, [category, meet_id]).fetchone()))
    comp_cols = ["season", "entrants", "events", "clubs", "median_points", "top_points"]
    if combined_junior:
        comp = [dict(zip(comp_cols, r)) for r in con.execute(
            _JUNIOR_MEET_COMPARE_SQL, [head[2]]).fetchall()]
        elite = dict(con.execute(_JUNIOR_MEET_ELITE_SQL, [head[2]]).fetchall())
    else:
        comp = [dict(zip(comp_cols, r)) for r in con.execute(
            _MEET_COMPARE_SQL, [category, head[2]]).fetchall()]
        elite = dict(con.execute(_MEET_ELITE_SQL, [category, head[2]]).fetchall())
    facts["elite_median_points"] = elite.get(head[2])
    for c in comp:
        c["elite_median_points"] = elite.get(c["season"])
    # Relay events stay senior-scoped (no junior-relay title); added on top as today.
    facts["events"] += con.execute(
        _MEET_RELAY_EVENTS_SQL, [category, meet_id]).fetchone()[0]
    rel_by_season = dict(con.execute(
        _MEET_RELAY_EVENTS_BY_SEASON_SQL, [category, head[2]]).fetchall())
    for c in comp:
        c["events"] += rel_by_season.get(c["season"], 0)
    return {"category": category, "meet_id": meet_id, "meet_name": head[0],
            "meet_date": head[1], "season": head[2], "junior_scoped": combined_junior,
            "facts": facts, "season_comparison": comp}
```

- [ ] **Step 4: Run test to verify it passes; then the full suite**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild.py -k "meet_header or build_meet" -v`
Then: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: new tests PASS; full suite green. Note the existing `test_build_meet_facts_and_comparison` (DM-L) must still pass unchanged.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/queries.py st-scrape/tests/test_webbuild.py
git commit -m "feat(web): junior-scope the meet-page header facts and trends for combined DMJ-L"
```

---

### Task 7: Frontend — hide the redundant "Juniorer" tile on junior-scoped meet pages

**Files:**
- Modify: `web/src/routes/Meet.svelte`
- Test: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: `meet.junior_scoped` boolean (from Task 6).
- Produces: `Meet.svelte` omits the "Juniorer" tile when `meet.junior_scoped` (on a junior-scoped page it equals "Deltagere", so it is noise). All other tiles/charts unchanged.

- [ ] **Step 1: Write the failing test**

Add to `web/tests/routes.render.test.js`. Reuse the existing `meetJson`/`racesJson` mocks pattern; add a junior-scoped meet object:

```javascript
const juniorMeet = {
  category: 'DMJ-L', meet_id: 'C2026', meet_name: 'Combined Champs 2026',
  meet_date: '2026-04-10', season: 2026, junior_scoped: true,
  facts: { swims: 4, entrants: 4, events: 1, clubs: 3, juniors: 4,
           median_points: 500, top_points: 500, elite_median_points: 500 },
  season_comparison: [{ season: 2026, entrants: 4, events: 1, clubs: 3,
                        median_points: 500, top_points: 500, elite_median_points: 500 }],
}

test('junior-scoped meet hides the redundant Juniorer tile', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(juniorMeet)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  render(Meet, { params: { cat: 'DMJ-L', meetId: 'C2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Combined Champs 2026' })).toBeInTheDocument())
  expect(screen.queryByText('Juniorer')).toBeNull()
  expect(screen.getByText('Deltagere')).toBeInTheDocument()   // kept
})

test('ordinary meet still shows the Juniorer tile', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.getByText('Juniorer')).toBeInTheDocument()
})
```

Confirm the `meetJson` fixture (`web/tests/fixtures/meet.json`) has no `junior_scoped` key (so the ordinary test exercises the false path) — if it lacks `facts.juniors`, the tile label still renders, so the assertion holds.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- routes.render`
Expected: FAIL — junior-scoped test finds "Juniorer" (tile still rendered).

- [ ] **Step 3: Implement**

In `web/src/routes/Meet.svelte`, add after `let meet = $state(null)` (line 14):

```javascript
  const jr = $derived(meet?.junior_scoped === true)
```

In the `tiles` derivation (lines 52–79), replace the unconditional "Juniorer" entry with a spread that omits it when `jr`:

```javascript
          ...(jr ? [] : [{ label: 'Juniorer', value: formatInt(meet.facts.juniors) }]),
```

(Place it where the `{ label: 'Juniorer', ... }` object currently sits, between the "Klubber" and "Median point" tiles.)

- [ ] **Step 4: Run test to verify it passes; then the full suite**

Run: `cd web && npm test -- routes.render`
Then: `cd web && npm test`
Expected: new tests PASS; full frontend suite green.

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/Meet.svelte web/tests/routes.render.test.js
git commit -m "feat(web): hide redundant Juniorer tile on junior-scoped meet pages"
```

---

## Self-review notes

- Spec coverage: podium (Task 1), tiles + dropped cutline/1–8/juniors + junior DSQ + junior_scoped flag (Task 2), graphs with dropped cutline curve (Task 3), frontend hiding (Task 4), regressions for DM-L and non-combined DMJ-L (Tasks 1–2). DMJ-K out of scope — no task, by design.
- `junior_scoped` set on all three `build_race` return paths (individual normal, relay, junior).
- `_build_junior_race` signature and `facts` keys are consistent across Tasks 1–3.
