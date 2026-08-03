# Digest Per-Entity Aggregates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the AI meet report two precomputed per-meet aggregates it cannot
derive for itself — a club medal table (new `Klubberne` section) and the
multi-title swimmers the top-10-by-points cutoff hides.

**Architecture:** Two new blocks in `webbuild/digest.py`, built by digest-local
SQL over the existing analytics views (no new view, no curate change). One new
section heading in `evaluation/agent.py` with both version constants bumped, and
four functions in `evaluation/check.py` taught that names, clubs and points now
live in more than one block. The SPA is untouched.

**Tech Stack:** Python 3.12, DuckDB SQL over curated Parquet views, pydantic
structured output, pytest. Everything runs from `st-scrape/` with
`.venv/bin/python`.

## Global Constraints

- Spec: [`docs/superpowers/specs/2026-08-03-digest-entity-aggregates-design.md`](../specs/2026-08-03-digest-entity-aggregates-design.md). It wins any disagreement with this plan.
- **TDD.** Write the failing test, run it, watch it fail, then implement.
- Title = `phase IN ('final', 'timed_final') AND rank = 1`; podium = same phases, `rank BETWEEN 1 AND 3`. Junior path: `junior_rank` instead of `rank`. Counted **per result row**, so a dead heat yields two titles.
- Threshold: `MIN_TITLES = 3`. Club table: `CLUB_N = 5`.
- Canonical stroke order for `strokes[]`: `Fri, Ryg, Bryst, Fly, IM, HM`.
- **Every ORDER BY feeding a LIMIT must be a total order.** The digest is part of the evaluation cache key, so an unstable row set silently invalidates cached reports and pays to regenerate them.
- Senior queries filter `class = 'open'`. Junior queries need no class filter — `junior_championship` already applies it.
- `swimmer_id` is used for grouping and tie-breaking but is **never emitted** — the digest names no ids.
- Every new digest key must be read with `.get(...)` in `check.py`: the test digests in `tests/test_evaluation_agent.py` do not carry them.
- Run the full suite before each commit: `cd st-scrape && .venv/bin/python -m pytest -q` (322 passing before this work).
- Commit per task. Branch `digest-entity-aggregates` already exists and holds the spec commit.

## Already verified while writing this plan

Do not re-derive these — they were run, not reasoned about:

- Every SQL query below was executed against the Task 1 fixtures, and **every expected value in every assertion is that run's actual output** (including `AGF 8/8/4`, `Sigma Swim Allerød 4/5/1`, and Mathias's `strokes == ["Bryst", "Fly", "IM"]`). If an assertion fails, suspect the implementation, not the number.
- `QUALIFY titles >= 3` referencing the window alias works in this DuckDB version.
- Six repeated builds of both blocks returned identical rows.
- Task 3's `check.py` edits were applied to a scratch copy and the whole existing `tests/test_evaluation_check.py` + `tests/test_evaluation_agent.py` suite (76 tests) still passed, so those edits are regression-free as written.

## File Structure

| File | Responsibility | Change |
| --- | --- | --- |
| `st-scrape/webbuild/digest.py` | The model's entire world: pure SQL per meet | Add `_CLUBS_SQL`, `_JUNIOR_CLUBS_SQL`, `_MULTI_TITLE_SQL`, `_JUNIOR_MULTI_TITLE_SQL`, `_multi_title_swimmers()`, two keys in `build()` |
| `st-scrape/tests/evaluation_fixtures.py` | Curated fixtures for digest tests | Add `multi_title_con()`, `junior_multi_title_con()` |
| `st-scrape/tests/test_digest.py` | Digest block behaviour | Add tests for both blocks |
| `st-scrape/evaluation/check.py` | Deterministic "no invented facts" gate | `_club_names()`, `_named_swimmers()`, `points_owners`, `genders_in_digest`, `_aggregate_values`, `check_attribution` masking |
| `st-scrape/tests/test_evaluation_check.py` | Gate behaviour | Add tests for the new blocks |
| `st-scrape/evaluation/agent.py` | Prompt, schema, versions, retry text | Fifth heading, `PROMPT_VERSION` 7, `SCHEMA_VERSION` 3, rules 3/10, word budget, misattribution retry |
| `st-scrape/tests/test_evaluation_agent.py` | Prompt/schema/guard behaviour | Fifth section in two hardcoded body lists, renamed test |
| `docs/analytics.md` | Evaluation reference | Five `ApplyGuardrail` calls per meet |
| `CLAUDE.md` | Agent guidance | Refresh the st-scrape test count |

---

### Task 1: The `clubs` block

**Files:**
- Modify: `st-scrape/webbuild/digest.py` (add after `_JUNIOR_TOP_SWIMS_SQL`, ~line 148; extend `build()` at lines 268-285)
- Modify: `st-scrape/tests/evaluation_fixtures.py` (append `multi_title_con`, `junior_multi_title_con`)
- Test: `st-scrape/tests/test_digest.py`

**Interfaces:**
- Consumes: `tests.analytics_fixtures.build_curated`, `analytics.loader.create_views`, and the module-private `_row(**kw)` / `_time(cs)` helpers already in `tests/evaluation_fixtures.py`.
- Produces: `digest.build(...)["clubs"]` — a list of at most 5 dicts with exactly the keys `club, swimmers, titles, podiums, rank`. `digest.CLUB_N = 5`. Two fixtures, `multi_title_con()` and `junior_multi_title_con()`, both also used by Task 2.

- [ ] **Step 1: Add the two fixtures**

Append to `st-scrape/tests/evaluation_fixtures.py`. These are also Task 2's
fixtures — every number in both tasks' assertions was verified against them.

```python
def multi_title_con() -> duckdb.DuckDBPyConnection:
    """One DM-L meet built to exercise both per-entity aggregates.

    Deliberate contents, each pinning one rule:
      * Mathias Christensen wins 4 finals across 3 strokes (the DM-L/10334
        shape) and is SECOND in a fifth -- a second place is not a title.
      * Anders Andersen and Anna Testsen win 3 each, so the block's tie on
        `titles` is broken by name; Anna's Ryg titles are entered before her
        Fri one, so canonical stroke order is observable.
      * Dobbelt Vinder wins 2: below the threshold, absent from the block.
      * A dead heat (two rank-1 rows in one event, same club) gives that club
        two titles from one event.
      * Heat Winner wins a HEAT with more points than anyone: not a title.
      * A class='para' swim with 999 points: invisible to both blocks.
      * Three filler clubs with no podiums and 3/2/1 swimmers: the top-5 cut
        and the `swimmers DESC` fallback ordering.
    """
    mid, season, mdate = "M2026", 2026, "2026-04-10"
    mname = "Multi Champs 2026"
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L"])]
    obt, rid = [], 0

    def add(sid, name, club, gender, distance, stroke, points, rank,
            phase="Final", klass="open"):
        nonlocal rid
        rid += 1
        cs = 6000 + rid
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, completed_time=_time(cs),
            completed_centiseconds=cs, points=points, points_fixed=points,
            season=season, meet_name=mname, meet_date=mdate, distance=distance,
            stroke=stroke, gender=gender, type=phase, **{"class": klass}))

    for g, d, st, p in [("M", 200, "IM", 764), ("M", 100, "Fly", 729),
                        ("M", 200, "Bryst", 725), ("M", 400, "IM", 715)]:
        add("m1", "Mathias Christensen", "Sigma Swim Allerød", g, d, st, p, 1)
    add("m1", "Mathias Christensen", "Sigma Swim Allerød", "M", 100, "Bryst", 690, 2)

    for d, p in [(50, 800), (100, 790), (200, 780)]:
        add("m2", "Anders Andersen", "AGF", "M", d, "Fri", p, 1)

    for d, st, p in [(100, "Ryg", 770), (200, "Ryg", 760), (100, "Fri", 750)]:
        add("m3", "Anna Testsen", "AGF", "F", d, st, p, 1)

    for d, p in [(50, 700), (100, 695)]:
        add("m4", "Dobbelt Vinder", "VEST", "F", d, "Bryst", p, 1)

    add("m5", "Dead Heat A", "AGF", "F", 200, "Fly", 710, 1)
    add("m6", "Dead Heat B", "AGF", "F", 200, "Fly", 710, 1)
    add("h1", "Heat Winner", "VEST", "M", 50, "Ryg", 900, 1, phase="Heats")
    add("p1", "Para Swimmer", "PARAKLUB", "M", 100, "Fly", 999, 1,
        phase="Timed final", klass="para")

    for club, n in [("KLUB A", 3), ("KLUB B", 2), ("KLUB C", 1)]:
        for i in range(n):
            add(f"{club[-1].lower()}{i}", f"{club} Swimmer {i}", club,
                "M", 200, "IM", 400 - i, 4 + i)

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def junior_multi_title_con() -> duckdb.DuckDBPyConnection:
    """A DM-L + DMJ-L meet where a SENIOR sweeps the finals and a JUNIOR sweeps
    the junior field.

    The junior title comes from the qualifying swim, so Senior Sweeper's three
    finals (and his own heats) must be invisible on the junior path: the junior
    digest must report Junior Jens, not him. Three events, so a junior clears
    MIN_TITLES.
    """
    mid, season, mdate = "JM2026", 2026, "2026-04-10"
    mname = "Junior Multi Champs 2026"
    events = [("M", 100, "Fri"), ("M", 200, "Fri"), ("M", 100, "Ryg")]
    meets = [dict(meet_id=mid, meet_name=mname, venue="Aarhus", course="LCM",
                  season=season, meet_date=mdate, category=["DM-L", "DMJ-L"])]
    obt, rid = [], 0

    def add(sid, name, club, by, gender, distance, stroke, points, rank, cs, phase):
        nonlocal rid
        rid += 1
        obt.append(_row(
            result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid, rank=rank,
            name=name, swimmer_id=sid, club=club, birth_year=by,
            completed_time=_time(cs), completed_centiseconds=cs, points=points,
            points_fixed=points, season=season, meet_name=mname, meet_date=mdate,
            distance=distance, stroke=stroke, gender=gender, type=phase))

    for i, (g, d, st) in enumerate(events):
        add("sen1", "Senior Sweeper", "SENIORKLUB", 2000, g, d, st,
            900 - i, 1, 5000 + i, "Final")
        add("sen1", "Senior Sweeper", "SENIORKLUB", 2000, g, d, st,
            880 - i, 1, 5100 + i, "Heats")
        add("jun1", "Junior Jens", "AGF", season - 17, g, d, st,
            700 - i, 2, 5300 + i, "Heats")
        add("jun2", "Junior Jonas", "VEST", season - 17, g, d, st,
            650 - i, 3, 5400 + i, "Heats")

    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 2: Write the failing tests**

Append to `st-scrape/tests/test_digest.py`, and extend its import line to
`from tests.evaluation_fixtures import (digest_con, gapped_digest_con,
junior_digest_con, junior_multi_title_con, multi_title_con, tied_points_con)`.

```python
def test_clubs_is_a_medal_table_ordered_by_titles_then_podiums():
    d = digest.build(multi_title_con(), "DM-L", "M2026")
    assert [(c["club"], c["titles"], c["podiums"], c["swimmers"], c["rank"])
            for c in d["clubs"]] == [
        ("AGF", 8, 8, 4, 1),                    # 3 + 3 titles + a dead-heated 2
        ("Sigma Swim Allerød", 4, 5, 1, 2),     # 4 titles, and a second place
        ("VEST", 2, 2, 2, 3),
        ("KLUB A", 0, 0, 3, 4),                 # no podiums: ordered by swimmers
        ("KLUB B", 0, 0, 2, 5),
    ]
    # CLUB_N truncates: KLUB C (1 swimmer, no podiums) falls off the table.
    assert len(d["clubs"]) == digest.CLUB_N
    assert "KLUB C" not in {c["club"] for c in d["clubs"]}


def test_clubs_ignores_heat_wins_and_para_swims():
    """A heat win is not a title (medal_count's rule), and a para swim is not
    scored at all. Heat Winner has the meet's highest points and swims for
    VEST, so a missing phase filter shows up as VEST holding three titles."""
    d = digest.build(multi_title_con(), "DM-L", "M2026")
    vest = next(c for c in d["clubs"] if c["club"] == "VEST")
    assert vest["titles"] == 2
    assert "PARAKLUB" not in {c["club"] for c in d["clubs"]}


def test_clubs_breaks_a_full_tie_on_club_name():
    """Every club in this fixture has the same swimmer count and podium count,
    so only the name makes the order total -- and a LIMIT over a non-total
    order silently changes the digest, which is part of the cache key."""
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert [(c["club"], c["titles"], c["podiums"], c["swimmers"])
            for c in d["clubs"]] == [
        ("AGF", 4, 4, 8), ("SIGMA", 0, 4, 8), ("VEST", 0, 4, 8)]


def test_clubs_on_the_junior_path_uses_junior_ranks():
    """Seniors fill the senior final; the junior title is decided in the heats.
    SENIORKLUB must be absent entirely, not merely ranked below."""
    d = digest.build(junior_multi_title_con(), "DMJ-L", "JM2026")
    assert [(c["club"], c["titles"], c["podiums"], c["swimmers"])
            for c in d["clubs"]] == [("AGF", 3, 3, 1), ("VEST", 0, 3, 1)]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -k clubs -v`
Expected: 4 failures, all `KeyError: 'clubs'`.

- [ ] **Step 4: Implement the block**

In `st-scrape/webbuild/digest.py`, insert after `_JUNIOR_TOP_SWIMS_SQL` (line 148):

```python
# --- per-entity aggregates within one meet ------------------------------------
# Titles and podiums use medal_count's definition (analytics/views/
# 50_field_evolution.sql): a heat win is not a medal, a timed final counts as a
# final, and dead heats share a rank so one event can yield two titles. Counted
# per result row for exactly that reason.
_FINAL_PHASES = "phase IN ('final', 'timed_final')"

CLUB_N = 5

# The club medal table for this meet. `swimmers` counts everyone the club
# entered (all phases) -- it is context for the club's size, not part of the
# performance measure; titles and podiums are finals-only.
#
# The ORDER BY is a TOTAL order, ending on `club`, which is unique per row. A
# LIMIT over a partial order lets DuckDB return a different top 5 per call, and
# the digest is part of the evaluation cache key (see _TOP_SWIMS_SQL above).
# `swimmers` sits in the chain so a meet whose curated data holds no finals at
# all still ranks by something meaningful instead of alphabetically.
# params: category, meet_id
_CLUBS_SQL = f"""
    WITH agg AS (
        SELECT club,
               count(DISTINCT swimmer_id) AS swimmers,
               count(*) FILTER (WHERE {_FINAL_PHASES} AND rank = 1) AS titles,
               count(*) FILTER (WHERE {_FINAL_PHASES}
                                  AND rank BETWEEN 1 AND 3) AS podiums
        FROM results_by_category
        WHERE category = ? AND meet_id = ? AND class = 'open'
          AND club IS NOT NULL
        GROUP BY club
    )
    SELECT club, swimmers, titles, podiums,
           row_number() OVER (ORDER BY titles DESC, podiums DESC,
                                       swimmers DESC, club) AS rank
    FROM agg
    ORDER BY rank LIMIT {CLUB_N}
"""

# params: meet_id
_JUNIOR_CLUBS_SQL = f"""
    WITH agg AS (
        SELECT club,
               count(DISTINCT swimmer_id) AS swimmers,
               count(*) FILTER (WHERE junior_rank = 1) AS titles,
               count(*) FILTER (WHERE junior_rank BETWEEN 1 AND 3) AS podiums
        FROM junior_championship
        WHERE meet_id = ? AND club IS NOT NULL
        GROUP BY club
    )
    SELECT club, swimmers, titles, podiums,
           row_number() OVER (ORDER BY titles DESC, podiums DESC,
                                       swimmers DESC, club) AS rank
    FROM agg
    ORDER BY rank LIMIT {CLUB_N}
"""
```

In `build()`, extend the existing junior/senior branch (currently lines 268-275)
so it reads:

```python
    swim_cols = ["name", "club", "event", "time", "points", "rank"]
    stroke_cols = ["stroke", "dist_group", "median_points", "prev5_median"]
    club_cols = ["club", "swimmers", "titles", "podiums", "rank"]
    if junior:
        top = con.execute(_JUNIOR_TOP_SWIMS_SQL, [meet_id]).fetchall()
        strokes = con.execute(_JUNIOR_BY_STROKE_SQL,
                              [oldest, season, season, season]).fetchall()
        clubs = con.execute(_JUNIOR_CLUBS_SQL, [meet_id]).fetchall()
    else:
        top = con.execute(_TOP_SWIMS_SQL, [category, meet_id]).fetchall()
        strokes = con.execute(_BY_STROKE_SQL,
                              [category, oldest, season, season, season]).fetchall()
        clubs = con.execute(_CLUBS_SQL, [category, meet_id]).fetchall()
```

and add one key to the returned dict, after `top_swims`:

```python
        "clubs": [dict(zip(club_cols, r)) for r in clubs],
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -v`
Expected: all pass, including the pre-existing digest tests.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/webbuild/digest.py st-scrape/tests/evaluation_fixtures.py \
        st-scrape/tests/test_digest.py
git commit -m "feat(evaluation): add a per-meet club medal table to the digest"
```

---

### Task 2: The `multi_title_swimmers` block

**Files:**
- Modify: `st-scrape/webbuild/digest.py` (after the club SQL from Task 1; `build()`)
- Test: `st-scrape/tests/test_digest.py`

**Interfaces:**
- Consumes: `multi_title_con()` / `junior_multi_title_con()` from Task 1, `_FINAL_PHASES` from Task 1.
- Produces: `digest.build(...)["multi_title_swimmers"]` — a list of dicts with keys `name, club, titles, strokes, wins`, where `wins` is a list of `{"event": str, "points": int}`. Also `digest.MIN_TITLES = 3` and the module-private `_multi_title_swimmers(rows)`.

- [ ] **Step 1: Write the failing tests**

Append to `st-scrape/tests/test_digest.py`:

```python
def test_multi_title_swimmers_surfaces_a_sweep_the_points_cutoff_hides():
    """The DM-L/10334 defect: Mathias Christensen won four finals across three
    strokes at 715-764 while the 10th top_swims slot sat at 779, so the model
    never saw his name and could not have counted his titles anyway."""
    d = digest.build(multi_title_con(), "DM-L", "M2026")
    first = d["multi_title_swimmers"][0]
    assert first == {
        "name": "Mathias Christensen",
        "club": "Sigma Swim Allerød",
        "titles": 4,
        "strokes": ["Bryst", "Fly", "IM"],          # canonical order, not entry order
        "wins": [{"event": "M 200m IM (LCM)", "points": 764},
                 {"event": "M 100m Fly (LCM)", "points": 729},
                 {"event": "M 200m Bryst (LCM)", "points": 725},
                 {"event": "M 400m IM (LCM)", "points": 715}],
    }
    # His 100m Bryst second place is not a title and is not among the wins.
    assert 690 not in [w["points"] for w in first["wins"]]


def test_multi_title_swimmers_applies_the_threshold_and_orders_the_block():
    d = digest.build(multi_title_con(), "DM-L", "M2026")
    assert [(s["name"], s["titles"]) for s in d["multi_title_swimmers"]] == [
        ("Mathias Christensen", 4),
        ("Anders Andersen", 3),      # tie on titles broken by name
        ("Anna Testsen", 3),
    ]
    # Two titles is below MIN_TITLES; a heat win and a para swim are not titles.
    named = {s["name"] for s in d["multi_title_swimmers"]}
    assert not named & {"Dobbelt Vinder", "Heat Winner", "Para Swimmer",
                        "Dead Heat A", "Dead Heat B"}


def test_multi_title_strokes_are_distinct_and_canonically_ordered():
    d = digest.build(multi_title_con(), "DM-L", "M2026")
    anna = next(s for s in d["multi_title_swimmers"] if s["name"] == "Anna Testsen")
    assert anna["strokes"] == ["Fri", "Ryg"]     # entered Ryg, Ryg, Fri
    anders = next(s for s in d["multi_title_swimmers"]
                  if s["name"] == "Anders Andersen")
    assert anders["strokes"] == ["Fri"]          # three Fri titles, one entry


def test_multi_title_swimmers_is_empty_when_nobody_sweeps():
    """Not a failure: every swimmer in this fixture wins at most one event."""
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert d["multi_title_swimmers"] == []


def test_multi_title_swimmers_on_the_junior_path_reports_juniors_only():
    """Senior Sweeper wins all three finals with more points than any junior.
    On the junior path the title is the heats result, so he must be absent."""
    d = digest.build(junior_multi_title_con(), "DMJ-L", "JM2026")
    assert [(s["name"], s["titles"]) for s in d["multi_title_swimmers"]] == [
        ("Junior Jens", 3)]
    assert d["multi_title_swimmers"][0]["strokes"] == ["Fri", "Ryg"]


def test_both_new_blocks_are_deterministic_across_repeated_builds():
    """Both feed the evaluation cache key, so an unstable row set silently
    invalidates cached reports and pays to regenerate them."""
    con = multi_title_con()
    builds = [digest.build(con, "DM-L", "M2026") for _ in range(6)]
    for key in ("clubs", "multi_title_swimmers"):
        assert all(b[key] == builds[0][key] for b in builds), f"{key} is unstable"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -k multi_title -v`
Expected: failures with `KeyError: 'multi_title_swimmers'`.

- [ ] **Step 3: Implement the block**

In `st-scrape/webbuild/digest.py`, after `_JUNIOR_CLUBS_SQL`:

```python
MIN_TITLES = 3

# Canonical stroke order, the same one the SPA's race filter uses. Not
# alphabetical and not order of appearance: both vary, and the digest has to be
# byte-stable.
_STROKE_ORDER = ("Fri", "Ryg", "Bryst", "Fly", "IM", "HM")

# Swimmers with MIN_TITLES or more individual titles at this meet, one row per
# winning swim. NO LIMIT: a cutoff is the defect this block fixes. Ranking by
# points hides exactly the rarest achievement -- points run higher in sprint
# free and fly than in breast and IM, so a single-event specialist takes a
# top_swims slot at 822 while four titles across three strokes at 715-764 takes
# none (DM-L/10334, Mathias Christensen).
#
# The ORDER BY is total (swimmer_id last), and it also groups each swimmer's
# rows together so _multi_title_swimmers can fold them in one pass.
# params: category, meet_id
_MULTI_TITLE_SQL = f"""
    SELECT swimmer_id, name, club, event, stroke, points,
           count(*) OVER (PARTITION BY swimmer_id) AS titles
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
      AND {_FINAL_PHASES} AND rank = 1 AND swimmer_id IS NOT NULL
    QUALIFY titles >= {MIN_TITLES}
    ORDER BY titles DESC, name, swimmer_id, points DESC, event
"""

# params: meet_id
# junior_championship holds at most one row per swimmer per event (it filters
# phase IN ('heats', 'timed_final')), so counting rows counts titles.
_JUNIOR_MULTI_TITLE_SQL = f"""
    SELECT swimmer_id, name, club, event, stroke, points,
           count(*) OVER (PARTITION BY swimmer_id) AS titles
    FROM junior_championship
    WHERE meet_id = ? AND junior_rank = 1
    QUALIFY titles >= {MIN_TITLES}
    ORDER BY titles DESC, name, swimmer_id, points DESC, event
"""
```

Add the folding helper next to `_with_stroke_deltas`:

```python
def _multi_title_swimmers(rows) -> list[dict]:
    """Per-win rows -> one dict per swimmer, order preserved.

    Grouped on swimmer_id, which is NOT emitted (the digest names no ids): two
    swimmers sharing a name must not merge into one four-title swimmer. An
    unknown stroke sorts last rather than raising -- a curate surprise should
    not take down the whole batch.
    """
    out: list[dict] = []
    by_id: dict[str, dict] = {}
    for swimmer_id, name, club, event, stroke, points, titles in rows:
        row = by_id.get(swimmer_id)
        if row is None:
            row = {"name": name, "club": club, "titles": titles,
                   "strokes": [], "wins": []}
            by_id[swimmer_id] = row
            out.append(row)
        if stroke not in row["strokes"]:
            row["strokes"].append(stroke)
        row["wins"].append({"event": event, "points": points})
    for row in out:
        row["strokes"].sort(
            key=lambda s: (_STROKE_ORDER.index(s) if s in _STROKE_ORDER
                           else len(_STROKE_ORDER), s))
    return out
```

In `build()`, add to each branch of the junior/senior `if` from Task 1:

```python
        multi = con.execute(_JUNIOR_MULTI_TITLE_SQL, [meet_id]).fetchall()
```
```python
        multi = con.execute(_MULTI_TITLE_SQL, [category, meet_id]).fetchall()
```

and one more key in the returned dict, directly after `clubs`:

```python
        "multi_title_swimmers": _multi_title_swimmers(multi),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/webbuild/digest.py st-scrape/tests/test_digest.py
git commit -m "feat(evaluation): put multi-title swimmers in the digest"
```

---

### Task 3: Teach `check.py` about the new blocks

Four functions read `top_swims` exclusively. Each is now wrong, and two of the
four fail in the direction that costs a published report.

**Files:**
- Modify: `st-scrape/evaluation/check.py` (`allowed_numbers` ~line 92, `_aggregate_values` ~line 190, `points_owners` ~line 208, `check_attribution` ~line 240, `genders_in_digest` ~line 282)
- Test: `st-scrape/tests/test_evaluation_check.py`

**Interfaces:**
- Consumes: the digest shape from Tasks 1-2.
- Produces: module-private `_club_names(digest) -> set[str]` and `_named_swimmers(digest) -> set[str]`, both used by `allowed_numbers` and `check_attribution`. Public signatures are unchanged: `allowed_numbers(digest)`, `points_owners(digest)`, `genders_in_digest(digest)`, `check_attribution(text, digest)`, `check_numbers(text, digest)`, `check_genders(text, digest)`.

- [ ] **Step 1: Write the failing tests**

Append to `st-scrape/tests/test_evaluation_check.py`:

```python
_ENTITY_DIGEST = {
    "meet": {"name": "DM Langbane 2023", "date": "2023-04-10"},
    "facts": {"entrants": 412, "median_points": 612, "top_points": 764},
    "season_history": [],
    "top_swims": [
        {"name": "Emilie Beckmann", "club": "Swim Team Odense",
         "event": "F 50m Fly (LCM)", "time": "26.10", "points": 822, "rank": 1},
    ],
    "clubs": [
        {"club": "Svømmeklubben MK31", "swimmers": 14, "titles": 5,
         "podiums": 11, "rank": 1},
        {"club": "A6 JGI-Swim", "swimmers": 9, "titles": 2, "podiums": 6,
         "rank": 2},
    ],
    "multi_title_swimmers": [
        {"name": "Mathias Christensen", "club": "Sigma Swim Allerød",
         "titles": 4, "strokes": ["Bryst", "Fly", "IM"],
         "wins": [{"event": "M 200m IM (LCM)", "points": 764},
                  {"event": "M 100m Fly (LCM)", "points": 729}]},
    ],
    "by_stroke": [],
    "derived": {},
}


def test_club_table_names_license_their_own_digits():
    """Club names carry digits ("MK31", "A6"). The prompt licenses naming a
    club, so those digits arrive by design -- flagging them as fabricated
    spends the meet's single rewrite on a false positive, which is what left
    DM-K/7088 unpublished."""
    text = ("Svømmeklubben MK31 vandt 5 titler og 11 podieplaceringer. "
            "A6 JGI-Swim fulgte med 2 titler.")
    assert check.check_numbers(text, _ENTITY_DIGEST) == set()


def test_a_multi_title_swimmers_club_also_licenses_its_digits():
    assert "31" in check.allowed_numbers(_ENTITY_DIGEST)
    d = {**_ENTITY_DIGEST, "clubs": [],
         "multi_title_swimmers": [{"name": "X Y", "club": "MK31", "titles": 3,
                                   "strokes": ["Fri"], "wins": []}]}
    assert "31" in check.allowed_numbers(d)


def test_a_win_is_bound_to_the_swimmer_who_won_it():
    """The block's points are the only figures in the report that nothing else
    protects: they are absent from top_swims by construction."""
    assert check.points_owners(_ENTITY_DIGEST)["764"] == {"mathias christensen"}
    good = "Mathias Christensen vandt 200m IM med 764 point."
    assert check.check_attribution(good, _ENTITY_DIGEST) == set()
    bad = "Emilie Beckmann vandt fire titler med 764 point."
    assert check.check_attribution(bad, _ENTITY_DIGEST) == {"Emilie Beckmann: 764"}


def test_a_gender_flip_on_a_win_is_caught():
    """Same defect class as DM-L/9775's "vandt herrernes 50m Ryg" against an F
    digest row -- every number right, the claim false."""
    assert check.check_genders("Han vandt herrernes 200m IM.", _ENTITY_DIGEST) == set()
    assert check.check_genders("Hun vandt damernes 200m IM.",
                               _ENTITY_DIGEST) == {"damernes 200m IM"}


def test_club_aggregates_are_not_treated_as_a_swimmers_result():
    """A club's title count is nobody's points. If it collides with a real
    points value the provenance is ambiguous, so the attribution check must
    stay quiet rather than credit it to the nearest name."""
    d = {**_ENTITY_DIGEST,
         "clubs": [{"club": "AGF", "swimmers": 3, "titles": 764, "podiums": 1,
                    "rank": 1}]}
    assert "764" not in check.points_owners(d)
```

If the module is imported as `from evaluation import check` in that file, keep
its existing import style — check the top of the file first.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_check.py -v`
Expected: `test_club_table_names_license_their_own_digits` fails (31, 6, 9, 14
unlicensed), the win-attribution and gender tests fail, the aggregate test
fails.

- [ ] **Step 3: Implement**

In `st-scrape/evaluation/check.py`, add two helpers above `allowed_numbers`:

```python
def _club_names(digest: dict) -> set[str]:
    """Every club name the digest carries, from all three blocks that name one.

    Kept in one place because two consumers need the same set: the digit
    licence in allowed_numbers, and the masking in check_attribution.
    """
    out: set[str] = set()
    for key in ("top_swims", "clubs", "multi_title_swimmers"):
        for row in digest.get(key) or []:
            club = row.get("club") if isinstance(row, dict) else None
            if isinstance(club, str):
                out.add(club)
    return out


def _named_swimmers(digest: dict) -> set[str]:
    """Every swimmer the digest names, i.e. every name the prose may use."""
    out: set[str] = set()
    for key in ("top_swims", "multi_title_swimmers"):
        for row in digest.get(key) or []:
            name = row.get("name") if isinstance(row, dict) else None
            if isinstance(name, str):
                out.add(name)
    return out
```

Replace the `for swim in digest.get("top_swims", []):` club loop at the end of
`allowed_numbers` with:

```python
    # Club names carry digits — "Svømmeklubben MK31", "A6 JGI-Swim". The prompt
    # licenses naming a club, so those digits arrive in the prose by design;
    # flagging them as fabricated spends the meet's single rewrite on a false
    # positive (this is what left DM-K/7088 unpublished). Only club names, and
    # only the digit runs as written — the rest of the digest's free text stays
    # unlicensed, which is the leak _walk deliberately avoids.
    for club in _club_names(digest):
        out.update(re.findall(r"\d+", club))
```

In `_aggregate_values`, add the club table — its counts are nobody's result:

```python
    for block in (digest.get("season_history") or [], digest.get("by_stroke") or [],
                  digest.get("clubs") or []):
        _walk(block, out)
```

In `points_owners`, credit the wins too (the `ambiguous` set and the existing
`top_swims` loop stay exactly as they are):

```python
    for row in digest.get("multi_title_swimmers") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if not isinstance(name, str):
            continue
        for win in row.get("wins") or []:
            points = win.get("points") if isinstance(win, dict) else None
            if points is None:
                continue
            key = str(points)
            if key in ambiguous:
                continue
            out.setdefault(key, set()).add(name.lower())
```

In `check_attribution`, swap both `top_swims`-only comprehensions for the
helpers. The `mentions` loop becomes:

```python
    for name in _named_swimmers(digest):
        for m in re.finditer(re.escape(name), text, re.IGNORECASE):
            mentions.append((m.start(), name.lower()))
```

and the masking loop becomes:

```python
    masked = text
    for club in _club_names(digest):
        masked = re.sub(re.escape(club), " " * len(club), masked, flags=re.IGNORECASE)
```

In `genders_in_digest`, read both blocks' events:

```python
def genders_in_digest(digest: dict) -> dict[tuple[str, str], set[str]]:
    """(distance, stroke) -> the genders the digest actually holds.

    Both name-carrying blocks contribute: a swimmer's title is as much a
    gendered claim as a top swim, and an event absent here is simply unjudged.
    """
    events = [swim.get("event") for swim in digest.get("top_swims", [])
              if isinstance(swim, dict)]
    for row in digest.get("multi_title_swimmers") or []:
        if not isinstance(row, dict):
            continue
        events += [win.get("event") for win in row.get("wins") or []
                   if isinstance(win, dict)]
    out: dict[tuple[str, str], set[str]] = {}
    for event in events:
        m = _EVENT.match(str(event or ""))
        if m:
            out.setdefault((m.group(2).lower(), m.group(3).lower()),
                           set()).add(m.group(1).upper())
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_check.py -v`
Expected: all pass, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/evaluation/check.py st-scrape/tests/test_evaluation_check.py
git commit -m "fix(evaluation): check names, clubs and points in every digest block"
```

---

### Task 4: The fifth section, the prompt rules, and both versions

**Files:**
- Modify: `st-scrape/evaluation/agent.py` (lines 29-30, 56-61, 70-131, ~146-158, ~313-322)
- Test: `st-scrape/tests/test_evaluation_agent.py` (lines 77, 227, 251-252)

**Interfaces:**
- Consumes: the digest keys `clubs` and `multi_title_swimmers` from Tasks 1-2.
- Produces: `ag.HEADINGS` as a 5-tuple ending in `"Klubberne"`; `PROMPT_VERSION = "7"`, `SCHEMA_VERSION = "3"`. `MeetEvaluation` now requires five sections in order. No signature changes.

- [ ] **Step 1: Write the failing test**

Append to `st-scrape/tests/test_evaluation_agent.py`:

```python
def test_the_prompt_and_schema_carry_the_club_section():
    """HEADINGS feeds three things at once: the SYSTEM_PROMPT text, the Literal
    in the Section tool schema, and MeetEvaluation's order validator. A heading
    the model cannot see in the schema is the failure that cost 105 tool calls
    on one meet."""
    assert ag.HEADINGS[-1] == "Klubberne"
    assert len(ag.HEADINGS) == 5
    assert "Klubberne" in ag.SYSTEM_PROMPT
    # The two blocks the new rules point at must be named in the prompt, or the
    # model has no way to know they exist.
    assert "digest.clubs" in ag.SYSTEM_PROMPT
    assert "digest.multi_title_swimmers" in ag.SYSTEM_PROMPT
    # Both versions are in the cache key; a section change that does not move
    # them republishes four-section text forever.
    assert (ag.PROMPT_VERSION, ag.SCHEMA_VERSION) == ("7", "3")


def test_the_retry_prompt_points_at_the_precomputed_title_count():
    """The old text told the model to never total up a swimmer's wins. The
    digest now carries the total, so the instruction has to point at it."""
    prompt = ag._prompt("{}", misattributed={"Emilie Beckmann: 764"})
    assert "digest.multi_title_swimmers" in prompt
    assert "never total up a swimmer's wins" not in prompt
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_agent.py -k "club_section or precomputed_title" -v`
Expected: FAIL — `ag.HEADINGS[-1]` is `"Discipliner i bevægelse"`.

- [ ] **Step 3: Implement**

In `st-scrape/evaluation/agent.py`:

```python
PROMPT_VERSION = "7"
SCHEMA_VERSION = "3"
```

```python
HEADINGS = (
    "Samlet niveau",
    "Bredde",
    "Fremhævede svømninger",
    "Discipliner i bevægelse",
    "Klubberne",
)
```

In `SYSTEM_PROMPT`, change the word budget and section count line to:

```
You will be given a <digest> containing every fact you may use. Write about
300 words total, split into exactly these five sections, in this order, with
these headings verbatim:
```

Replace rule 3 with:

```
3. NAMED SWIMMERS. You may name swimmers from digest.top_swims and from
   digest.multi_title_swimmers, and state their time, points, placement and
   event. Nothing else. A swimmer's title count is
   digest.multi_title_swimmers[].titles — quote it, never count the wins
   yourself. Never write about a swimmer's potential or future, their
   technique, body, health, injuries, age, training or schooling, and never
   phrase anything as criticism of a named person. Many of these swimmers are
   minors.
```

Append rule 10 after rule 9:

```
10. CLUBS. digest.clubs is this meet's club table, already ordered: rank 1 is
    the club with the most titles. The section "Klubberne" reports that order
    and the figures in it — titles, podiums and the number of swimmers each
    club entered. Say a club led the meet only if it is rank 1. Never rank a
    club that is not in digest.clubs, never characterise the clubs that are
    absent from it (the meet had more clubs than the table shows), and never
    judge a club or explain its position. Clubs are organisations, so rule 3
    does not apply to them — rule 6 still does: a club name is not a place,
    and a title count is not a statement about a region.
```

Change the closing line from "Output the four sections" to:

```
Output the five sections through the provided structure. Do not add sections,
headings, preambles or closing remarks.
```

Rename the validator and its message (the docstring on `Section` about the
`Literal` stays as it is — it is still true):

```python
class MeetEvaluation(BaseModel):
    sections: list[Section]

    @field_validator("sections")
    @classmethod
    def all_sections_in_order(cls, v: list[Section]) -> list[Section]:
        if tuple(s.heading for s in v) != HEADINGS:
            raise ValueError(f"sections must be exactly {HEADINGS} in order")
        return v
```

In `_prompt`, replace the `misattributed` branch's closing sentence:

```python
    if misattributed:
        # Quote the pairing, not just the number: the figure itself is real and
        # in the digest, so "N is wrong" would read as a contradiction.
        bad = ", ".join(sorted(misattributed))
        return (f"{head}\n"
                f"Your previous answer credited the wrong swimmer with these "
                f"results ({bad}). Each entry in digest.top_swims and in "
                f"digest.multi_title_swimmers[].wins binds one name to one "
                f"event, time and points — never move a figure from one "
                f"swimmer to another. A swimmer's title count is "
                f"digest.multi_title_swimmers[].titles; take it from there "
                f"rather than counting wins yourself. Rewrite the evaluation.")
```

- [ ] **Step 4: Fix the two tests that silently truncate**

Both zip a hardcoded 4-item body list against `HEADINGS`, so with five headings
`zip` drops the fifth section and the tests quietly stop testing what they
claim. In `tests/test_evaluation_agent.py`:

- line ~227: `bodies = [f"{n} point." for n in (612, 612, 612, 612)]` → add a
  fifth `612`.
- line ~252: `zip(ag.HEADINGS, ["a.", "b.", "c i tredje.", "d."])` → append
  `"e."`.
- line 77: rename `test_evaluate_returns_the_four_sections_in_order` to
  `test_evaluate_returns_the_sections_in_order` (it already asserts against
  `ag.HEADINGS`, so the body needs no change).

- [ ] **Step 5: Run the full suite**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: all pass. Any failure mentioning a heading count is a hardcoded
4-section list the grep in Step 4 missed — search for `HEADINGS` and for
four-element body lists in `tests/test_evaluation_main.py` too.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/evaluation/agent.py st-scrape/tests/test_evaluation_agent.py
git commit -m "feat(evaluation): add the Klubberne section and bump both versions"
```

---

### Task 5: Docs, then the PR

**Files:**
- Modify: `docs/analytics.md` (line ~214-215)
- Modify: `CLAUDE.md` (line 78)

- [ ] **Step 1: Update the guardrail note**

`docs/analytics.md` says the report is checked "one section at a time, four
`ApplyGuardrail` calls per generated meet". Change `four` to `five`. Leave the
measurement table and the "Concatenating four sections" sentence at line 224
alone — those are historical measurements of a four-section report and are
still what was measured.

- [ ] **Step 2: Refresh the test count**

Run `cd st-scrape && .venv/bin/python -m pytest -q | tail -1` and put the real
number into `CLAUDE.md` line 78, replacing `(316)`.

- [ ] **Step 3: Commit and open the PR**

```bash
git add docs/analytics.md CLAUDE.md
git commit -m "docs: five guardrail calls per meet, refresh the test count"
git push -u origin digest-entity-aggregates
gh pr create --base master \
  --title "feat(evaluation): per-entity aggregates in the meet digest" \
  --body "$(cat <<'EOF'
Spec: `docs/superpowers/specs/2026-08-03-digest-entity-aggregates-design.md`

Two precomputed per-meet aggregates the model cannot derive for itself:

- **`clubs`** — a club medal table (titles, podiums, swimmers, rank), behind a
  new fifth section `Klubberne`.
- **`multi_title_swimmers`** — every swimmer with 3+ individual titles at the
  meet, with each win. Fixes the DM-L/10334 blind spot: four titles across
  three strokes at 715-764 points fell below the 779-point top-10 cutoff, so
  the model never saw the name and had no title count to quote.

`check.py` now reads names, clubs and points from every block that carries
them, not just `top_swims` — otherwise the club table's digits ("MK31") read as
fabricated numbers and the new swimmers' points are unprotected.

`PROMPT_VERSION` 6→7 and `SCHEMA_VERSION` 2→3, so all 41 meets regenerate on
the next `make web-eval`. No `web/` change: sections render generically.
EOF
)"
gh pr checks --watch
```

---

### Task 6: Regenerate and publish (hand-run, needs AWS + Bedrock)

Not a subagent task — it needs credentials and it spends money.

- [ ] **Step 1: Merge**

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 2: Regenerate every meet**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends && make web-eval
```

Both version bumps invalidate all 41 cache entries, so every meet is
regenerated (~$0.30). Expect a few grounding blocks: the verdict is stochastic,
so **re-run for a re-roll, never tighten the prompt** to chase the threshold.

- [ ] **Step 3: Publish just the reports**

```bash
make web-eval-deploy && make web-eval-verify
```

**No `make web-refresh`.** Only `*/evaluation.json` changed, and a full refresh
is ~50 minutes.

- [ ] **Step 4: Read one report**

Open a meet page and read the `Klubberne` section on `DM-L/10334`, plus whether
Mathias Christensen's four titles are now mentioned. This is the acceptance
check the tests cannot make: the tests prove the digest carries the facts, not
that the Danish prose is worth publishing.
