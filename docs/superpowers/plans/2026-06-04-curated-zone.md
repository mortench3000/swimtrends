# Curated Zone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Spec 1 raw JSONL zone into a curated Parquet data lake with World Aquatics points, authoritative para classification, and flattened splits, cataloged in Glue for Athena/DuckDB.

**Architecture:** A new pure-functional `curate/` Python package under `st-scrape/` (sibling to `ingestion/`), mirroring the existing inject-the-side-effects style (`run_cycle`/`run_scrape_task`): pure transform functions are unit-tested with no AWS, and a thin `run_curate_task`/`main` wires real boto3 + pyarrow. A new `SwimtrendsCuratedStack` (CDK) adds a curated Fargate task, an S3-event trigger Lambda, a class-overrides DynamoDB table, and Glue catalog tables. Reuses the Spec 1 bucket, ECS cluster, and SNS topic.

**Tech Stack:** Python 3.12, pyarrow (Parquet), boto3, DynamoDB, S3, AWS Glue, AWS CDK (Python), pytest + moto.

---

## File structure

Created under `st-scrape/curate/` (new package):

- `curate/__init__.py` — package marker.
- `curate/points.py` — pure WA points logic (ported from `calc_points.py`).
- `curate/classify.py` — authoritative class resolution (override-else-heuristic).
- `curate/model.py` — build curated table rows from raw dicts (incl. `result_id`).
- `curate/transform.py` — pure `transform_meet()` orchestration → table→rows dict.
- `curate/parquet.py` — pyarrow schemas + `write_parquet_bytes()` + partition paths.
- `curate/overrides.py` — DynamoDB class-overrides access layer.
- `curate/basetimes.py` — load base times from an S3 object (or local file).
- `curate/catalog.py` — Glue table definitions + create/update.
- `curate/run.py` — `run_curate_task()` (injected I/O) + `main()` container entry.

Modified:

- `st-scrape/requirements.txt` — add `pyarrow`.
- `st-scrape/requirements-dev.txt` — moto already covers s3/dynamodb; add `pyarrow` via requirements.
- `st-scrape/ingestion/cli.py` — add `curate`, `class`, `basetimes` subcommands.
- `swimtrends-app/swimtrends_app/swimtrends_curated_stack.py` — new CDK stack.
- `swimtrends-app/app.py` — instantiate the curated stack.
- `swimtrends-app/tests/unit/test_curated_stack.py` — CDK assertions.

Test files: one per module under `st-scrape/tests/` (e.g. `tests/test_curate_points.py`).

## Curated schemas (authoritative reference for all tasks)

All tables partitioned by `season` (int) then `course` (str), written one Parquet
file per meet: `curated/<table>/season=<s>/course=<c>/meet=<meet_id>.parquet`.

- **dim_meet:** `meet_id`(str), `meet_name`(str), `venue`(str), `course`(str), `season`(int), `meet_date`(str, `DD-MM-YYYY` from raw), `category`(list<str>).
- **dim_race:** `race_id`(int), `meet_id`(str), `number`(int), `name`(str), `distance`(int), `stroke`(str), `gender`(str), `relay_count`(int), `type`(str), `class`(str), `season`(int), `course`(str).
- **fact_result:** `result_id`(str), `race_id`(int), `meet_id`(str), `rank`(int), `name`(str), `swimmer_id`(str|null), `nationality`(str), `club`(str), `birth_year`(int|null), `completed_time`(str), `completed_centiseconds`(int|null), `points`(int|null), `points_fixed`(int|null), `season`(int), `course`(str).
- **fact_split:** `result_id`(str), `race_id`(int), `distance`(int), `split_time`(str), `split_centiseconds`(int|null), `cumulative_time`(str), `cumulative_centiseconds`(int|null), `season`(int), `course`(str).
- **obt_result:** all `fact_result` columns **plus** `meet_name`, `venue`, `meet_date`, `number`, `race_name`(from race `name`), `distance`, `stroke`, `gender`, `relay_count`, `type`, `class`. (`season`/`course` already present.)

**`result_id` = `f"{race_id}-{ordinal}"`** where `ordinal` is the 0-based index of the result among results of that race in raw file order. (NOT `Rank`: disqualified swims share `Rank = -1`, which would collide. File order is deterministic because the scraper overwrites raw deterministically.)

**Scorability (ported from `calc_points.py`):** a result is scored only if its race is known, `completed_centiseconds` is not null, and `Rank != -1` (DQ). Otherwise `points = points_fixed = null`. Para races (authoritative `class == "para"`) are never scored: `points = points_fixed = null`.

---

## Task 1: Add pyarrow dependency

**Files:**
- Modify: `st-scrape/requirements.txt`

- [ ] **Step 1: Add pyarrow to requirements.txt**

Append a line to `st-scrape/requirements.txt` so it reads:

```
requests>=2.31
beautifulsoup4>=4.12
boto3>=1.34
tzdata>=2024.1
pyarrow>=15.0
```

- [ ] **Step 2: Install into the venv**

Run: `cd st-scrape && .venv/bin/pip install -r requirements-dev.txt`
Expected: pyarrow installs; `.venv/bin/python -c "import pyarrow; print(pyarrow.__version__)"` prints a version ≥ 15.

- [ ] **Step 3: Commit**

```bash
git add st-scrape/requirements.txt
git commit -m "build: add pyarrow for curated Parquet output"
```

---

## Task 2: WA points (pure, ported from calc_points.py)

**Files:**
- Create: `st-scrape/curate/__init__.py` (empty)
- Create: `st-scrape/curate/points.py`
- Test: `st-scrape/tests/test_curate_points.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_points.py`:

```python
"""WA points: formula, stroke mapping, scorability, season vs fixed reference."""
from curate import points


def _table():
    # (season, course, gender, relay_count, distance, stroke) -> basetime_sec
    return {
        (2022, "LCM", "F", 1, 100, "FREE"): 51.71,
        (2026, "LCM", "F", 1, 100, "FREE"): 50.00,
    }


def test_formula_truncates():
    # 1000 * (51.71/51.71)**3 == 1000 exactly.
    assert points.calculate_points(51.71, 51.71) == 1000
    # Slower swim scores < 1000.
    assert points.calculate_points(51.71, 60.00) == 639


def test_stroke_mapping_im_and_holdmedley_to_medley():
    assert points.STROKE_MAP["IM"] == "MEDLEY"
    assert points.STROKE_MAP["HM"] == "MEDLEY"
    assert points.STROKE_MAP["Fri"] == "FREE"


def test_points_for_uses_season_and_fixed_reference():
    table = _table()
    race = {"gender": "F", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    # season 2022 base 51.71 vs a 52.00 swim.
    assert points.points_for(table, 2022, "LCM", race, 52.00) == 983
    # fixed reference season 2026 base 50.00 vs the same swim.
    assert points.points_for(table, 2026, "LCM", race, 52.00) == 888


def test_points_for_returns_none_when_no_base_time():
    table = _table()
    race = {"gender": "M", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    assert points.points_for(table, 2022, "LCM", race, 50.0) is None


def test_score_result_skips_dq_and_para_and_missing_time():
    table = _table()
    race = {"gender": "F", "relay_count": 1, "distance": 100, "stroke": "Fri"}
    # Normal scorable swim (open).
    p, pf = points.score_result(table, 2022, "LCM", race, klass="open",
                                completed_centiseconds=5200, rank=1)
    assert (p, pf) == (983, 888)
    # DQ (rank -1) -> not scored.
    assert points.score_result(table, 2022, "LCM", race, klass="open",
                               completed_centiseconds=5200, rank=-1) == (None, None)
    # Missing time -> not scored.
    assert points.score_result(table, 2022, "LCM", race, klass="open",
                               completed_centiseconds=None, rank=1) == (None, None)
    # Para -> never scored even with a valid time.
    assert points.score_result(table, 2022, "LCM", race, klass="para",
                               completed_centiseconds=5200, rank=1) == (None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_points.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate'`.

- [ ] **Step 3: Write minimal implementation**

Create empty `st-scrape/curate/__init__.py`. Create `st-scrape/curate/points.py`:

```python
"""World Aquatics points (pure). Ported from calc_points.py.

points = trunc(1000 * (basetime / swimtime) ** 3).
Two scores per result:
  points        - vs the meet's OWN season base times (era-relative).
  points_fixed  - vs FIXED_REF_SEASON (one stationary cross-era scale).
"""
import math

FIXED_REF_SEASON = 2026

# Danish scraper stroke codes -> base-time stroke codes. IM (individual medley)
# and HM (holdmedley / team medley relay) both map to MEDLEY.
STROKE_MAP = {"Fri": "FREE", "Ryg": "BACK", "Bryst": "BREAST", "Fly": "FLY",
              "IM": "MEDLEY", "HM": "MEDLEY"}


def calculate_points(basetime_sec, swimtime_sec):
    """WA points, truncated to an integer."""
    return math.trunc(1000 * math.pow(basetime_sec / swimtime_sec, 3))


def points_for(table, season, course, race, swimtime_sec):
    """Look up the base time for this race+season and score it, or None."""
    stroke = STROKE_MAP.get(race.get("stroke"))
    if stroke is None:
        return None
    base = table.get((season, course, race["gender"], race["relay_count"],
                      race["distance"], stroke))
    if base is None:
        return None
    return calculate_points(base, swimtime_sec)


def score_result(table, season, course, race, *, klass,
                 completed_centiseconds, rank):
    """Return (points, points_fixed). Para, DQ (rank -1), and missing-time
    results are never scored."""
    if klass == "para" or completed_centiseconds is None or rank == -1:
        return (None, None)
    t = completed_centiseconds / 100.0
    return (points_for(table, season, course, race, t),
            points_for(table, FIXED_REF_SEASON, course, race, t))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_points.py -v`
Expected: PASS (5 tests). If `calculate_points(51.71, 60.00)` differs, recompute the expected constant from the formula and update the test — the formula is authoritative.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/__init__.py st-scrape/curate/points.py st-scrape/tests/test_curate_points.py
git commit -m "feat: add pure WA points module for curated zone"
```

---

## Task 3: Authoritative class resolution

**Files:**
- Create: `st-scrape/curate/classify.py`
- Test: `st-scrape/tests/test_curate_classify.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_classify.py`:

```python
"""Authoritative class = per-(meet,race) override if present, else the raw
Timed-final-duplicating-a-prelim/final heuristic."""
from curate import classify


def _race(race_id, name, rtype):
    return {"race_id": race_id, "name": name, "type": rtype}


def test_heuristic_marks_timed_final_duplicate_as_para():
    races = [
        _race(1, "100 Fri - Damer", "Heats"),
        _race(2, "100 Fri - Damer", "Final"),
        _race(3, "100 Fri - Damer", "Timed final"),  # para: duplicates a prelim/final
        _race(4, "800 Fri - Damer", "Timed final"),   # open: no prelim/final twin
    ]
    resolved = classify.authoritative_class(races, overrides={})
    assert resolved == {1: "open", 2: "open", 3: "para", 4: "open"}


def test_override_wins_over_heuristic():
    races = [_race(9, "50 Fri - Herrer", "Timed final")]  # heuristic -> open
    resolved = classify.authoritative_class(races, overrides={9: "para"})
    assert resolved == {9: "para"}


def test_override_can_force_open():
    races = [
        _race(1, "100 Fri - Damer", "Heats"),
        _race(2, "100 Fri - Damer", "Final"),
        _race(3, "100 Fri - Damer", "Timed final"),  # heuristic -> para
    ]
    resolved = classify.authoritative_class(races, overrides={3: "open"})
    assert resolved[3] == "open"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.classify'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/classify.py`:

```python
"""Authoritative open/para class for curated races.

Override-else-heuristic. The heuristic mirrors the raw zone's rule: a 'Timed
final' whose event name also appears as a Heats/Final in the same meet is a para
event (an able-bodied direct final has no prelim/final twin)."""


def authoritative_class(races, overrides):
    """races: list of dicts with race_id, name, type. overrides: {race_id: class}.
    Returns {race_id: 'open'|'para'}."""
    prelim_final_names = {r["name"] for r in races
                          if r.get("type") in ("Heats", "Final")}
    resolved = {}
    for r in races:
        rid = r["race_id"]
        if rid in overrides:
            resolved[rid] = overrides[rid]
            continue
        is_para = r.get("type") == "Timed final" and r.get("name") in prelim_final_names
        resolved[rid] = "para" if is_para else "open"
    return resolved
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_classify.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/classify.py st-scrape/tests/test_curate_classify.py
git commit -m "feat: add authoritative class resolution (override-else-heuristic)"
```

---

## Task 4: Build curated rows from raw (model)

**Files:**
- Create: `st-scrape/curate/model.py`
- Test: `st-scrape/tests/test_curate_model.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_model.py`:

```python
"""Row builders: dim_meet, dim_race, fact_result (+ result_id, points),
fact_split, obt_result."""
from curate import model

MEET = {"meet_id": 8609, "meet": "DM Langbane 2021", "venue": "Aarhus",
        "course": "LCM", "season": 2021, "date": "08-07-2021",
        "category": ["DM-L", "DMJ-L"]}

RACES = [
    {"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Final", "class": "open"},
]

RESULTS = [
    {"race_id": 1, "Rank": 1, "Name": "A B", "Swimmer_id": "7", "nationality": "DK",
     "club": "C", "birth_year": 2001, "completed_time": "1:00.00",
     "completed_centiseconds": 6000,
     "splits": [{"distance": 50, "split_time": "29.00", "split_centiseconds": 2900,
                 "cumulative_time": "29.00", "cumulative_centiseconds": 2900}]},
    {"race_id": 1, "Rank": -1, "Name": "DQ One", "Swimmer_id": "8", "nationality": "DK",
     "club": "C", "birth_year": 2002, "completed_time": "DQ",
     "completed_centiseconds": None, "splits": []},
    {"race_id": 1, "Rank": -1, "Name": "DQ Two", "Swimmer_id": "9", "nationality": "DK",
     "club": "C", "birth_year": 2003, "completed_time": "DQ",
     "completed_centiseconds": None, "splits": []},
]


def test_dim_meet_row():
    row = model.build_dim_meet(MEET)
    assert row == {"meet_id": "8609", "meet_name": "DM Langbane 2021",
                   "venue": "Aarhus", "course": "LCM", "season": 2021,
                   "meet_date": "08-07-2021", "category": ["DM-L", "DMJ-L"]}


def test_dim_race_carries_authoritative_class_and_partitions():
    rows = model.build_dim_race(RACES, {1: "para"}, season=2021, course="LCM")
    assert rows[0]["class"] == "para"
    assert rows[0]["season"] == 2021 and rows[0]["course"] == "LCM"
    assert rows[0]["race_id"] == 1 and rows[0]["meet_id"] == "8609"


def test_result_id_uses_ordinal_not_rank_so_dqs_dont_collide():
    table = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    races_by_id = {1: RACES[0]}
    rows = model.build_fact_result(RESULTS, races_by_id, {1: "open"}, table,
                                   meet_id="8609", season=2021, course="LCM")
    ids = [r["result_id"] for r in rows]
    assert ids == ["1-0", "1-1", "1-2"]   # two DQs do NOT collide
    # First row scored (base 60.0 vs 60.0 swim -> 1000); DQs unscored.
    assert rows[0]["points"] == 1000 and rows[0]["points_fixed"] is None
    assert rows[1]["points"] is None and rows[2]["points"] is None
    assert rows[0]["rank"] == 1 and rows[0]["swimmer_id"] == "7"


def test_fact_split_keys_to_result_id():
    rows = model.build_fact_split(RESULTS, meet_id="8609", season=2021, course="LCM")
    assert len(rows) == 1                 # only the first result has splits
    assert rows[0]["result_id"] == "1-0"
    assert rows[0]["distance"] == 50 and rows[0]["split_centiseconds"] == 2900


def test_obt_inlines_meet_and_race_attributes():
    table = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    races_by_id = {1: RACES[0]}
    fact = model.build_fact_result(RESULTS, races_by_id, {1: "open"}, table,
                                   meet_id="8609", season=2021, course="LCM")
    obt = model.build_obt(fact, MEET, races_by_id, {1: "open"})
    assert obt[0]["meet_name"] == "DM Langbane 2021"
    assert obt[0]["race_name"] == "100 Fri - Damer"
    assert obt[0]["stroke"] == "Fri" and obt[0]["class"] == "open"
    assert obt[0]["result_id"] == "1-0" and obt[0]["points"] == 1000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.model'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/model.py`:

```python
"""Build curated table rows from raw meet/race/result dicts.

result_id is race-local ordinal (f"{race_id}-{i}"), NOT Rank: disqualified swims
share Rank=-1 and would collide. Raw file order is deterministic, so ordinals are
stable across re-runs."""
from curate import points as points_mod


def build_dim_meet(meet):
    return {
        "meet_id": str(meet["meet_id"]),
        "meet_name": meet.get("meet", ""),
        "venue": meet.get("venue", ""),
        "course": meet["course"],
        "season": meet["season"],
        "meet_date": meet.get("date", ""),
        "category": list(meet.get("category", [])),
    }


def build_dim_race(races, class_by_id, *, season, course):
    rows = []
    for r in races:
        rows.append({
            "race_id": r["race_id"],
            "meet_id": str(r["meet_id"]),
            "number": r.get("number"),
            "name": r["name"],
            "distance": r["distance"],
            "stroke": r["stroke"],
            "gender": r["gender"],
            "relay_count": r["relay_count"],
            "type": r["type"],
            "class": class_by_id[r["race_id"]],
            "season": season,
            "course": course,
        })
    return rows


def _result_ids(results):
    """Assign race-local ordinal ids in raw file order."""
    counters, ids = {}, []
    for r in results:
        rid = r["race_id"]
        i = counters.get(rid, 0)
        ids.append(f"{rid}-{i}")
        counters[rid] = i + 1
    return ids


def build_fact_result(results, races_by_id, class_by_id, base_times, *,
                      meet_id, season, course):
    ids = _result_ids(results)
    rows = []
    for result_id, r in zip(ids, results):
        race = races_by_id.get(r["race_id"])
        cs = r.get("completed_centiseconds")
        if race is None:
            p = pf = None
        else:
            p, pf = points_mod.score_result(
                base_times, season, course, race,
                klass=class_by_id.get(r["race_id"], "open"),
                completed_centiseconds=cs, rank=r.get("Rank"))
        rows.append({
            "result_id": result_id,
            "race_id": r["race_id"],
            "meet_id": str(meet_id),
            "rank": r.get("Rank"),
            "name": r.get("Name", ""),
            "swimmer_id": r.get("Swimmer_id"),
            "nationality": r.get("nationality"),
            "club": r.get("club"),
            "birth_year": r.get("birth_year"),
            "completed_time": r.get("completed_time"),
            "completed_centiseconds": cs,
            "points": p,
            "points_fixed": pf,
            "season": season,
            "course": course,
        })
    return rows


def build_fact_split(results, *, meet_id, season, course):
    ids = _result_ids(results)
    rows = []
    for result_id, r in zip(ids, results):
        for s in r.get("splits", []):
            rows.append({
                "result_id": result_id,
                "race_id": r["race_id"],
                "distance": s.get("distance"),
                "split_time": s.get("split_time"),
                "split_centiseconds": s.get("split_centiseconds"),
                "cumulative_time": s.get("cumulative_time"),
                "cumulative_centiseconds": s.get("cumulative_centiseconds"),
                "season": season,
                "course": course,
            })
    return rows


def build_obt(fact_result_rows, meet, races_by_id, class_by_id):
    rows = []
    for fr in fact_result_rows:
        race = races_by_id.get(fr["race_id"], {})
        row = dict(fr)
        row.update({
            "meet_name": meet.get("meet", ""),
            "venue": meet.get("venue", ""),
            "meet_date": meet.get("date", ""),
            "number": race.get("number"),
            "race_name": race.get("name"),
            "distance": race.get("distance"),
            "stroke": race.get("stroke"),
            "gender": race.get("gender"),
            "relay_count": race.get("relay_count"),
            "type": race.get("type"),
            "class": class_by_id.get(fr["race_id"], "open"),
        })
        rows.append(row)
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_model.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/model.py st-scrape/tests/test_curate_model.py
git commit -m "feat: add curated row builders with ordinal result_id"
```

---

## Task 5: Pure transform_meet orchestration

**Files:**
- Create: `st-scrape/curate/transform.py`
- Test: `st-scrape/tests/test_curate_transform.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_transform.py`:

```python
"""transform_meet ties model builders together from parsed raw dicts."""
from curate import transform

MEET = {"meet_id": 8609, "meet": "DM L 2021", "venue": "Aarhus", "course": "LCM",
        "season": 2021, "date": "08-07-2021", "category": ["DM-L"]}
RACES = [
    {"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Final", "class": "open"},
    {"meet_id": 8609, "race_id": 2, "number": 2, "name": "100 Fri - Damer",
     "distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1,
     "type": "Timed final", "class": "open"},   # para by heuristic (dup of race 1)
]
RESULTS = [
    {"race_id": 1, "Rank": 1, "Name": "A", "Swimmer_id": "7", "completed_time": "1:00.00",
     "completed_centiseconds": 6000, "splits": []},
    {"race_id": 2, "Rank": 1, "Name": "P", "Swimmer_id": "8", "completed_time": "1:10.00",
     "completed_centiseconds": 7000, "splits": []},
]


def test_transform_produces_all_tables_and_para_is_unscored():
    base_times = {(2021, "LCM", "F", 1, 100, "FREE"): 60.0}
    tables = transform.transform_meet(MEET, RACES, RESULTS, base_times, overrides={})
    assert set(tables) == {"dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"}
    assert len(tables["dim_meet"]) == 1
    # Race 2 is para (Timed final duplicating race 1's name) -> dim_race says so.
    race_class = {r["race_id"]: r["class"] for r in tables["dim_race"]}
    assert race_class == {1: "open", 2: "para"}
    # Open result scored, para result unscored.
    pts = {r["race_id"]: r["points"] for r in tables["fact_result"]}
    assert pts[1] == 1000 and pts[2] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_transform.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.transform'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/transform.py`:

```python
"""Pure curated transform: parsed raw dicts -> {table_name: [row dicts]}."""
from curate import classify, model


def transform_meet(meet, races, results, base_times, overrides):
    """meet: dict. races/results: lists of dicts. base_times: lookup table.
    overrides: {race_id: 'open'|'para'}. Returns the five curated tables."""
    season, course = meet["season"], meet["course"]
    class_by_id = classify.authoritative_class(races, overrides)
    races_by_id = {r["race_id"]: r for r in races}

    fact_result = model.build_fact_result(
        results, races_by_id, class_by_id, base_times,
        meet_id=meet["meet_id"], season=season, course=course)

    return {
        "dim_meet": [model.build_dim_meet(meet)],
        "dim_race": model.build_dim_race(races, class_by_id, season=season, course=course),
        "fact_result": fact_result,
        "fact_split": model.build_fact_split(
            results, meet_id=meet["meet_id"], season=season, course=course),
        "obt_result": model.build_obt(fact_result, meet, races_by_id, class_by_id),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_transform.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/transform.py st-scrape/tests/test_curate_transform.py
git commit -m "feat: add pure transform_meet orchestration"
```

---

## Task 6: Parquet schemas + writer + partition paths

**Files:**
- Create: `st-scrape/curate/parquet.py`
- Test: `st-scrape/tests/test_curate_parquet.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_parquet.py`:

```python
"""Parquet writer: round-trips rows, handles nulls, and builds partition paths."""
import io

import pyarrow.parquet as pq

from curate import parquet


def test_partition_path_per_meet():
    assert parquet.object_key("fact_result", season=2021, course="LCM", meet_id="8609") == \
        "curated/fact_result/season=2021/course=LCM/meet=8609.parquet"


def test_write_round_trips_with_nulls():
    rows = [
        {"result_id": "1-0", "points": 1000, "points_fixed": None,
         "season": 2021, "course": "LCM"},
        {"result_id": "1-1", "points": None, "points_fixed": None,
         "season": 2021, "course": "LCM"},
    ]
    data = parquet.write_parquet_bytes("fact_result", rows)
    table = pq.read_table(io.BytesIO(data))
    out = table.to_pylist()
    assert out[0]["result_id"] == "1-0" and out[0]["points"] == 1000
    assert out[1]["points"] is None


def test_empty_rows_still_writes_valid_schema():
    data = parquet.write_parquet_bytes("fact_split", [])
    table = pq.read_table(io.BytesIO(data))
    assert table.num_rows == 0
    assert "result_id" in table.schema.names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_parquet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.parquet'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/parquet.py`:

```python
"""Parquet schemas + writer + S3 object keys for the curated zone.

Explicit pyarrow schemas (not inferred) so an empty meet still writes a
well-typed file and the Glue catalog stays stable."""
import io

import pyarrow as pa
import pyarrow.parquet as pq

_S = pa.string()
_I = pa.int64()

SCHEMAS = {
    "dim_meet": pa.schema([
        ("meet_id", _S), ("meet_name", _S), ("venue", _S), ("course", _S),
        ("season", _I), ("meet_date", _S), ("category", pa.list_(_S)),
    ]),
    "dim_race": pa.schema([
        ("race_id", _I), ("meet_id", _S), ("number", _I), ("name", _S),
        ("distance", _I), ("stroke", _S), ("gender", _S), ("relay_count", _I),
        ("type", _S), ("class", _S), ("season", _I), ("course", _S),
    ]),
    "fact_result": pa.schema([
        ("result_id", _S), ("race_id", _I), ("meet_id", _S), ("rank", _I),
        ("name", _S), ("swimmer_id", _S), ("nationality", _S), ("club", _S),
        ("birth_year", _I), ("completed_time", _S), ("completed_centiseconds", _I),
        ("points", _I), ("points_fixed", _I), ("season", _I), ("course", _S),
    ]),
    "fact_split": pa.schema([
        ("result_id", _S), ("race_id", _I), ("distance", _I), ("split_time", _S),
        ("split_centiseconds", _I), ("cumulative_time", _S),
        ("cumulative_centiseconds", _I), ("season", _I), ("course", _S),
    ]),
    "obt_result": pa.schema([
        ("result_id", _S), ("race_id", _I), ("meet_id", _S), ("rank", _I),
        ("name", _S), ("swimmer_id", _S), ("nationality", _S), ("club", _S),
        ("birth_year", _I), ("completed_time", _S), ("completed_centiseconds", _I),
        ("points", _I), ("points_fixed", _I), ("season", _I), ("course", _S),
        ("meet_name", _S), ("venue", _S), ("meet_date", _S), ("number", _I),
        ("race_name", _S), ("distance", _I), ("stroke", _S), ("gender", _S),
        ("relay_count", _I), ("type", _S), ("class", _S),
    ]),
}


def object_key(table, *, season, course, meet_id):
    return (f"curated/{table}/season={season}/course={course}/"
            f"meet={meet_id}.parquet")


def write_parquet_bytes(table, rows):
    """Serialize rows to Snappy Parquet bytes using the table's fixed schema.
    Missing keys become nulls; extra keys are ignored."""
    schema = SCHEMAS[table]
    columns = {name: [row.get(name) for row in rows] for name in schema.names}
    arrays = [pa.array(columns[name], type=field.type)
              for name, field in zip(schema.names, schema)]
    arrow_table = pa.table(arrays, schema=schema)
    buf = io.BytesIO()
    pq.write_table(arrow_table, buf, compression="snappy")
    return buf.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_parquet.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/parquet.py st-scrape/tests/test_curate_parquet.py
git commit -m "feat: add curated Parquet schemas, writer, and object keys"
```

---

## Task 7: Class-overrides DynamoDB access layer

**Files:**
- Create: `st-scrape/curate/overrides.py`
- Test: `st-scrape/tests/test_curate_overrides.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_overrides.py`:

```python
"""Class-overrides table: set/list/get-for-meet."""
import boto3
import pytest

from curate.overrides import ClassOverrides

REGION = "eu-west-1"
TABLE = "swimtrends-class-overrides-test"


@pytest.fixture
def overrides_table(mocked_aws):
    ddb = boto3.resource("dynamodb", region_name=REGION)
    ddb.create_table(
        TableName=TABLE,
        KeySchema=[{"AttributeName": "meet_id", "KeyType": "HASH"},
                   {"AttributeName": "race_id", "KeyType": "RANGE"}],
        AttributeDefinitions=[{"AttributeName": "meet_id", "AttributeType": "S"},
                              {"AttributeName": "race_id", "AttributeType": "N"}],
        BillingMode="PAY_PER_REQUEST",
    )
    yield ddb.Table(TABLE)


def test_set_then_get_for_meet_returns_race_id_to_class(overrides_table):
    ov = ClassOverrides(TABLE, region=REGION)
    ov.set_override("8609", 213, "para", reason="para-only event")
    ov.set_override("8609", 99, "open", reason="false positive")
    ov.set_override("9999", 1, "para", reason="other meet")
    assert ov.get_for_meet("8609") == {213: "para", 99: "open"}


def test_get_for_meet_empty_when_none(overrides_table):
    ov = ClassOverrides(TABLE, region=REGION)
    assert ov.get_for_meet("8609") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_overrides.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.overrides'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/overrides.py`:

```python
"""DynamoDB access for per-(meet,race) authoritative class overrides.

Partition key meet_id (S), sort key race_id (N). Sparse: only the handful of
races the heuristic gets wrong."""
import boto3
from boto3.dynamodb.conditions import Key


class ClassOverrides:
    def __init__(self, table_name, region=None):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def set_override(self, meet_id, race_id, klass, reason=""):
        if klass not in ("open", "para"):
            raise ValueError(f"class must be 'open' or 'para', got {klass!r}")
        self._table.put_item(Item={
            "meet_id": str(meet_id), "race_id": int(race_id),
            "class": klass, "reason": reason,
        })

    def get_for_meet(self, meet_id):
        """Return {race_id(int): class} for one meet."""
        resp = self._table.query(
            KeyConditionExpression=Key("meet_id").eq(str(meet_id)))
        return {int(i["race_id"]): i["class"] for i in resp.get("Items", [])}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_overrides.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/overrides.py st-scrape/tests/test_curate_overrides.py
git commit -m "feat: add class-overrides DynamoDB access layer"
```

---

## Task 8: Base-times loader (from S3 or local file)

**Files:**
- Create: `st-scrape/curate/basetimes.py`
- Test: `st-scrape/tests/test_curate_basetimes.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_basetimes.py`:

```python
"""Base-times loader parses JSONL into the (season,course,gender,relay,dist,stroke)
-> seconds lookup the points module expects."""
from curate import basetimes

JSONL = (
    '{"season": 2022, "course": "LCM", "gender": "F", "relay_count": 1, '
    '"distance": 100, "stroke": "FREE", "basetime": "51.71", "basetime_in_sec": 51.71}\n'
    '{"season": 2026, "course": "LCM", "gender": "F", "relay_count": 1, '
    '"distance": 100, "stroke": "FREE", "basetime": "50.00", "basetime_in_sec": 50.0}\n'
)


def test_parse_jsonl_to_lookup():
    table = basetimes.parse(JSONL)
    assert table[(2022, "LCM", "F", 1, 100, "FREE")] == 51.71
    assert table[(2026, "LCM", "F", 1, 100, "FREE")] == 50.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_basetimes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.basetimes'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/basetimes.py`:

```python
"""Load the WA base-times reference into the lookup the points module uses.

Keyed (season, course, gender, relay_count, distance, stroke) -> seconds."""
import json


def parse(jsonl_text):
    table = {}
    for line in jsonl_text.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        table[(r["season"], r["course"], r["gender"], r["relay_count"],
               r["distance"], r["stroke"])] = r["basetime_in_sec"]
    return table
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_basetimes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/basetimes.py st-scrape/tests/test_curate_basetimes.py
git commit -m "feat: add base-times JSONL loader for curated points"
```

---

## Task 9: run_curate_task orchestration (injected I/O) + main

**Files:**
- Create: `st-scrape/curate/run.py`
- Test: `st-scrape/tests/test_curate_run.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_run.py`:

```python
"""run_curate_task: read raw -> transform -> write curated parquet -> notify.
All I/O injected; verifies object keys, overwrite-by-meet, and notification."""
import io

import pyarrow.parquet as pq

from curate import run

MEET = ('{"meet_id": 8609, "meet": "DM L 2021", "venue": "Aarhus", '
        '"course": "LCM", "season": 2021, "date": "08-07-2021", "category": ["DM-L"]}')
RACES = (
    '{"meet_id": 8609, "race_id": 1, "number": 1, "name": "100 Fri - Damer", '
    '"distance": 100, "stroke": "Fri", "gender": "F", "relay_count": 1, '
    '"type": "Final", "class": "open"}\n'
)
RESULTS = (
    '{"race_id": 1, "Rank": 1, "Name": "A", "Swimmer_id": "7", '
    '"completed_time": "1:00.00", "completed_centiseconds": 6000, "splits": []}\n'
)
BASE_TIMES = ('{"season": 2021, "course": "LCM", "gender": "F", "relay_count": 1, '
              '"distance": 100, "stroke": "FREE", "basetime_in_sec": 60.0}\n')


def test_run_writes_all_five_tables_and_notifies():
    raw = {
        "raw/meet=8609/meet_info.jsonl": MEET,
        "raw/meet=8609/races.jsonl": RACES,
        "raw/meet=8609/results.jsonl": RESULTS,
        "reference/point_base_times.jsonl": BASE_TIMES,
    }
    written, notes = {}, []

    run.run_curate_task(
        meet_id="8609",
        read_text=lambda key: raw[key],
        get_overrides=lambda mid: {},
        write_bytes=lambda key, data: written.__setitem__(key, data),
        notify=lambda subject, msg: notes.append(subject),
    )

    assert set(written) == {
        "curated/dim_meet/season=2021/course=LCM/meet=8609.parquet",
        "curated/dim_race/season=2021/course=LCM/meet=8609.parquet",
        "curated/fact_result/season=2021/course=LCM/meet=8609.parquet",
        "curated/fact_split/season=2021/course=LCM/meet=8609.parquet",
        "curated/obt_result/season=2021/course=LCM/meet=8609.parquet",
    }
    fr = pq.read_table(io.BytesIO(
        written["curated/fact_result/season=2021/course=LCM/meet=8609.parquet"]))
    assert fr.to_pylist()[0]["points"] == 1000
    assert any("curat" in s.lower() for s in notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_run.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.run'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/run.py`:

```python
"""Curated transform task entrypoint.

run_curate_task() is pure-ish orchestration with all I/O injected (read_text,
get_overrides, write_bytes, notify) so it unit-tests without AWS. main() wires
the real boto3 implementations and is the Fargate container entry."""
import json
import os

from curate import basetimes, parquet, transform

RAW_PREFIX = "raw/meet={meet_id}/"
BASE_TIMES_KEY = "reference/point_base_times.jsonl"


def _read_jsonl(read_text, key):
    return [json.loads(l) for l in read_text(key).splitlines() if l.strip()]


def run_curate_task(*, meet_id, read_text, get_overrides, write_bytes, notify):
    """Transform one meet's raw zone into curated Parquet. Re-raises on failure
    after notifying, so the container exits non-zero."""
    try:
        prefix = RAW_PREFIX.format(meet_id=meet_id)
        meet = _read_jsonl(read_text, prefix + "meet_info.jsonl")[0]
        races = _read_jsonl(read_text, prefix + "races.jsonl")
        results = _read_jsonl(read_text, prefix + "results.jsonl")
        base_times = basetimes.parse(read_text(BASE_TIMES_KEY))
        overrides = get_overrides(meet_id)

        tables = transform.transform_meet(meet, races, results, base_times, overrides)
        season, course = meet["season"], meet["course"]
        counts = {}
        for table_name, rows in tables.items():
            key = parquet.object_key(table_name, season=season, course=course,
                                     meet_id=meet_id)
            write_bytes(key, parquet.write_parquet_bytes(table_name, rows))
            counts[table_name] = len(rows)

        notify("Swimtrends curate SUCCEEDED",
               f"Meet {meet_id} ({meet.get('meet','')}) curated: {counts}")
        return counts
    except Exception as e:
        notify("Swimtrends curate FAILED", f"Meet {meet_id}: {e}")
        raise


def main():
    import boto3

    from curate.overrides import ClassOverrides

    meet_id = os.environ["MEET_ID"]
    bucket = os.environ["CURATED_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]
    overrides = ClassOverrides(os.environ["OVERRIDES_TABLE"])

    s3 = boto3.client("s3")
    sns = boto3.client("sns")

    def read_text(key):
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    def write_bytes(key, data):
        s3.put_object(Bucket=bucket, Key=key, Body=data)

    run_curate_task(
        meet_id=meet_id,
        read_text=read_text,
        get_overrides=overrides.get_for_meet,
        write_bytes=write_bytes,
        notify=lambda subject, msg: sns.publish(
            TopicArn=topic_arn, Subject=subject[:100], Message=msg),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_run.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: all green (Spec 1 suite + new curate tests).

- [ ] **Step 6: Commit**

```bash
git add st-scrape/curate/run.py st-scrape/tests/test_curate_run.py
git commit -m "feat: add run_curate_task orchestration and container main"
```

---

## Task 10: CLI subcommands (curate, class, basetimes)

**Files:**
- Modify: `st-scrape/ingestion/cli.py`
- Test: `st-scrape/tests/test_cli_curate.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_cli_curate.py`:

```python
"""CLI curate/class subcommands route to the right injected side effects."""
from ingestion import cli


class FakeRegistry:
    def __init__(self, ids):
        self._ids = ids

    def scheduled_meets(self):  # unused here but matches interface
        return []

    def all_meet_ids(self):
        return self._ids


class FakeOverrides:
    def __init__(self):
        self.calls = []

    def set_override(self, meet_id, race_id, klass, reason=""):
        self.calls.append((meet_id, race_id, klass, reason))


def test_curate_single_meet_invokes_curator():
    invoked = []
    cli.run(["curate", "8609"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload), overrides=None)
    assert invoked == [{"meet_ids": ["8609"]}]


def test_curate_all_invokes_with_all_flag():
    invoked = []
    cli.run(["curate", "--all"], registry=None, invoke=None,
            curate=lambda payload: invoked.append(payload), overrides=None)
    assert invoked == [{"all": True}]


def test_class_set_writes_override():
    ov = FakeOverrides()
    cli.run(["class", "set", "8609", "213", "para", "--reason", "para-only"],
            registry=None, invoke=None, curate=None, overrides=ov)
    assert ov.calls == [("8609", 213, "para", "para-only")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_cli_curate.py -v`
Expected: FAIL — `run()` does not accept `curate`/`overrides` kwargs.

- [ ] **Step 3: Extend the CLI**

In `st-scrape/ingestion/cli.py`, add parsers inside `build_parser()` (after the `disp` parser, before `return parser`):

```python
    cur = sub.add_parser("curate", help="Run the curated transform.")
    cur.add_argument("meet_id", nargs="?", default=None)
    cur.add_argument("--all", action="store_true",
                     help="Curate every meet (full rebuild).")

    cls = sub.add_parser("class", help="Manage authoritative class overrides.")
    cls_sub = cls.add_subparsers(dest="class_command", required=True)
    cls_set = cls_sub.add_parser("set", help="Set an override for one race.")
    cls_set.add_argument("meet_id")
    cls_set.add_argument("race_id", type=int)
    cls_set.add_argument("klass", choices=["open", "para"])
    cls_set.add_argument("--reason", default="")
```

Change the `run()` signature and add the new branches. Replace
`def run(argv, *, registry, invoke):` with:

```python
def run(argv, *, registry, invoke, curate=None, overrides=None):
    """Execute one CLI command. registry/invoke/curate/overrides injected."""
```

Then, before the final implicit return of `run()`, add:

```python
    if args.command == "curate":
        if args.all and args.meet_id:
            raise SystemExit("Pass a meet_id OR --all, not both.")
        payload = {"all": True} if args.all else {"meet_ids": [args.meet_id]}
        if not args.all and not args.meet_id:
            raise SystemExit("curate needs a meet_id or --all.")
        curate(payload)
        print(f"Curate invoked with payload: {json.dumps(payload)}")
        return

    if args.command == "class":
        if args.class_command == "set":
            overrides.set_override(args.meet_id, args.race_id, args.klass,
                                   reason=args.reason)
            print(f"Override set: meet {args.meet_id} race {args.race_id} "
                  f"-> {args.klass}")
        return
```

Update `main()` to construct the new injected dependencies. After the existing
`lambda_client`/`function_name` setup, add:

```python
    from curate.overrides import ClassOverrides

    overrides = ClassOverrides(os.environ["OVERRIDES_TABLE"]) \
        if os.environ.get("OVERRIDES_TABLE") else None
    curator_fn = os.environ.get("CURATOR_FUNCTION")

    def curate(payload):
        if curator_fn is None:
            raise SystemExit("CURATOR_FUNCTION not set.")
        resp = lambda_client.invoke(
            FunctionName=curator_fn, InvocationType="Event",
            Payload=json.dumps(payload).encode("utf-8"))
        return resp["StatusCode"]
```

and change the final call to:

```python
    run(sys.argv[1:], registry=registry, invoke=invoke,
        curate=curate, overrides=overrides)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_cli_curate.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the existing CLI tests for no regressions**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_cli.py -v`
Expected: PASS — existing `cli.run(...)` calls still work because `curate`/`overrides` default to `None`.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/ingestion/cli.py st-scrape/tests/test_cli_curate.py
git commit -m "feat: add curate and class CLI subcommands"
```

---

## Task 11: Glue catalog table definitions

**Files:**
- Create: `st-scrape/curate/catalog.py`
- Test: `st-scrape/tests/test_curate_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `st-scrape/tests/test_curate_catalog.py`:

```python
"""Glue table input is derived from the same schema, partitioned by season/course."""
from curate import catalog


def test_table_input_has_partition_keys_and_columns():
    ti = catalog.table_input("fact_result", "s3://bucket/curated/fact_result/")
    assert ti["Name"] == "fact_result"
    part_keys = [c["Name"] for c in ti["PartitionKeys"]]
    assert part_keys == ["season", "course"]
    col_names = [c["Name"] for c in ti["StorageDescriptor"]["Columns"]]
    # Partition columns must NOT also appear in Columns (Glue rejects overlap).
    assert "season" not in col_names and "course" not in col_names
    assert "result_id" in col_names and "points" in col_names
    assert ti["StorageDescriptor"]["Location"] == "s3://bucket/curated/fact_result/"


def test_all_five_tables_supported():
    for name in ["dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"]:
        ti = catalog.table_input(name, f"s3://bucket/curated/{name}/")
        assert ti["Name"] == name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'curate.catalog'`.

- [ ] **Step 3: Write minimal implementation**

Create `st-scrape/curate/catalog.py`:

```python
"""Glue Data Catalog table definitions derived from the Parquet schemas.

season/course are partition keys (encoded in the S3 path), so they are declared
as PartitionKeys and excluded from the regular column list."""
import pyarrow as pa

from curate import parquet

PARTITION_COLS = ("season", "course")

_ARROW_TO_GLUE = {pa.string(): "string", pa.int64(): "bigint"}


def _glue_type(arrow_type):
    if pa.types.is_list(arrow_type):
        inner = _ARROW_TO_GLUE[arrow_type.value_type]
        return f"array<{inner}>"
    return _ARROW_TO_GLUE[arrow_type]


def table_input(table, location):
    """Return a Glue CreateTable 'TableInput' dict for one curated table."""
    schema = parquet.SCHEMAS[table]
    columns = [{"Name": f.name, "Type": _glue_type(f.type)}
               for f in schema if f.name not in PARTITION_COLS]
    return {
        "Name": table,
        "TableType": "EXTERNAL_TABLE",
        "Parameters": {"classification": "parquet", "EXTERNAL": "TRUE"},
        "PartitionKeys": [
            {"Name": "season", "Type": "bigint"},
            {"Name": "course", "Type": "string"},
        ],
        "StorageDescriptor": {
            "Columns": columns,
            "Location": location,
            "InputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "OutputFormat": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "SerdeInfo": {
                "SerializationLibrary":
                    "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
            },
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_curate_catalog.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add st-scrape/curate/catalog.py st-scrape/tests/test_curate_catalog.py
git commit -m "feat: add Glue table definitions for curated tables"
```

---

## Task 12: Curated container image entrypoint

**Files:**
- Modify: `st-scrape/Dockerfile`
- Create: `st-scrape/Dockerfile.curate`

The Spec 1 `Dockerfile` ENTRYPOINT is the scraper. The curated task needs its own
entrypoint but can share the codebase. Use a dedicated Dockerfile that copies the
`curate/` package and runs `python -m curate.run`.

- [ ] **Step 1: Create the curate Dockerfile**

Create `st-scrape/Dockerfile.curate`:

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared scraper module (for any reuse) + the curate package.
COPY scrape_races.py .
COPY curate/ ./curate/

# Reads MEET_ID / CURATED_BUCKET / OVERRIDES_TABLE / SNS_TOPIC_ARN from the env.
ENTRYPOINT ["python", "-m", "curate.run"]
```

- [ ] **Step 2: Build the image locally to verify it assembles**

Run: `cd st-scrape && docker build -f Dockerfile.curate -t swimtrends-curate:test .`
Expected: build succeeds; `docker run --rm swimtrends-curate:test` exits with a
`KeyError: 'MEET_ID'` (env not set) — confirming the entrypoint runs.

- [ ] **Step 3: Commit**

```bash
git add st-scrape/Dockerfile.curate
git commit -m "build: add curated transform container image"
```

---

## Task 13: CDK SwimtrendsCuratedStack

**Files:**
- Create: `swimtrends-app/swimtrends_app/swimtrends_curated_stack.py`
- Modify: `swimtrends-app/app.py`
- Test: `swimtrends-app/tests/unit/test_curated_stack.py`

- [ ] **Step 1: Write the failing CDK assertion test**

Create `swimtrends-app/tests/unit/test_curated_stack.py`:

```python
"""Synth assertions for the curated stack: overrides table, curated task,
trigger Lambda, Glue database + tables."""
import aws_cdk as cdk
from aws_cdk import assertions

from swimtrends_app.swimtrends_curated_stack import SwimtrendsCuratedStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")


def _template():
    app = cdk.App()
    stack = SwimtrendsCuratedStack(app, "TestCurated", alert_email=None, env=ENV)
    return assertions.Template.from_stack(stack)


def test_overrides_table_has_composite_key():
    t = _template()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "swimtrends-class-overrides",
        "KeySchema": [
            {"AttributeName": "meet_id", "KeyType": "HASH"},
            {"AttributeName": "race_id", "KeyType": "RANGE"},
        ],
    })


def test_glue_database_and_five_tables():
    t = _template()
    t.resource_count_is("AWS::Glue::Database", 1)
    t.resource_count_is("AWS::Glue::Table", 5)


def test_trigger_lambda_exists():
    t = _template()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "curate_trigger.lambda_handler",
    })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit/test_curated_stack.py -v`
Expected: FAIL — `ModuleNotFoundError: swimtrends_app.swimtrends_curated_stack`.

- [ ] **Step 3: Write the stack**

Create `swimtrends-app/swimtrends_app/swimtrends_curated_stack.py`:

```python
"""Swimtrends curated zone (Spec 2 of 3).

A class-overrides DynamoDB table, a Fargate task that runs the curated transform,
an S3-event trigger Lambda (raw results.jsonl -> RunTask), a Glue database with
one table per curated dataset, and SNS alerts. Reuses the swimtrends-meet-data
bucket and the ingestion ECS cluster by name."""
import os
import sys

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

ST_SCRAPE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "st-scrape"))
sys.path.insert(0, ST_SCRAPE_DIR)
from curate import catalog  # noqa: E402  (import after path insert)

CONTAINER_NAME = "curate"
BUCKET_NAME = "swimtrends-meet-data"
CURATED_TABLES = ["dim_meet", "dim_race", "fact_result", "fact_split", "obt_result"]


class SwimtrendsCuratedStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 alert_email: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket.from_bucket_name(self, "DataBucket", BUCKET_NAME)

        overrides = dynamodb.Table(
            self, "ClassOverrides",
            table_name="swimtrends-class-overrides",
            partition_key=dynamodb.Attribute(
                name="meet_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(
                name="race_id", type=dynamodb.AttributeType.NUMBER),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        topic = sns.Topic(self, "CurateAlertTopic",
                          display_name="Swimtrends curate alerts")
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))

        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        sg = ec2.SecurityGroup(self, "CurateTaskSG", vpc=vpc,
                               allow_all_outbound=True,
                               description="Egress-only SG for the curate task")
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster", cluster_name="swimtrends-ingestion",
            vpc=vpc, security_groups=[])

        task_def = ecs.FargateTaskDefinition(
            self, "CurateTaskDef", cpu=512, memory_limit_mib=1024)
        task_def.add_container(
            CONTAINER_NAME,
            image=ecs.ContainerImage.from_asset(
                ST_SCRAPE_DIR, file="Dockerfile.curate"),
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="curate",
                log_retention=logs.RetentionDays.ONE_MONTH),
            environment={
                "CURATED_BUCKET": BUCKET_NAME,
                "OVERRIDES_TABLE": overrides.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
            },
        )
        bucket.grant_read(task_def.task_role, objects_key_pattern="raw/*")
        bucket.grant_read(task_def.task_role, objects_key_pattern="reference/*")
        bucket.grant_put(task_def.task_role, objects_key_pattern="curated/*")
        overrides.grant_read_data(task_def.task_role)
        topic.grant_publish(task_def.task_role)

        # --- S3-event trigger Lambda: raw results.jsonl lands -> RunTask ---
        trigger_fn = lambda_.Function(
            self, "CurateTrigger",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="curate_trigger.lambda_handler",
            timeout=Duration.minutes(1),
            memory_size=256,
            code=lambda_.Code.from_asset(
                os.path.join(os.path.dirname(__file__), "..", "lambda_curate_trigger")),
            environment={
                "ECS_CLUSTER": cluster.cluster_arn,
                "TASK_DEFINITION": task_def.task_definition_arn,
                "CONTAINER_NAME": CONTAINER_NAME,
                "SUBNET_IDS": ",".join(s.subnet_id for s in vpc.public_subnets),
                "SECURITY_GROUP_ID": sg.security_group_id,
            },
        )
        trigger_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ecs:RunTask"], resources=[task_def.task_definition_arn]))
        trigger_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[task_def.task_role.role_arn,
                       task_def.obtain_execution_role().role_arn]))

        bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(trigger_fn),
            s3.NotificationKeyFilter(prefix="raw/", suffix="results.jsonl"))

        # --- Glue catalog ---
        db = glue.CfnDatabase(
            self, "CuratedDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="swimtrends_curated"))
        for name in CURATED_TABLES:
            location = f"s3://{BUCKET_NAME}/curated/{name}/"
            ti = catalog.table_input(name, location)
            tbl = glue.CfnTable(
                self, f"Table{name}",
                catalog_id=self.account,
                database_name="swimtrends_curated",
                table_input=glue.CfnTable.TableInputProperty(
                    name=ti["Name"],
                    table_type=ti["TableType"],
                    parameters=ti["Parameters"],
                    partition_keys=[
                        glue.CfnTable.ColumnProperty(name=c["Name"], type=c["Type"])
                        for c in ti["PartitionKeys"]],
                    storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                        columns=[glue.CfnTable.ColumnProperty(
                            name=c["Name"], type=c["Type"])
                            for c in ti["StorageDescriptor"]["Columns"]],
                        location=location,
                        input_format=ti["StorageDescriptor"]["InputFormat"],
                        output_format=ti["StorageDescriptor"]["OutputFormat"],
                        serde_info=glue.CfnTable.SerdeInfoProperty(
                            serialization_library=ti["StorageDescriptor"]
                            ["SerdeInfo"]["SerializationLibrary"]))))
            tbl.add_dependency(db)
```

- [ ] **Step 4: Create the trigger Lambda source**

Create `swimtrends-app/lambda_curate_trigger/curate_trigger.py`:

```python
"""S3 ObjectCreated(raw/.../results.jsonl) -> RunTask the curate Fargate task
for that meet. Parses meet_id from the key 'raw/meet=<id>/results.jsonl'."""
import os
import re

import boto3

KEY_RE = re.compile(r"raw/meet=([^/]+)/results\.jsonl$")


def lambda_handler(event, context):
    ecs = boto3.client("ecs")
    launched = []
    for record in event.get("Records", []):
        key = record["s3"]["object"]["key"]
        m = KEY_RE.search(key)
        if not m:
            continue
        meet_id = m.group(1)
        ecs.run_task(
            cluster=os.environ["ECS_CLUSTER"],
            taskDefinition=os.environ["TASK_DEFINITION"],
            launchType="FARGATE",
            count=1,
            networkConfiguration={"awsvpcConfiguration": {
                "subnets": os.environ["SUBNET_IDS"].split(","),
                "securityGroups": [os.environ["SECURITY_GROUP_ID"]],
                "assignPublicIp": "ENABLED",
            }},
            overrides={"containerOverrides": [{
                "name": os.environ["CONTAINER_NAME"],
                "environment": [{"name": "MEET_ID", "value": meet_id}],
            }]},
        )
        launched.append(meet_id)
    return {"launched": launched}
```

- [ ] **Step 5: Wire the stack into app.py**

In `swimtrends-app/app.py`, add the import and instantiation:

```python
from swimtrends_app.swimtrends_curated_stack import SwimtrendsCuratedStack
```

and after the `SwimtrendsIngestionStack(...)` block:

```python
SwimtrendsCuratedStack(
    app, "SwimtrendsCuratedStack",
    alert_email=app.node.try_get_context("alert_email"),
    env=ENV,
)
```

- [ ] **Step 6: Run the CDK test to verify it passes**

Run: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit/test_curated_stack.py -v`
Expected: PASS (3 tests). The `glue` import requires `aws-cdk-lib` (already pinned).

- [ ] **Step 7: Synthesize to validate the whole app**

Run:
```bash
cd swimtrends-app
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk synth SwimtrendsCuratedStack --app ".venv/bin/python3 app.py" -c alert_email=mortench.privat@gmail.com >/dev/null
```
Expected: synth succeeds (no exceptions), emits CloudFormation.

- [ ] **Step 8: Commit**

```bash
git add swimtrends-app/swimtrends_app/swimtrends_curated_stack.py \
        swimtrends-app/lambda_curate_trigger/curate_trigger.py \
        swimtrends-app/app.py \
        swimtrends-app/tests/unit/test_curated_stack.py
git commit -m "feat: add SwimtrendsCuratedStack (overrides table, curate task, S3 trigger, Glue catalog)"
```

---

## Task 14: Deploy, seed base times, backfill curate

**Files:** none (operational).

- [ ] **Step 1: Generate and upload the base-times reference**

Run:
```bash
cd st-scrape
.venv/bin/python gen_base_times.py    # writes db/point_base_times.jsonl
AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 \
  aws s3 cp db/point_base_times.jsonl s3://swimtrends-meet-data/reference/point_base_times.jsonl
```
Expected: validation passes; object uploaded.

- [ ] **Step 2: Deploy the curated stack**

Run:
```bash
cd swimtrends-app
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk deploy SwimtrendsCuratedStack \
  --app ".venv/bin/python3 app.py" -c alert_email=mortench.privat@gmail.com \
  --require-approval never --ci
```
Expected: stack deploys (Docker must be running for the image asset).
**Note:** the S3 event notification mutates the shared bucket's config — confirm
no Spec 1 notification conflict (Spec 1 added none, so this is additive).

- [ ] **Step 3: Backfill — curate all already-scraped meets**

For each meet already in the raw zone, trigger the curate task. Quickest path is
to re-put the trigger or invoke the curator directly. Using a one-off RunTask per
meet (replace `<meet_id>`):
```bash
AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 \
  aws ecs run-task --cluster swimtrends-ingestion \
  --task-definition <CurateTaskDef-arn> --launch-type FARGATE \
  --network-configuration '{"awsvpcConfiguration":{"subnets":[...],"securityGroups":[...],"assignPublicIp":"ENABLED"}}' \
  --overrides '{"containerOverrides":[{"name":"curate","environment":[{"name":"MEET_ID","value":"<meet_id>"}]}]}'
```
Expected: each task writes `curated/<table>/season=.../course=.../meet=<id>.parquet`.

- [ ] **Step 4: Verify curated output and points**

Run:
```bash
AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 \
  aws s3 ls s3://swimtrends-meet-data/curated/ --recursive | head
```
Expected: Parquet files under all five table prefixes. Spot-check one
`obt_result` file (download + `pq.read_table`) and confirm `points` populated for
open results and `null` for para.

- [ ] **Step 5: Verify the Glue catalog resolves the partitions**

Run a partition repair / load so Glue sees the existing data (Athena, Spec 3, will
query it):
```bash
AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 \
  aws glue get-tables --database-name swimtrends_curated \
  --query 'TableList[].Name'
```
Expected: the five table names. (Partition discovery — crawler vs `MSCK`/Athena
`ALTER TABLE ADD PARTITION` — is finalized in Spec 3 when the query engine lands.)

- [ ] **Step 6: Final commit (docs/status, if any operational notes were added)**

```bash
git add -A
git commit -m "chore: curated zone deployed and backfilled" || echo "nothing to commit"
```

---

## Self-review notes

- **Spec coverage:** transform (T5), points (T2), base times (T8/T14), authoritative class + overrides (T3/T7/T10), splits flattening + `result_id` (T4), fact/dim + OBT (T4/T5/T6), Glue catalog (T11/T13), schema contract (the "Curated schemas" section + `parquet.SCHEMAS`), incremental trigger (T13 S3 event) + full rebuild (T10 `curate --all`, T14 backfill), CDK stack reusing bucket/cluster/SNS (T13), Fargate-Python engine (T9/T12). All Spec 2 in-scope items map to a task.
- **`result_id` correctness:** keyed by race-local ordinal, not `Rank`, because DQs share `Rank=-1` (verified against real raw data). Pinned in T4 test `test_result_id_uses_ordinal_not_rank_so_dqs_dont_collide`.
- **Naming consistency:** `score_result`, `authoritative_class`, `transform_meet`, `write_parquet_bytes`, `object_key`, `table_input`, `get_for_meet`, `set_override`, `run_curate_task` are used identically across tasks.
- **Open items deferred to plan-execution/Spec 3 (not blockers):** Glue partition discovery mechanism (crawler vs Athena DDL) is settled in Spec 3; `curate --all` server-side fan-out (T10 sends `{"all": true}`) needs the curator Lambda/handler to enumerate meets — for the backfill, T14 Step 3 drives RunTask per meet directly, so the `--all` server path can be implemented when the query layer needs it.
```
