# AI coach evaluation on meet pages — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a collapsible, ~250-word Danish coach-style evaluation on each meet detail page, generated offline in batch by a Strands agent on Amazon Bedrock and cached content-addressed on S3 so identical data always yields identical published text.

**Architecture:** A pure-SQL `digest` (the only facts the model sees) → a single-call Strands agent with a versioned Bedrock Guardrail → a deterministic number check → an S3 cache keyed by `sha256(digest + prompt/schema version + model id)` → a static `evaluation.json` per meet that the SPA loads. `webbuild` never calls Bedrock; a failed evaluation leaves the page exactly as it is today.

**Tech Stack:** Python 3.12, DuckDB (curated Parquet on S3), Strands Agents SDK, Amazon Bedrock (Converse API + Guardrails), boto3/moto, pytest, Svelte 5 + Vitest, AWS CDK (Python).

**Spec:** `docs/superpowers/specs/2026-07-27-ai-meet-evaluation-design.md`

## Global Constraints

Every task's requirements implicitly include this section.

- **Region is `eu-west-1`, profile is `swimtrends`.** Pass `region_name` explicitly to every boto3 client and to `BedrockModel` — `AWS_REGION` is the lowest-priority fallback in the boto3 resolution chain and must never be relied on.
- **Never use the legacy Bedrock `InvokeModel` API.** All model calls go through the Converse API via Strands' `BedrockModel`.
- **Guardrails are applied at a numbered version, never `DRAFT`.**
- **Contextual grounding thresholds start at `0.7` grounding / `0.5` relevance.** Valid range is `0`–`0.99` (`1.0` throws `ValidationException`).
- **`max_tokens = 1200`** on the agent. At request start `input_tokens + max_tokens` is reserved 1:1 against the TPM quota, so an oversized value blocks concurrency for nothing.
- **Bedrock model IDs and prices are never hardcoded from memory.** Task 9 resolves them from the live Bedrock model catalog / pricing page and records what it found.
- **No AWS account id in any new file** (this is a public repo).
- **No test may call Bedrock or S3 for real.** S3 is exercised with `moto`; Bedrock is stubbed. `make eval-models` (Task 9) is the only thing that reaches Bedrock, and it is run by hand.
- **IAM for the batch operator is `bedrock:InvokeModel*` scoped to the exact chosen model ARN plus `bedrock:ApplyGuardrail` on the guardrail ARN — never a wildcard.**
- **`PROMPT_VERSION` and `SCHEMA_VERSION`** are module constants in `st-scrape/evaluation/agent.py`, bumped by hand. They are part of the cache key.
- **Cache location:** `s3://swimtrends-meet-data/evaluations/<category>/<meet_id>/<key>.json`.
- **The report may contain no number that is not present in the digest.** The prompt forbids computing figures; the digest carries a `derived` block with the precomputed percentage deltas the report is allowed to quote.
- **Danish disclosure copy, verbatim.**
  - Summary suffix: `· AI-genereret, eksperimentelt`
  - Footer: `Denne vurdering er automatisk genereret af en sprogmodel ud fra stævnets tal. Den er eksperimentel og en fortolkning — ikke fakta. Alle tal kan efterprøves i tabellerne ovenfor. Genereret {generated_at} · {model_label}`
- **Section headings, verbatim and in this order:** `Samlet niveau`, `Bredde`, `Fremhævede svømninger`, `Discipliner i bevægelse`.
- **Named swimmers:** results-grounded statements only (time, points, placement, improvement vs their own prior best). Never talent/future projections, never technique/body/health/injury/training speculation, never criticism of a named person, never age/school/personal detail beyond club. Applies to all five categories including the junior championships, where swimmers are 16–18.
- **Run from the directory shown in each command.** `st-scrape` tests: `cd st-scrape && .venv/bin/python -m pytest -q`. CDK tests: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit`. Web tests: `cd web && npm test`.

## File Structure

| Path | Responsibility |
| --- | --- |
| `st-scrape/webbuild/digest.py` | **Create.** Pure SQL → the digest dict for one meet. No model, no S3, no IO. |
| `st-scrape/evaluation/__init__.py` | **Create.** Empty package marker. |
| `st-scrape/evaluation/agent.py` | **Create.** `MeetEvaluation` schema, system prompt, `PROMPT_VERSION`/`SCHEMA_VERSION`, `build_agent()`, `evaluate()`. |
| `st-scrape/evaluation/cache.py` | **Create.** `canonical_json()`, `cache_key()`, `get()`, `put()` against S3. |
| `st-scrape/evaluation/check.py` | **Create.** `numbers_in_text()`, `allowed_numbers()`, `check_numbers()`. Pure. |
| `st-scrape/evaluation/compare.py` | **Create.** Model-comparison harness → HTML + table. Reaches Bedrock; hand-run only. |
| `st-scrape/evaluation/__main__.py` | **Create.** The batch loop and CLI. |
| `st-scrape/tests/evaluation_fixtures.py` | **Create.** A 6-season DM-L fixture with varied points, and a combined junior fixture. |
| `st-scrape/tests/test_digest.py` | **Create.** Digest SQL tests. |
| `st-scrape/tests/test_evaluation_cache.py` | **Create.** Cache key + S3 round-trip (moto). |
| `st-scrape/tests/test_evaluation_check.py` | **Create.** Number-check tests. |
| `st-scrape/tests/test_evaluation_agent.py` | **Create.** Agent wiring tests (Bedrock stubbed). |
| `st-scrape/requirements.txt` | **Modify.** Add `strands-agents`, `pydantic`. |
| `web/src/lib/dataClient.js` | **Modify.** Add `getEvaluation()` that resolves `null` on 404. |
| `web/src/routes/Meet.svelte` | **Modify.** Load and render the collapsible section below the charts. |
| `web/tests/fixtures/evaluation.json` | **Create.** Fixture for the render test. |
| `web/tests/routes.render.test.js` | **Modify.** Add the section's render tests. |
| `web/tests/dataClient.test.js` | **Modify.** Add the 404 → `null` test. |
| `swimtrends-app/swimtrends_app/swimtrends_evaluation_stack.py` | **Create.** The Bedrock Guardrail + a numbered version. |
| `swimtrends-app/swimtrends_app/../app.py` | **Modify.** Wire the new stack in. |
| `swimtrends-app/tests/unit/test_evaluation_stack.py` | **Create.** Assertion tests for the guardrail. |
| `Makefile` | **Modify.** Add `web-eval` and `eval-models`; wire evaluation into `web-refresh`. |
| `docs/analytics.md` | **Modify.** Document the evaluation step and its knobs. |

---

### Task 1: Digest — meet header, facts, season history

Builds the deterministic core of the digest, including the junior-scoped `DMJ-L` path, reusing the SQL shapes already proven in `webbuild/queries.py`.

**Files:**
- Create: `st-scrape/tests/evaluation_fixtures.py`
- Create: `st-scrape/webbuild/digest.py`
- Test: `st-scrape/tests/test_digest.py`

**Interfaces:**
- Consumes: `tests.analytics_fixtures.build_curated(con, obt=, meets=, splits=)`, `analytics.loader.create_views(con)` — both existing.
- Produces:
  - `webbuild.digest.build(con, category: str, meet_id: str) -> dict` — returns keys `meet`, `facts`, `season_history` (this task) and `top_swims`, `by_stroke`, `derived` (Task 2).
  - `tests.evaluation_fixtures.digest_con() -> duckdb.DuckDBPyConnection` — DM-L, seasons 2021–2026, varied points.
  - `tests.evaluation_fixtures.junior_digest_con() -> duckdb.DuckDBPyConnection` — a meet tagged both `DM-L` and `DMJ-L`, seasons 2025–2026.

- [ ] **Step 1: Write the fixture**

The existing `tests/webbuild_fixtures.py` hardcodes `points=500` for every row, so it cannot exercise medians or top-N ordering. This fixture varies points and spans six seasons so the 5-season window has something to truncate.

Create `st-scrape/tests/evaluation_fixtures.py`:

```python
"""Curated fixtures for digest tests: six seasons of DM-L with varied points.

webbuild_fixtures gives every swim points=500, which cannot exercise medians or
top-N ordering. Here points vary per swimmer and per season so the 5-season
window, the medians and the top-swims ranking are all observable.
"""
import duckdb

from analytics.loader import create_views
from tests.analytics_fixtures import build_curated


def _row(**kw):
    base = {
        "result_id": None, "race_id": None, "meet_id": None, "rank": None,
        "name": None, "swimmer_id": None, "nationality": "DEN", "club": None,
        "birth_year": 2000, "completed_time": None, "completed_centiseconds": None,
        "points": None, "points_fixed": None, "season": None, "course": "LCM",
        "meet_name": None, "venue": "Aarhus", "meet_date": None, "number": 1,
        "race_name": None, "distance": None, "stroke": None, "gender": None,
        "relay_count": 1, "type": None, "class": "open",
    }
    base.update(kw)
    return base


def _time(cs):
    return f"{cs // 6000}:{(cs % 6000) // 100:02d}.{cs % 100:02d}"


# (gender, distance, stroke) -> dist_group is sprint/middel/lang in digest.py
_EVENTS = [
    ("M", 100, "Fri"),      # sprint
    ("F", 200, "Ryg"),      # middel
    ("M", 800, "Fri"),      # lang
    ("F", 200, "Bryst"),    # middel
]


def digest_con() -> duckdb.DuckDBPyConnection:
    """DM-L, seasons 2021..2026. Six swimmers per event; points climb with
    season (base 400 + 20 per season past 2021) so medians differ per season,
    and swimmer index shifts points so top_swims has a stable order."""
    obt, meets = [], []
    for season in range(2021, 2027):
        mid = f"D{season}"
        name = f"Danish Champs {season}"
        mdate = f"{season}-04-10"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L"]))
        rid = 0
        for ev_i, (gender, distance, stroke) in enumerate(_EVENTS):
            for i in range(6):
                rid += 1
                pts = 400 + 20 * (season - 2021) + (5 - i) * 30 + ev_i
                cs = 5200 + i * 40 + ev_i * 1000
                obt.append(_row(
                    result_id=f"{mid}-{rid}", race_id=rid, meet_id=mid,
                    rank=i + 1, name=f"Swimmer {ev_i}{i}",
                    swimmer_id=f"s{ev_i}{i}", club=["AGF", "SIGMA", "VEST"][i % 3],
                    completed_time=_time(cs), completed_centiseconds=cs,
                    points=pts, points_fixed=pts, season=season, meet_name=name,
                    meet_date=mdate, distance=distance, stroke=stroke,
                    gender=gender, type="Final"))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con


def junior_digest_con() -> duckdb.DuckDBPyConnection:
    """A meet tagged BOTH DM-L and DMJ-L, 2025 + 2026. Seniors (born 2000) fill
    the final; juniors (age 17) swim heats only, so junior_championship ranks a
    different podium than the senior final — the case digest.build must scope."""
    obt, meets = [], []
    for season in (2025, 2026):
        mid = f"J{season}"
        name = f"Combined Champs {season}"
        mdate = f"{season}-04-10"
        meets.append(dict(meet_id=mid, meet_name=name, venue="Aarhus",
                          course="LCM", season=season, meet_date=mdate,
                          category=["DM-L", "DMJ-L"]))
        rid = 0
        for phase, field in (
            ("Heats", [(f"sen{i}", f"Senior {i}", 2000, 5300 + i * 40, 600 - i * 20)
                       for i in range(3)]
                      + [(f"jun{i}", f"Junior {i}", season - 17, 5600 + i * 40,
                          520 - i * 20) for i in range(4)]),
            ("Final", [(f"sen{i}", f"Senior {i}", 2000, 5250 + i * 40, 620 - i * 20)
                       for i in range(3)]),
        ):
            for i, (sid, sname, by, cs, pts) in enumerate(field, 1):
                rid += 1
                obt.append(_row(
                    result_id=f"{mid}-{phase}-{rid}", race_id=rid, meet_id=mid,
                    rank=i, name=sname, swimmer_id=sid, club="AGF", birth_year=by,
                    completed_time=_time(cs), completed_centiseconds=cs,
                    points=pts, points_fixed=pts, season=season, meet_name=name,
                    meet_date=mdate, distance=100, stroke="Fri", gender="M",
                    type=phase))
    con = duckdb.connect()
    build_curated(con, obt=obt, meets=meets, splits=[])
    create_views(con)
    return con
```

- [ ] **Step 2: Write the failing tests**

Create `st-scrape/tests/test_digest.py`:

```python
from tests.evaluation_fixtures import digest_con, junior_digest_con
from webbuild import digest


def test_meet_header():
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert d["meet"] == {"name": "Danish Champs 2026", "date": "2026-04-10",
                         "season": 2026, "category": "DM-L", "course": "LCM"}


def test_facts_are_present_and_scored():
    d = digest.build(digest_con(), "DM-L", "D2026")
    f = d["facts"]
    assert f["entrants"] == 24            # 4 events x 6 swimmers
    assert f["events"] == 4
    assert f["clubs"] == 3
    assert f["top_points"] == 553         # 400 + 20*5 + 5*30 + 3 (last event)
    assert f["median_points"] is not None
    assert f["elite_median_points"] is not None


def test_season_history_is_newest_first_and_capped_at_six_rows():
    # the meet's own season plus the five prior seasons on record
    d = digest.build(digest_con(), "DM-L", "D2026")
    seasons = [r["season"] for r in d["season_history"]]
    assert seasons == [2026, 2025, 2024, 2023, 2022, 2021]


def test_season_history_truncates_to_the_window_for_an_older_meet():
    d = digest.build(digest_con(), "DM-L", "D2023")
    seasons = [r["season"] for r in d["season_history"]]
    assert seasons == [2023, 2022, 2021]          # nothing before 2021 exists
    assert all(s <= 2023 for s in seasons)        # never looks into the future


def test_junior_scoped_meet_uses_the_junior_championship():
    d = digest.build(junior_digest_con(), "DMJ-L", "J2026")
    assert d["meet"]["category"] == "DMJ-L"
    assert d["facts"]["entrants"] == 4             # the four juniors, not the seniors
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'webbuild.digest'`

- [ ] **Step 4: Write the implementation**

Create `st-scrape/webbuild/digest.py`:

```python
"""The digest: the only facts the evaluation agent is allowed to see.

Pure SQL over the curated views, deterministic for a given (category, meet).
Every number that may appear in a published evaluation comes from here — see
evaluation/check.py, which enforces exactly that.

Window: the meet's own season plus the five prior seasons ON RECORD (not
season-5, since a category may have gaps).
"""

WINDOW = 6          # the meet's season + 5 prior

_HEAD_SQL = """
    SELECT any_value(meet_name), any_value(meet_date), any_value(season),
           any_value(course)
    FROM results_by_category WHERE category = ? AND meet_id = ?
"""

_FACTS_SQL = """
    SELECT count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           count(DISTINCT swimmer_id) FILTER (WHERE is_junior) AS juniors,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
"""

_JUNIOR_FACTS_SQL = """
    SELECT count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           count(DISTINCT swimmer_id) AS juniors,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM junior_championship WHERE meet_id = ?
"""

# params: category, season
_HISTORY_SQL = f"""
    SELECT season,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT club) AS clubs,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points
    FROM results_by_category
    WHERE category = ? AND season <= ? AND class = 'open'
    GROUP BY season ORDER BY season DESC LIMIT {WINDOW}
"""

# params: season
_JUNIOR_HISTORY_SQL = f"""
    SELECT season,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT club) AS clubs,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points
    FROM junior_championship
    WHERE season <= ?
    GROUP BY season ORDER BY season DESC LIMIT {WINDOW}
"""

# Elite depth: median points among the top 10 per event, per season. Heat/final
# deduped to a swimmer's best per event first. params: category, season
_ELITE_SQL = """
    WITH best AS (
        SELECT season, gender, distance, stroke, course, swimmer_id,
               max(points) AS pts
        FROM results_by_category
        WHERE category = ? AND season <= ? AND class = 'open'
          AND points IS NOT NULL AND swimmer_id IS NOT NULL
        GROUP BY season, gender, distance, stroke, course, swimmer_id
    ), ranked AS (
        SELECT season, pts, row_number() OVER (
                   PARTITION BY season, gender, distance, stroke, course
                   ORDER BY pts DESC) AS rk
        FROM best
    )
    SELECT season, CAST(quantile_cont(pts, 0.5) AS BIGINT) AS elite_median_points
    FROM ranked WHERE rk <= 10 GROUP BY season
"""

# params: season
_JUNIOR_ELITE_SQL = """
    WITH best AS (
        SELECT season, gender, distance, stroke, course, swimmer_id,
               max(points) AS pts
        FROM junior_championship
        WHERE season <= ? AND points IS NOT NULL AND swimmer_id IS NOT NULL
        GROUP BY season, gender, distance, stroke, course, swimmer_id
    ), ranked AS (
        SELECT season, pts, row_number() OVER (
                   PARTITION BY season, gender, distance, stroke, course
                   ORDER BY pts DESC) AS rk
        FROM best
    )
    SELECT season, CAST(quantile_cont(pts, 0.5) AS BIGINT) AS elite_median_points
    FROM ranked WHERE rk <= 10 GROUP BY season
"""
```

> **Corrected during execution.** An earlier draft of this plan defined a local
> `_meet_is_combined` here that hardcoded `"DM-L" in cats and "DMJ-L" in cats`.
> That diverges from `webbuild/queries.py`'s predicate ("any non-`DMJ*` tag AND
> any `DMJ*` tag"), so a meet tagged e.g. `["DO", "DMJ-L"]` would be junior-scoped
> on the meet page but senior-scoped in the digest — the evaluation would describe
> a different field than the page shows. Import the existing predicate instead, so
> the two cannot drift:

```python
from webbuild.queries import _meet_is_combined


def build(con, category: str, meet_id: str) -> dict:
    junior = category == "DMJ-L" and _meet_is_combined(con, meet_id)
    head = con.execute(_HEAD_SQL, [category, meet_id]).fetchone()
    season = head[2]

    fact_cols = ["entrants", "events", "clubs", "juniors",
                 "median_points", "top_points"]
    if junior:
        facts = dict(zip(fact_cols, con.execute(
            _JUNIOR_FACTS_SQL, [meet_id]).fetchone()))
        hist_rows = con.execute(_JUNIOR_HISTORY_SQL, [season]).fetchall()
        elite = dict(con.execute(_JUNIOR_ELITE_SQL, [season]).fetchall())
    else:
        facts = dict(zip(fact_cols, con.execute(
            _FACTS_SQL, [category, meet_id]).fetchone()))
        hist_rows = con.execute(_HISTORY_SQL, [category, season]).fetchall()
        elite = dict(con.execute(_ELITE_SQL, [category, season]).fetchall())

    facts["elite_median_points"] = elite.get(season)
    hist_cols = ["season", "entrants", "clubs", "median_points"]
    history = [dict(zip(hist_cols, r)) for r in hist_rows]
    for h in history:
        h["elite_median_points"] = elite.get(h["season"])

    return {
        "meet": {"name": head[0], "date": head[1], "season": season,
                 "category": category, "course": head[3]},
        "facts": facts,
        "season_history": history,
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -q`
Expected: PASS (5 tests)

If `test_facts_are_present_and_scored` fails on `top_points`, print the actual value and fix the *expected* value in the test to match the fixture arithmetic — the fixture is the source of truth for that number, not the assertion.

- [ ] **Step 6: Confirm nothing else broke**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: all existing tests still pass (164 before this task, +5 now).

- [ ] **Step 7: Commit**

```bash
git add st-scrape/webbuild/digest.py st-scrape/tests/test_digest.py st-scrape/tests/evaluation_fixtures.py
git commit -m "feat(eval): digest core — meet header, facts, 6-season history"
```

---

### Task 2: Digest — top swims, per-stroke trend, derived deltas

Adds the two new aggregates the report's "standout swims" and "disciplines in motion" sections need, plus the `derived` block that makes percentage claims checkable.

**Files:**
- Modify: `st-scrape/webbuild/digest.py`
- Modify: `st-scrape/tests/test_digest.py`

**Interfaces:**
- Consumes: `webbuild.digest.build(con, category, meet_id)` from Task 1.
- Produces: three additional keys on the returned dict —
  - `top_swims: list[dict]` with keys `name, club, event, time, points, rank` (≤10, points-descending, one row per swimmer per event).
  - `by_stroke: list[dict]` with keys `stroke, dist_group, median_points, prev5_median` (`dist_group` ∈ `sprint`/`middel`/`lang`).
  - `derived: dict[str, int]` — precomputed rounded percentage deltas the report may quote.

- [ ] **Step 1: Write the failing tests**

Append to `st-scrape/tests/test_digest.py`:

```python
def test_top_swims_are_points_descending_and_capped():
    d = digest.build(digest_con(), "DM-L", "D2026")
    pts = [s["points"] for s in d["top_swims"]]
    assert len(pts) == 10
    assert pts == sorted(pts, reverse=True)
    top = d["top_swims"][0]
    assert set(top) == {"name", "club", "event", "time", "points", "rank"}
    assert top["event"] == "F 200m Bryst (LCM)"   # highest-scoring event in the fixture


def test_top_swims_dedupe_a_swimmer_within_an_event():
    # the junior fixture has the same swimmer in heats AND final of M 100 Fri
    d = digest.build(junior_digest_con(), "DM-L", "J2026")
    names = [s["name"] for s in d["top_swims"]]
    assert len(names) == len(set(names))


def test_by_stroke_has_a_row_per_stroke_and_distance_group():
    d = digest.build(digest_con(), "DM-L", "D2026")
    keys = {(r["stroke"], r["dist_group"]) for r in d["by_stroke"]}
    assert keys == {("Fri", "sprint"), ("Fri", "lang"),
                    ("Ryg", "middel"), ("Bryst", "middel")}
    row = next(r for r in d["by_stroke"] if r["stroke"] == "Ryg")
    assert row["median_points"] > row["prev5_median"]   # points climb with season


def test_by_stroke_prev5_is_null_when_there_is_no_history():
    d = digest.build(digest_con(), "DM-L", "D2021")
    assert all(r["prev5_median"] is None for r in d["by_stroke"])


def test_derived_holds_rounded_percentage_deltas():
    d = digest.build(digest_con(), "DM-L", "D2026")
    assert "median_points_vs_prev5_pct" in d["derived"]
    assert "entrants_vs_prev5_pct" in d["derived"]
    assert all(isinstance(v, int) for v in d["derived"].values())


def test_derived_is_empty_for_a_meet_with_no_prior_seasons():
    d = digest.build(digest_con(), "DM-L", "D2021")
    assert d["derived"] == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -q`
Expected: FAIL with `KeyError: 'top_swims'`

- [ ] **Step 3: Add the SQL and the assembly**

Add to `st-scrape/webbuild/digest.py`, above `build()`:

```python
TOP_N = 10

# Distance buckets coarse enough that each has several swims at 37 meets.
_DIST_GROUP = """
    CASE WHEN distance <= 100 THEN 'sprint'
         WHEN distance <= 400 THEN 'middel'
         ELSE 'lang' END
"""

# One row per swimmer per event (heats/final deduped), best swims first.
# params: category, meet_id
_TOP_SWIMS_SQL = f"""
    SELECT name, club, event, completed_time AS time, points, rank
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
      AND points IS NOT NULL AND swimmer_id IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY swimmer_id, gender, distance, stroke, course
        ORDER BY points DESC) = 1
    ORDER BY points DESC LIMIT {TOP_N}
"""

# params: meet_id
_JUNIOR_TOP_SWIMS_SQL = f"""
    SELECT name, club, event, completed_time AS time, points,
           junior_rank AS rank
    FROM junior_championship
    WHERE meet_id = ? AND points IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY swimmer_id, gender, distance, stroke, course
        ORDER BY points DESC) = 1
    ORDER BY points DESC LIMIT {TOP_N}
"""

# median points this season vs the mean of the prior seasons in the window,
# per stroke x distance group. params: category, season, season, season, season
_BY_STROKE_SQL = f"""
    WITH best AS (
        SELECT season, stroke, {_DIST_GROUP} AS dist_group, swimmer_id,
               gender, distance, course, max(points) AS pts
        FROM results_by_category
        WHERE category = ? AND season BETWEEN ? - 5 AND ? AND class = 'open'
          AND points IS NOT NULL AND swimmer_id IS NOT NULL
        GROUP BY season, stroke, dist_group, swimmer_id, gender, distance, course
    )
    SELECT stroke, dist_group,
           CAST(quantile_cont(pts, 0.5) FILTER (WHERE season = ?) AS BIGINT)
               AS median_points,
           CAST(quantile_cont(pts, 0.5) FILTER (WHERE season < ?) AS BIGINT)
               AS prev5_median
    FROM best
    GROUP BY stroke, dist_group
    HAVING median_points IS NOT NULL
    ORDER BY stroke, dist_group
"""

# params: season, season, season, season
_JUNIOR_BY_STROKE_SQL = f"""
    WITH best AS (
        SELECT season, stroke, {_DIST_GROUP} AS dist_group, swimmer_id,
               gender, distance, course, max(points) AS pts
        FROM junior_championship
        WHERE season BETWEEN ? - 5 AND ? AND points IS NOT NULL
        GROUP BY season, stroke, dist_group, swimmer_id, gender, distance, course
    )
    SELECT stroke, dist_group,
           CAST(quantile_cont(pts, 0.5) FILTER (WHERE season = ?) AS BIGINT)
               AS median_points,
           CAST(quantile_cont(pts, 0.5) FILTER (WHERE season < ?) AS BIGINT)
               AS prev5_median
    FROM best
    GROUP BY stroke, dist_group
    HAVING median_points IS NOT NULL
    ORDER BY stroke, dist_group
"""

_DERIVED_METRICS = ["median_points", "elite_median_points", "entrants", "clubs"]


def _derived(facts: dict, history: list[dict]) -> dict:
    """Rounded percentage deltas of this meet vs the mean of the prior seasons.

    Precomputed here so the report can quote a percentage without the model
    doing arithmetic — check.py then needs no special case for derived numbers.
    Metrics with no history, a null value, or a zero baseline are omitted.
    """
    prior = history[1:]
    out = {}
    for metric in _DERIVED_METRICS:
        vals = [h[metric] for h in prior if h.get(metric) is not None]
        now = facts.get(metric)
        if not vals or now is None:
            continue
        base = sum(vals) / len(vals)
        if base == 0:
            continue
        out[f"{metric}_vs_prev5_pct"] = round(100 * (now / base - 1))
    return out
```

- [ ] **Step 4: Wire them into `build()`**

In `st-scrape/webbuild/digest.py`, replace the `return` statement of `build()` with:

```python
    swim_cols = ["name", "club", "event", "time", "points", "rank"]
    stroke_cols = ["stroke", "dist_group", "median_points", "prev5_median"]
    if junior:
        top = con.execute(_JUNIOR_TOP_SWIMS_SQL, [meet_id]).fetchall()
        strokes = con.execute(_JUNIOR_BY_STROKE_SQL,
                              [season, season, season, season]).fetchall()
    else:
        top = con.execute(_TOP_SWIMS_SQL, [category, meet_id]).fetchall()
        strokes = con.execute(_BY_STROKE_SQL,
                              [category, season, season, season, season]).fetchall()

    return {
        "meet": {"name": head[0], "date": head[1], "season": season,
                 "category": category, "course": head[3]},
        "facts": facts,
        "season_history": history,
        "top_swims": [dict(zip(swim_cols, r)) for r in top],
        "by_stroke": [dict(zip(stroke_cols, r)) for r in strokes],
        "derived": _derived(facts, history),
    }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_digest.py -q`
Expected: PASS (11 tests)

If `test_top_swims_are_points_descending_and_capped` fails on the `event` string, print `d["top_swims"][0]["event"]` and correct the expectation — the format comes from the existing `results` view (`concat_ws(' ', gender, distance || 'm', stroke, '(' || course || ')')`), and the fixture's highest-scoring event is whichever has the largest `ev_i`.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/webbuild/digest.py st-scrape/tests/test_digest.py
git commit -m "feat(eval): digest top swims, per-stroke trend and derived deltas"
```

---

### Task 3: Content-addressed cache

The determinism guarantee. Same digest + same prompt/schema/model → same key → the stored text is reused verbatim, forever, until something in the key changes or the entry is deleted.

**Files:**
- Create: `st-scrape/evaluation/__init__.py`
- Create: `st-scrape/evaluation/cache.py`
- Test: `st-scrape/tests/test_evaluation_cache.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `evaluation.cache.canonical_json(obj) -> str` — `sort_keys=True`, no whitespace padding, `ensure_ascii=False`.
  - `evaluation.cache.cache_key(digest: dict, *, prompt_version: str, schema_version: str, model_id: str) -> str` — 64-char hex.
  - `evaluation.cache.s3_key(category: str, meet_id: str, key: str) -> str`
  - `evaluation.cache.get(client, category, meet_id, key) -> dict | None`
  - `evaluation.cache.put(client, category, meet_id, key, payload: dict) -> None`
  - `evaluation.cache.BUCKET` = `"swimtrends-meet-data"`, `evaluation.cache.PREFIX` = `"evaluations"`.

- [ ] **Step 1: Write the failing tests**

Create `st-scrape/tests/test_evaluation_cache.py`:

```python
import boto3
import pytest
from moto import mock_aws

from evaluation import cache

DIGEST = {"meet": {"name": "Danish Champs 2026", "season": 2026},
          "facts": {"entrants": 24, "median_points": 500}}
VERSIONS = dict(prompt_version="1", schema_version="1", model_id="model-x")


def test_canonical_json_is_order_independent_and_keeps_danish():
    a = cache.canonical_json({"b": 1, "a": "Svømmeklubben Åræø"})
    b = cache.canonical_json({"a": "Svømmeklubben Åræø", "b": 1})
    assert a == b
    assert "Åræø" in a          # not \u-escaped


def test_cache_key_is_stable_across_dict_ordering():
    reordered = {"facts": DIGEST["facts"], "meet": DIGEST["meet"]}
    assert cache.cache_key(DIGEST, **VERSIONS) == cache.cache_key(reordered, **VERSIONS)


def test_cache_key_changes_with_data():
    other = {**DIGEST, "facts": {"entrants": 25, "median_points": 500}}
    assert cache.cache_key(DIGEST, **VERSIONS) != cache.cache_key(other, **VERSIONS)


@pytest.mark.parametrize("field", ["prompt_version", "schema_version", "model_id"])
def test_cache_key_changes_with_prompt_schema_or_model(field):
    bumped = {**VERSIONS, field: "different"}
    assert cache.cache_key(DIGEST, **VERSIONS) != cache.cache_key(DIGEST, **bumped)


def test_s3_key_layout():
    assert cache.s3_key("DM-L", "12486", "abc") == "evaluations/DM-L/12486/abc.json"


@mock_aws
def test_get_returns_none_on_miss_and_the_payload_on_hit():
    client = boto3.client("s3", region_name="eu-west-1")
    client.create_bucket(Bucket=cache.BUCKET,
                         CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    key = cache.cache_key(DIGEST, **VERSIONS)
    assert cache.get(client, "DM-L", "12486", key) is None
    payload = {"sections": [{"heading": "Samlet niveau", "body": "Et stærkt DM."}]}
    cache.put(client, "DM-L", "12486", key, payload)
    assert cache.get(client, "DM-L", "12486", key) == payload
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'evaluation'`

- [ ] **Step 3: Write the implementation**

Create `st-scrape/evaluation/__init__.py` (empty file), then `st-scrape/evaluation/cache.py`:

```python
"""Content-addressed store for generated meet evaluations.

The key is a hash of the digest AND the prompt version, schema version and
model id. So: unchanged inputs reuse the stored text verbatim (no model call,
no cost, no drift between refreshes); a deliberate prompt or model change
regenerates every meet, visibly and on purpose.

Revoke by deleting the object, or via `python -m evaluation --force`. The
bucket is versioned, so a regeneration keeps the prior text.
"""
import hashlib
import json

from botocore.exceptions import ClientError

BUCKET = "swimtrends-meet-data"
PREFIX = "evaluations"


def canonical_json(obj) -> str:
    """Byte-stable JSON: sorted keys, no padding, Danish characters intact."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def cache_key(digest: dict, *, prompt_version: str, schema_version: str,
              model_id: str) -> str:
    material = canonical_json({
        "digest": digest,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "model_id": model_id,
    })
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def s3_key(category: str, meet_id: str, key: str) -> str:
    return f"{PREFIX}/{category}/{meet_id}/{key}.json"


def get(client, category: str, meet_id: str, key: str) -> dict | None:
    try:
        obj = client.get_object(Bucket=BUCKET, Key=s3_key(category, meet_id, key))
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    return json.loads(obj["Body"].read().decode("utf-8"))


def put(client, category: str, meet_id: str, key: str, payload: dict) -> None:
    client.put_object(
        Bucket=BUCKET, Key=s3_key(category, meet_id, key),
        Body=canonical_json(payload).encode("utf-8"),
        ContentType="application/json; charset=utf-8")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_cache.py -q`
Expected: PASS (8 tests — the parametrised one counts three times)

- [ ] **Step 5: Commit**

```bash
git add st-scrape/evaluation/__init__.py st-scrape/evaluation/cache.py st-scrape/tests/test_evaluation_cache.py
git commit -m "feat(eval): content-addressed evaluation cache on S3"
```

---

### Task 4: Number check

The deterministic hallucination guard. Every number in the published text must appear in the digest — no exceptions, no derived arithmetic (the digest's `derived` block supplies the percentages the report is allowed to quote).

**Files:**
- Create: `st-scrape/evaluation/check.py`
- Test: `st-scrape/tests/test_evaluation_check.py`

**Interfaces:**
- Consumes: the digest shape from Tasks 1–2.
- Produces:
  - `evaluation.check.numbers_in_text(text: str) -> set[str]` — normalised numeric tokens found in prose.
  - `evaluation.check.allowed_numbers(digest: dict) -> set[str]` — normalised numeric tokens the digest licenses.
  - `evaluation.check.check_numbers(text: str, digest: dict) -> set[str]` — the offending tokens; empty set means clean.

- [ ] **Step 1: Write the failing tests**

Create `st-scrape/tests/test_evaluation_check.py`:

```python
from evaluation import check

DIGEST = {
    "meet": {"season": 2026, "name": "DM 2026", "date": "2026-04-10",
             "category": "DM-L", "course": "LCM"},
    "facts": {"entrants": 412, "events": 38, "clubs": 58, "juniors": 61,
              "median_points": 612, "elite_median_points": 701, "top_points": 812},
    "season_history": [
        {"season": 2026, "entrants": 412, "clubs": 58, "median_points": 612,
         "elite_median_points": 701},
        {"season": 2025, "entrants": 399, "clubs": 55, "median_points": 599,
         "elite_median_points": 688},
    ],
    "top_swims": [{"name": "Emma Sørensen", "club": "AGF", "event": "F 200m Fly (LCM)",
                   "time": "2:11.40", "points": 812, "rank": 1}],
    "by_stroke": [{"stroke": "Fly", "dist_group": "middel",
                   "median_points": 640, "prev5_median": 610}],
    "derived": {"median_points_vs_prev5_pct": 2},
}


def test_clean_report_passes():
    text = ("DM-L 2026 lå over niveauet: median 612 point mod 599 sidste sæson, "
            "og 412 deltagere fra 58 klubber. Emma Sørensens 2:11.40 (812 point) "
            "var stævnets bedste svømning.")
    assert check.check_numbers(text, DIGEST) == set()


def test_fabricated_number_is_caught():
    text = "Median-niveauet var 777 point."
    assert check.check_numbers(text, DIGEST) == {"777"}


def test_derived_percentage_from_the_digest_is_allowed():
    assert check.check_numbers("Niveauet lå 2% over 5-sæsons-snittet.", DIGEST) == set()


def test_undeclared_percentage_is_caught():
    assert check.check_numbers("Niveauet lå 9% over snittet.", DIGEST) == {"9"}


def test_time_is_matched_with_and_without_the_leading_minute():
    assert check.check_numbers("Hun svømmede 2:11.40.", DIGEST) == set()
    assert check.check_numbers("Hun svømmede 2:11,40.", DIGEST) == set()   # Danish comma
    assert check.check_numbers("Hun svømmede 2:12.40.", DIGEST) == {"2:12.40"}


def test_window_length_and_seasons_are_allowed():
    # "5-sæsons" and a season reference must not trip the check
    assert check.check_numbers("over de sidste 5 sæsoner siden 2025", DIGEST) == set()


def test_ordinal_ranks_from_top_swims_are_allowed():
    assert check.check_numbers("Hun blev nummer 1.", DIGEST) == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'evaluation.check'`

- [ ] **Step 3: Write the implementation**

Create `st-scrape/evaluation/check.py`:

```python
"""Every number in a published evaluation must appear in its digest.

This is the deterministic half of "don't make things up" — cheap, total, and
independent of the model and the guardrail. The prompt forbids the model from
computing figures; percentages it may quote are precomputed in digest["derived"],
so no arithmetic needs licensing here.
"""
import re

# A time (2:11.40), or a plain integer/decimal. Longest alternative first so a
# time is captured whole rather than as its pieces.
_TOKEN = re.compile(r"\d+:\d{1,2}[.,]\d{1,2}|\d+(?:[.,]\d+)?")


def _norm(token: str) -> str:
    """Danish decimal comma -> dot; drop a thousands separator-free integer's
    leading zeros only when it would still be non-empty."""
    return token.replace(",", ".")


def _time_variants(value: str) -> set[str]:
    """A digest time licenses its own form and the way prose usually writes it:
    '0:52.00' also licenses '52.00'."""
    out = {_norm(value)}
    m = re.fullmatch(r"(\d+):(\d{1,2}[.,]\d{1,2})", value or "")
    if m:
        out.add(_norm(m.group(2)))
        if m.group(1) == "0":
            out.add(_norm(m.group(2)))
    return out


def _walk(obj, out: set[str]) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)
    elif isinstance(obj, bool) or obj is None:
        return
    elif isinstance(obj, (int, float)):
        out.add(_norm(str(obj)))
        # An int is also licensed with its sign stripped: derived deltas are
        # negative in the digest but prose says "3% under".
        out.add(_norm(str(abs(obj))))
    elif isinstance(obj, str):
        if re.fullmatch(r"\d+:\d{1,2}[.,]\d{1,2}", obj):
            out |= _time_variants(obj)
        else:
            # Free text (names, event labels, dates) contributes its numbers:
            # an event label like "F 200m Fly (LCM)" licenses 200.
            for tok in _TOKEN.findall(obj):
                out.add(_norm(tok))


def allowed_numbers(digest: dict) -> set[str]:
    out: set[str] = set()
    _walk(digest, out)
    # The size of the comparison window itself ("de sidste 5 sæsoner").
    out.add(str(len(digest.get("season_history", []))))
    out.add(str(max(len(digest.get("season_history", [])) - 1, 0)))
    return out


def numbers_in_text(text: str) -> set[str]:
    return {_norm(t) for t in _TOKEN.findall(text or "")}


def check_numbers(text: str, digest: dict) -> set[str]:
    """The numeric tokens in `text` that the digest does not license."""
    return numbers_in_text(text) - allowed_numbers(digest)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_check.py -q`
Expected: PASS (7 tests)

`test_fabricated_number_is_caught` returning `{"777"}` and not, say, `{"777", "point"}` confirms the tokeniser only yields numbers.

- [ ] **Step 5: Commit**

```bash
git add st-scrape/evaluation/check.py st-scrape/tests/test_evaluation_check.py
git commit -m "feat(eval): deterministic number check against the digest"
```

---

### Task 5: The agent — schema, prompt, Bedrock wiring

**Files:**
- Create: `st-scrape/evaluation/agent.py`
- Modify: `st-scrape/requirements.txt`
- Test: `st-scrape/tests/test_evaluation_agent.py`

**Interfaces:**
- Consumes: `evaluation.check.check_numbers` (Task 4); the digest shape (Tasks 1–2).
- Produces:
  - `evaluation.agent.PROMPT_VERSION: str`, `evaluation.agent.SCHEMA_VERSION: str`
  - `evaluation.agent.HEADINGS: tuple[str, ...]` — the four Danish headings in order.
  - `evaluation.agent.MeetEvaluation` — pydantic model with `sections: list[Section]`.
  - `evaluation.agent.build_agent(*, model_id: str, guardrail_id: str, guardrail_version: str) -> Agent`
  - `evaluation.agent.evaluate(digest: dict, *, agent, retries: int = 1) -> list[dict]` — returns `[{"heading": ..., "body": ...}, ...]`; raises `EvaluationError` when the number check fails after the retry.
  - `evaluation.agent.EvaluationError(Exception)`
  - `evaluation.agent.model_label(model_id: str) -> str`

- [ ] **Step 1: Install the dependency and pin what resolved**

```bash
cd st-scrape && .venv/bin/pip install strands-agents pydantic
.venv/bin/pip show strands-agents pydantic | grep -E '^(Name|Version)'
```

Add the resolved versions to `st-scrape/requirements.txt` (append, keeping the existing lines):

```
strands-agents>=<resolved major.minor>
pydantic>=2
```

Replace `<resolved major.minor>` with what `pip show` printed. Do not invent a version.

- [ ] **Step 2: Write the failing tests**

Create `st-scrape/tests/test_evaluation_agent.py`:

```python
import pytest

from evaluation import agent as ag

DIGEST = {
    "meet": {"season": 2026, "name": "DM 2026", "date": "2026-04-10",
             "category": "DM-L", "course": "LCM"},
    "facts": {"entrants": 412, "events": 38, "clubs": 58, "juniors": 61,
              "median_points": 612, "elite_median_points": 701, "top_points": 812},
    "season_history": [
        {"season": 2026, "entrants": 412, "clubs": 58, "median_points": 612,
         "elite_median_points": 701}],
    "top_swims": [], "by_stroke": [], "derived": {},
}


class FakeResult:
    def __init__(self, sections):
        self.structured_output = ag.MeetEvaluation(sections=sections)


class FakeAgent:
    """Stands in for a Strands Agent: records prompts, returns canned reports."""
    def __init__(self, *reports):
        self.reports = list(reports)
        self.prompts = []

    def __call__(self, prompt, **kwargs):
        self.prompts.append(prompt)
        return FakeResult(self.reports.pop(0))


def _sections(body):
    return [{"heading": h, "body": body} for h in ag.HEADINGS]


def test_evaluate_returns_the_four_sections_in_order():
    fake = FakeAgent(_sections("612 point og 412 deltagere."))
    out = ag.evaluate(DIGEST, agent=fake)
    assert [s["heading"] for s in out] == list(ag.HEADINGS)


def test_evaluate_passes_the_digest_in_the_prompt():
    fake = FakeAgent(_sections("612 point."))
    ag.evaluate(DIGEST, agent=fake)
    assert "<digest>" in fake.prompts[0]
    assert "412" in fake.prompts[0]


def test_evaluate_retries_once_when_a_number_is_fabricated():
    fake = FakeAgent(_sections("Median var 777 point."),      # bad
                     _sections("Median var 612 point."))      # good on retry
    out = ag.evaluate(DIGEST, agent=fake)
    assert len(fake.prompts) == 2
    assert "777" in fake.prompts[1]           # the offending token is quoted back
    assert "612" in out[0]["body"]


def test_evaluate_raises_when_the_retry_also_fabricates():
    fake = FakeAgent(_sections("777 point."), _sections("888 point."))
    with pytest.raises(ag.EvaluationError) as e:
        ag.evaluate(DIGEST, agent=fake)
    assert "888" in str(e.value)


def test_schema_rejects_a_wrong_heading_set():
    with pytest.raises(Exception):
        ag.MeetEvaluation(sections=[{"heading": "Noget andet", "body": "x"}])


def test_build_agent_wires_region_model_and_a_numbered_guardrail(monkeypatch):
    seen = {}

    class RecordingModel:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(ag, "BedrockModel", RecordingModel)
    ag.build_agent(model_id="model-x", guardrail_id="gr-1", guardrail_version="3")
    assert seen["region_name"] == "eu-west-1"
    assert seen["model_id"] == "model-x"
    assert seen["guardrail_id"] == "gr-1"
    assert seen["guardrail_version"] == "3"
    assert seen["max_tokens"] == 1200


def test_build_agent_refuses_a_draft_guardrail():
    with pytest.raises(ValueError):
        ag.build_agent(model_id="model-x", guardrail_id="gr-1",
                       guardrail_version="DRAFT")


def test_model_label_falls_back_to_the_id():
    assert ag.model_label("something-unmapped") == "something-unmapped"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_agent.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'evaluation.agent'`

- [ ] **Step 4: Write the implementation**

Create `st-scrape/evaluation/agent.py`:

```python
"""The evaluation agent: one digest in, one Danish coach report out.

A single Strands agent, a single Converse call per meet, no tools and no
memory — the digest is the agent's entire world, which is what makes both the
guardrail's grounding check and the deterministic number check meaningful.

PROMPT_VERSION / SCHEMA_VERSION are part of the cache key: bump either and
every meet regenerates on the next run. Do that deliberately.
"""
from pydantic import BaseModel, field_validator
from strands import Agent
from strands.models import BedrockModel

from evaluation.check import check_numbers

PROMPT_VERSION = "1"
SCHEMA_VERSION = "1"

REGION = "eu-west-1"
MAX_TOKENS = 1200

HEADINGS = (
    "Samlet niveau",
    "Bredde",
    "Fremhævede svømninger",
    "Discipliner i bevægelse",
)

# Human-readable label shown in the page footer next to the generation date.
# Extend as models are added; unmapped ids fall back to the raw id.
MODEL_LABELS: dict[str, str] = {}

SYSTEM_PROMPT = f"""\
You are an experienced Danish swimming coach writing a short evaluation of a
national championship meet for a public analytics site. You write in DANISH.

You will be given a <digest> containing every fact you may use. Write about
250 words total, split into exactly these four sections, in this order, with
these headings verbatim:

{chr(10).join('  - ' + h for h in HEADINGS)}

Rules — these are absolute:

1. NUMBERS. Use only numbers that appear literally in the digest. Never
   calculate, estimate, round or infer a number. If you want to express a
   percentage change, use only the precomputed values in digest.derived. If a
   number you want does not exist in the digest, describe the direction in
   words instead ("højere end", "under de seneste sæsoners niveau").
2. COMPARISONS. Compare against the seasons in digest.season_history only.
   If there is little or no history, say so plainly rather than implying a
   trend.
3. NAMED SWIMMERS. You may name swimmers from digest.top_swims and state their
   time, points, placement and event. Nothing else. Never write about a
   swimmer's potential or future, their technique, body, health, injuries, age,
   training or schooling, and never phrase anything as criticism of a named
   person. Many of these swimmers are minors.
4. TONE. Informed, sober, specific. No hype, no exclamation marks, no emoji.
   Write as an analyst who respects the reader's knowledge of the sport.
5. Danish stroke names are used in the data and in your text: Fri, Ryg, Bryst,
   Fly, IM, HM.

Output the four sections through the provided structure. Do not add sections,
headings, preambles or closing remarks.
"""


class EvaluationError(Exception):
    """The model produced a report we refuse to publish."""


class Section(BaseModel):
    heading: str
    body: str

    @field_validator("heading")
    @classmethod
    def known_heading(cls, v: str) -> str:
        if v not in HEADINGS:
            raise ValueError(f"unknown heading: {v!r}")
        return v


class MeetEvaluation(BaseModel):
    sections: list[Section]

    @field_validator("sections")
    @classmethod
    def all_four_in_order(cls, v: list[Section]) -> list[Section]:
        if tuple(s.heading for s in v) != HEADINGS:
            raise ValueError(f"sections must be exactly {HEADINGS} in order")
        return v


def model_label(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)


def build_agent(*, model_id: str, guardrail_id: str, guardrail_version: str) -> Agent:
    """A Converse-API agent with the guardrail applied inline at a numbered
    version. DRAFT is refused: a draft guardrail can change under us between
    two meets in the same batch."""
    if not guardrail_version or guardrail_version.upper() == "DRAFT":
        raise ValueError("guardrail_version must be a numbered version, not DRAFT")
    model = BedrockModel(
        model_id=model_id,
        region_name=REGION,
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        max_tokens=MAX_TOKENS,
        cache_prompt="default",
    )
    return Agent(model=model, system_prompt=SYSTEM_PROMPT)


def _prompt(digest_json: str, offenders: set[str] | None = None) -> str:
    if not offenders:
        return f"<digest>{digest_json}</digest>"
    bad = ", ".join(sorted(offenders))
    return (f"<digest>{digest_json}</digest>\n"
            f"Your previous answer contained numbers that are not in the digest: "
            f"{bad}. Rewrite the evaluation using only numbers from the digest.")


def evaluate(digest: dict, *, agent, retries: int = 1) -> list[dict]:
    """digest -> [{heading, body}, ...]. Raises EvaluationError if the number
    check still fails after `retries` rewrites."""
    from evaluation.cache import canonical_json      # local: avoids a cycle

    digest_json = canonical_json(digest)
    offenders: set[str] = set()
    for attempt in range(retries + 1):
        result = agent(_prompt(digest_json, offenders if attempt else None),
                       structured_output_model=MeetEvaluation)
        report = result.structured_output
        text = "\n".join(s.body for s in report.sections)
        offenders = check_numbers(text, digest)
        if not offenders:
            return [{"heading": s.heading, "body": s.body} for s in report.sections]
    raise EvaluationError(
        f"numbers not in digest after {retries} retry: {sorted(offenders)}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd st-scrape && .venv/bin/python -m pytest tests/test_evaluation_agent.py -q`
Expected: PASS (8 tests)

If `from strands.models import BedrockModel` raises `ImportError`, find the correct import path with `cd st-scrape && .venv/bin/python -c "import strands, pkgutil; print([m.name for m in pkgutil.iter_modules(strands.__path__)])"` and fix the import — do not guess a second time. If `Agent.__call__` does not accept `structured_output_model`, check the installed version's signature with `.venv/bin/python -c "import inspect, strands; print(inspect.signature(strands.Agent.__call__))"` and adapt; `agent.structured_output()` is deprecated and must not be used.

- [ ] **Step 6: Run the whole suite**

Run: `cd st-scrape && .venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add st-scrape/evaluation/agent.py st-scrape/tests/test_evaluation_agent.py st-scrape/requirements.txt
git commit -m "feat(eval): coach agent — schema, Danish prompt, Bedrock wiring"
```

---

### Task 6: The batch CLI and Makefile wiring

**Files:**
- Create: `st-scrape/evaluation/__main__.py`
- Modify: `Makefile`
- Modify: `docs/analytics.md`

**Interfaces:**
- Consumes: `webbuild.digest.build`, `evaluation.cache.{cache_key,get,put}`, `evaluation.agent.{build_agent,evaluate,model_label,PROMPT_VERSION,SCHEMA_VERSION,EvaluationError}`, `webbuild.shape.write_json`, `analytics.loader.connect`.
- Produces: `python -m evaluation --out <dir> [--meets CAT/ID,…] [--model ID] [--force] [--dry-run]`, and the file `<out>/<category>/<meet_id>/evaluation.json` with keys `category, meet_id, prompt_version, schema_version, model_id, model_label, generated_at, sections`.

- [ ] **Step 1: Write the CLI**

Create `st-scrape/evaluation/__main__.py`:

```python
"""Fill the evaluation cache and emit evaluation.json per meet.

Run after webbuild and before the S3 sync (see the Makefile). Cheap on a cache
hit: the digest queries are aggregates, and no model is called unless the key
is missing. Any failure skips that meet — the page then renders exactly as it
does today.

Config comes from the environment:
  EVAL_MODEL_ID           Bedrock model id (or --model)
  EVAL_GUARDRAIL_ID       Bedrock guardrail id
  EVAL_GUARDRAIL_VERSION  numbered guardrail version (never DRAFT)
"""
import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

import boto3

from analytics.loader import connect
from evaluation import agent as ag
from evaluation import cache
from webbuild import digest as dg
from webbuild.shape import write_json

log = logging.getLogger("evaluation")


def _all_meets(con) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT DISTINCT category, meet_id FROM results_by_category "
        "WHERE class = 'open' ORDER BY category, meet_id").fetchall()
    return [(c, m) for c, m in rows]


def _parse_meets(spec: str) -> list[tuple[str, str]]:
    out = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        if "/" not in item:
            raise SystemExit(f"--meets entries must be CATEGORY/MEET_ID, got {item!r}")
        cat, mid = item.split("/", 1)
        out.append((cat, mid))
    return out


def run(con, out: Path, *, model_id: str, guardrail_id: str, guardrail_version: str,
        meets=None, force: bool = False, dry_run: bool = False) -> dict:
    s3 = boto3.client("s3", region_name=ag.REGION)
    agent = None if dry_run else ag.build_agent(
        model_id=model_id, guardrail_id=guardrail_id,
        guardrail_version=guardrail_version)
    stats = {"hit": 0, "generated": 0, "skipped": 0, "written": 0}

    for category, meet_id in (meets or _all_meets(con)):
        try:
            digest = dg.build(con, category, meet_id)
        except Exception:
            log.exception("digest failed for %s/%s", category, meet_id)
            stats["skipped"] += 1
            continue

        key = cache.cache_key(digest, prompt_version=ag.PROMPT_VERSION,
                              schema_version=ag.SCHEMA_VERSION, model_id=model_id)
        payload = None if force else cache.get(s3, category, meet_id, key)
        if payload is not None:
            stats["hit"] += 1
        elif dry_run:
            log.info("would generate %s/%s", category, meet_id)
            stats["skipped"] += 1
            continue
        else:
            try:
                sections = ag.evaluate(digest, agent=agent)
            except Exception:
                log.exception("evaluation failed for %s/%s", category, meet_id)
                stats["skipped"] += 1
                continue
            payload = {
                "category": category, "meet_id": meet_id,
                "prompt_version": ag.PROMPT_VERSION,
                "schema_version": ag.SCHEMA_VERSION,
                "model_id": model_id, "model_label": ag.model_label(model_id),
                "generated_at": dt.date.today().isoformat(),
                "sections": sections,
            }
            cache.put(s3, category, meet_id, key, payload)
            stats["generated"] += 1

        write_json(out / category / meet_id / "evaluation.json", payload)
        stats["written"] += 1

    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Generate cached AI meet evaluations and emit evaluation.json.")
    ap.add_argument("--out", required=True, type=Path, help="web data output directory")
    ap.add_argument("--meets", help="comma-separated CATEGORY/MEET_ID (default: all)")
    ap.add_argument("--model", default=os.environ.get("EVAL_MODEL_ID"),
                    help="Bedrock model id (default: $EVAL_MODEL_ID)")
    ap.add_argument("--force", action="store_true",
                    help="regenerate even on a cache hit (revokes the cached text)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report hits/misses, never call the model")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.model:
        raise SystemExit("no model: pass --model or set EVAL_MODEL_ID")
    guardrail_id = os.environ.get("EVAL_GUARDRAIL_ID")
    guardrail_version = os.environ.get("EVAL_GUARDRAIL_VERSION")
    if not args.dry_run and not (guardrail_id and guardrail_version):
        raise SystemExit(
            "set EVAL_GUARDRAIL_ID and EVAL_GUARDRAIL_VERSION "
            "(from the SwimtrendsEvaluationStack outputs)")

    stats = run(connect(), args.out, model_id=args.model,
                guardrail_id=guardrail_id, guardrail_version=guardrail_version,
                meets=_parse_meets(args.meets) if args.meets else None,
                force=args.force, dry_run=args.dry_run)
    print("evaluations: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify the CLI's argument handling without touching AWS**

```bash
cd st-scrape && .venv/bin/python -m evaluation --out /tmp/eval-out 2>&1 | tail -2
```
Expected: `no model: pass --model or set EVAL_MODEL_ID`

```bash
cd st-scrape && .venv/bin/python -m evaluation --out /tmp/eval-out --model m 2>&1 | tail -2
```
Expected: the `EVAL_GUARDRAIL_ID`/`EVAL_GUARDRAIL_VERSION` message.

Both must fail *before* any AWS call. If either hangs or raises a botocore error instead, the guard ordering in `main()` is wrong — fix it.

- [ ] **Step 3: Add the Makefile targets**

In `Makefile`, replace the `web-refresh` target (keep its existing body verbatim; only the comment and the new `$(MAKE) web-eval` line are added) with:

```make
# Regenerate the data JSON from the curated zone, add AI evaluations, and push
web-refresh:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	$(MAKE) web-eval
	aws s3 sync web/public/data s3://$(WEB_BUCKET)/data/ --delete --profile swimtrends
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/data/*" --profile swimtrends

# Fill the evaluation cache and emit evaluation.json (seconds on a cache hit).
# Needs EVAL_MODEL_ID, EVAL_GUARDRAIL_ID, EVAL_GUARDRAIL_VERSION in the
# environment — see docs/analytics.md. Does NOT sync; web-refresh does that.
web-eval:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation --out ../web/public/data
```

Add `web-eval` to the `.PHONY` line at the bottom of the file.

The evaluation step must run **before** the sync: `web-refresh` syncs with `--delete`, so an `evaluation.json` produced after the sync would be deleted on the next one.

- [ ] **Step 4: Document it**

Append a section to `docs/analytics.md`:

```markdown
## AI meet evaluations

Each meet page can carry a short Danish coach-style evaluation, generated
offline and cached. `make web-eval` fills the cache and writes
`web/public/data/<cat>/<meet>/evaluation.json`; `make web-refresh` runs it
between `webbuild` and the S3 sync.

Config (all three required; the guardrail values come from the
`SwimtrendsEvaluationStack` outputs):

```bash
export EVAL_MODEL_ID=<bedrock model id>
export EVAL_GUARDRAIL_ID=<guardrail id>
export EVAL_GUARDRAIL_VERSION=<numbered version, never DRAFT>
```

Useful flags:

- `--dry-run` — report cache hits and misses without calling the model.
- `--meets DM-L/12486` — one meet (or a comma-separated list).
- `--force` — regenerate and overwrite the cached text. This is the revoke
  switch; the bucket is versioned, so the prior text is retained.

The cache key is `sha256(digest + prompt_version + schema_version + model_id)`.
Unchanged inputs reuse the stored text verbatim — bumping `PROMPT_VERSION` or
`SCHEMA_VERSION` in `evaluation/agent.py`, or switching models, regenerates
every meet on the next run.

Every number in a published evaluation is checked against the digest
(`evaluation/check.py`); a report that fails twice is dropped and the page
renders without the section.
```

- [ ] **Step 5: Commit**

```bash
git add st-scrape/evaluation/__main__.py Makefile docs/analytics.md
git commit -m "feat(eval): batch CLI, make web-eval, wire into web-refresh"
```

---

### Task 7: Bedrock Guardrail (CDK)

**Files:**
- Create: `swimtrends-app/swimtrends_app/swimtrends_evaluation_stack.py`
- Modify: `swimtrends-app/app.py`
- Test: `swimtrends-app/tests/unit/test_evaluation_stack.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: a deployed guardrail whose id and numbered version are stack outputs `GuardrailId` and `GuardrailVersion`, consumed by `EVAL_GUARDRAIL_ID` / `EVAL_GUARDRAIL_VERSION` in Task 6.

A separate stack rather than an addition to `SwimtrendsCuratedStack`: it deploys independently, needs no `alert_email`, and keeps a guardrail change from touching the curate Lambda or Fargate task.

- [ ] **Step 1: Write the failing tests**

Create `swimtrends-app/tests/unit/test_evaluation_stack.py`:

```python
import aws_cdk as cdk
from aws_cdk import assertions

from swimtrends_app.swimtrends_evaluation_stack import SwimtrendsEvaluationStack


def _template():
    app = cdk.App()
    stack = SwimtrendsEvaluationStack(app, "TestEval")
    return assertions.Template.from_stack(stack)


def test_guardrail_blocks_the_three_denied_topics():
    t = _template()
    t.has_resource_properties("AWS::Bedrock::Guardrail", {
        "TopicPolicyConfig": {
            "TopicsConfig": assertions.Match.array_with([
                assertions.Match.object_like({"Name": "TalentProjection",
                                              "Type": "DENY"}),
                assertions.Match.object_like({"Name": "PhysiqueAndHealth",
                                              "Type": "DENY"}),
                assertions.Match.object_like({"Name": "PersonalCriticism",
                                              "Type": "DENY"}),
            ])
        }
    })


def test_guardrail_has_grounding_and_relevance_thresholds():
    _template().has_resource_properties("AWS::Bedrock::Guardrail", {
        "ContextualGroundingPolicyConfig": {
            "FiltersConfig": assertions.Match.array_with([
                {"Type": "GROUNDING", "Threshold": 0.7},
                {"Type": "RELEVANCE", "Threshold": 0.5},
            ])
        }
    })


def test_a_numbered_version_is_published():
    t = _template()
    t.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)


def test_outputs_expose_the_id_and_version():
    t = _template()
    outputs = t.find_outputs("*")
    assert "GuardrailId" in outputs
    assert "GuardrailVersion" in outputs
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit/test_evaluation_stack.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'swimtrends_app.swimtrends_evaluation_stack'`

- [ ] **Step 3: Write the stack**

Create `swimtrends-app/swimtrends_app/swimtrends_evaluation_stack.py`:

```python
"""Guardrail for the AI meet evaluations.

The evaluations are batch-generated prose about named swimmers — many of them
16-18 year olds at the junior championships. The guardrail is the enforcement
half of that policy (the system prompt is the cooperative half): it denies
talent projection, physique/health speculation and personal criticism, and runs
a contextual grounding check with the meet digest as the grounding source.

Applied inline on the Converse call at the NUMBERED version below — never
DRAFT, which could change between two meets of the same batch.
"""
from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

GROUNDING_THRESHOLD = 0.7
RELEVANCE_THRESHOLD = 0.5


class SwimtrendsEvaluationStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        guardrail = bedrock.CfnGuardrail(
            self, "EvaluationGuardrail",
            name="swimtrends-meet-evaluation",
            description=("Guardrail for batch-generated Danish coach evaluations "
                         "of swim meets. Denies projection, physique/health and "
                         "personal criticism about named swimmers; grounds every "
                         "claim in the meet digest."),
            blocked_input_messaging="Input blocked by guardrail.",
            blocked_outputs_messaging="Output blocked by guardrail.",
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="TalentProjection", type="DENY",
                        definition=("Predictions, projections or speculation about a "
                                    "named athlete's future performance, potential, "
                                    "career prospects or selection for teams or "
                                    "championships."),
                        examples=[
                            "Hun er et kommende OL-emne.",
                            "Han bliver landsholdssvømmer inden for to år.",
                        ]),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="PhysiqueAndHealth", type="DENY",
                        definition=("Statements or speculation about a named athlete's "
                                    "body, physique, weight, health, injuries, illness, "
                                    "fitness, training load or technique."),
                        examples=[
                            "Han virker utrænet på de sidste 50 meter.",
                            "Hendes skulderskade præger svømningen.",
                        ]),
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name="PersonalCriticism", type="DENY",
                        definition=("Criticism, blame, mockery or disparagement "
                                    "directed at a named person, including their "
                                    "execution, effort, attitude or choices."),
                        examples=[
                            "En skødesløs vending kostede hende sejren.",
                            "Han gav tydeligvis op på sidste længde.",
                        ]),
                ]),
            contextual_grounding_policy_config=(
                bedrock.CfnGuardrail.ContextualGroundingPolicyConfigProperty(
                    filters_config=[
                        bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                            type="GROUNDING", threshold=GROUNDING_THRESHOLD),
                        bedrock.CfnGuardrail.ContextualGroundingFilterConfigProperty(
                            type="RELEVANCE", threshold=RELEVANCE_THRESHOLD),
                    ])),
        )

        version = bedrock.CfnGuardrailVersion(
            self, "EvaluationGuardrailVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description="Published version consumed by the evaluation batch job.")

        CfnOutput(self, "GuardrailId", value=guardrail.attr_guardrail_id)
        CfnOutput(self, "GuardrailVersion", value=version.attr_version)
```

- [ ] **Step 4: Wire it into the app**

In `swimtrends-app/app.py`, add the import next to the others:

```python
from swimtrends_app.swimtrends_evaluation_stack import SwimtrendsEvaluationStack
```

and the instantiation after `SwimtrendsCuratedStack(...)`:

```python
SwimtrendsEvaluationStack(app, "SwimtrendsEvaluationStack", env=ENV)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit -q`
Expected: PASS — the four new tests plus every existing CDK test.

If a `CfnGuardrail` property name is rejected, check the installed aws-cdk-lib's signature with `cd swimtrends-app && .venv/bin/python -c "from aws_cdk import aws_bedrock; help(aws_bedrock.CfnGuardrail)" | head -60` and correct it. Do not switch to the alpha L2 construct — L1 is deliberate here.

- [ ] **Step 6: Synthesize to catch template-level errors**

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app && export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
npx aws-cdk@2.1133.0 synth SwimtrendsEvaluationStack --app ".venv/bin/python3 app.py" -c alert_email=mortench.privat@gmail.com > /dev/null && echo SYNTH_OK
```
Expected: `SYNTH_OK`

`-c alert_email` is passed even though this stack does not use it: omitting it while synthesizing the whole app would drop the SNS email subscription from the other stacks' templates.

**Do not deploy.** CDK stack deploys are an infra change requiring explicit confirmation — Task 10 asks for it.

- [ ] **Step 7: Commit**

```bash
git add swimtrends-app/swimtrends_app/swimtrends_evaluation_stack.py swimtrends-app/app.py swimtrends-app/tests/unit/test_evaluation_stack.py
git commit -m "feat(eval): CDK Bedrock guardrail with denied topics and grounding"
```

---

### Task 8: The meet-page section

**Files:**
- Modify: `web/src/lib/dataClient.js`
- Modify: `web/src/routes/Meet.svelte`
- Create: `web/tests/fixtures/evaluation.json`
- Modify: `web/tests/dataClient.test.js`
- Modify: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: the `evaluation.json` shape from Task 6 (`sections`, `generated_at`, `model_label`).
- Produces: `dataClient.getEvaluation(cat, meetId) -> Promise<object|null>` — resolves `null` on any fetch failure.

- [ ] **Step 1: Write the fixture**

Create `web/tests/fixtures/evaluation.json`:

```json
{
  "category": "DM-L",
  "meet_id": "M2026",
  "prompt_version": "1",
  "schema_version": "1",
  "model_id": "test-model",
  "model_label": "Testmodel",
  "generated_at": "2026-07-27",
  "sections": [
    {"heading": "Samlet niveau", "body": "Median-pointniveauet lå over de fem foregående sæsoner."},
    {"heading": "Bredde", "body": "412 deltagere fra 58 klubber."},
    {"heading": "Fremhævede svømninger", "body": "Emma Sørensen svømmede 200 Fly i 2:11.40 (812 point)."},
    {"heading": "Discipliner i bevægelse", "body": "Bryst-distancerne løftede niveauet."}
  ]
}
```

- [ ] **Step 2: Write the failing tests**

Append to `web/tests/dataClient.test.js`:

```javascript
test('getEvaluation resolves null when the file is absent', async () => {
  mockFetch({})
  await expect(dc.getEvaluation('DM-L', 'M2026')).resolves.toBeNull()
})

test('getEvaluation returns the payload when present', async () => {
  mockFetch({ 'data/DM-L/M2026/evaluation.json': { sections: [] } })
  const e = await dc.getEvaluation('DM-L', 'M2026')
  expect(e.sections).toEqual([])
})
```

Append to `web/tests/routes.render.test.js` (the file already imports `render`, `screen`, `waitFor`, `dc`, `Meet`, `meetJson`, `racesJson`):

```javascript
import evaluationJson from './fixtures/evaluation.json'

test('Meet renders the coach evaluation with its disclaimers', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(evaluationJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByText(/Trænerens vurdering/)
  expect(screen.getByText(/AI-genereret, eksperimentelt/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 4, name: 'Samlet niveau' })).toBeInTheDocument()
  expect(screen.getByText(/ikke fakta/)).toBeInTheDocument()
  expect(screen.getByText(/Testmodel/)).toBeInTheDocument()
})

test('Meet renders nothing when there is no evaluation', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.queryByText(/Trænerens vurdering/)).toBeNull()
})

test('the evaluation section starts collapsed', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(evaluationJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  const summary = await screen.findByText(/Trænerens vurdering/)
  expect(summary.closest('details').open).toBe(false)
})
```

The existing render tests in this file do not stub `getEvaluation`, so they will start hitting the real one. Step 4 handles that.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd web && npm test`
Expected: FAIL — `dc.getEvaluation is not a function`

- [ ] **Step 4: Implement the data client**

In `web/src/lib/dataClient.js`, append:

```javascript
// Absent evaluation is normal: generation is best-effort and a failed meet
// simply has no file. Resolve null so the page renders without the section.
export const getEvaluation = (cat, meetId) =>
  get(`${cat}/${meetId}/evaluation.json`).catch(() => null)
```

Because `get()` caches the *promise*, a rejected fetch would be cached as a rejection; `.catch` here is applied per call and returns `null` each time, which is the behaviour we want (no retry storm, no unhandled rejection).

- [ ] **Step 5: Implement the section**

In `web/src/routes/Meet.svelte`:

1. Add `getEvaluation` to the existing import from `../lib/dataClient.js`.
2. Add the state declaration next to `let races = $state(null)`:

```javascript
  let evaluation = $state(null)
```

3. In `load()`, extend the `Promise.all` to fetch it alongside the rest:

```javascript
      const [m, r, e] = await Promise.all([
        getMeet(params.cat, params.meetId),
        getRaces(params.cat, params.meetId),
        getEvaluation(params.cat, params.meetId),
      ])
      meet = m
      races = r.races
      evaluation = e
```

4. Immediately after the closing `</div>` of `.chart-grid`, add:

```svelte
  {#if evaluation}
    <details class="coach">
      <summary>Trænerens vurdering <span class="muted">· AI-genereret, eksperimentelt</span></summary>
      {#each evaluation.sections as s (s.heading)}
        <h4>{s.heading}</h4>
        <p>{s.body}</p>
      {/each}
      <p class="muted fine">
        Denne vurdering er automatisk genereret af en sprogmodel ud fra stævnets tal.
        Den er eksperimentel og en fortolkning — ikke fakta. Alle tal kan efterprøves
        i tabellerne ovenfor. Genereret {evaluation.generated_at} · {evaluation.model_label}
      </p>
    </details>
  {/if}
```

5. In the component's `<style>` block, add:

```css
  .coach { margin: 1.5rem 0; }
  .coach summary { cursor: pointer; font-weight: 600; }
  .coach h4 { margin: 1rem 0 0.25rem; }
  .coach p { margin: 0; }
  .coach .fine { margin-top: 1rem; font-size: 0.8rem; line-height: 1.4; }
```

Match the surrounding style block's existing indentation and property ordering.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd web && npm test`
Expected: PASS — the three new render tests, the two new dataClient tests, and every pre-existing test.

If a pre-existing render test now fails because `getEvaluation` performs a real `fetch` under jsdom, add `vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)` to that test rather than changing the component.

- [ ] **Step 7: Look at it in a browser**

Run the `run-web` skill (or `cd web && npm run dev:bg`) with a hand-written `web/public/data/DM-L/<meetId>/evaluation.json` copied from the fixture, open the meet page, and confirm: the section sits below the charts, starts collapsed, the summary shows the experimental label, and the footer text wraps readably at mobile width. Take a screenshot for the PR.

- [ ] **Step 8: Commit**

```bash
git add web/src/lib/dataClient.js web/src/routes/Meet.svelte web/tests/fixtures/evaluation.json web/tests/dataClient.test.js web/tests/routes.render.test.js
git commit -m "feat(web): collapsible AI coach evaluation on meet pages"
```

---

### Task 9: Model comparison harness

The only code that reaches Bedrock, and the only step run by hand. Produces the evidence for the model choice.

**Files:**
- Create: `st-scrape/evaluation/compare.py`
- Modify: `Makefile`
- Modify: `docs/analytics.md`

**Interfaces:**
- Consumes: `webbuild.digest.build`, `evaluation.agent.{build_agent,SYSTEM_PROMPT,MeetEvaluation,PROMPT_VERSION}`, `evaluation.check.check_numbers`, `analytics.loader.connect`.
- Produces: `python -m evaluation.compare --meets CAT/ID,… --models ID,… --out FILE.html` → an HTML page plus a stdout table.

- [ ] **Step 1: Resolve the candidate model IDs and prices**

Before writing code, get the facts. Do not carry model IDs or prices over from memory or from this plan.

```bash
AWS_PROFILE=swimtrends aws bedrock list-foundation-models --region eu-west-1 \
  --query "modelSummaries[?contains(modelId,'claude') || contains(modelId,'nova') || contains(modelId,'mistral')].modelId" \
  --output table
AWS_PROFILE=swimtrends aws bedrock list-inference-profiles --region eu-west-1 \
  --query "inferenceProfileSummaries[?starts_with(inferenceProfileId,'eu.')].inferenceProfileId" \
  --output table
```

Pick four: two Claude tiers via their `eu.` cross-region inference profile (EU data residency), plus one Nova and one Mistral as cheap controls. Confirm each is enabled for the account (a model without access fails the first Converse call with `AccessDeniedException`, which we want to discover now, not on meet 1). Look up the per-MTok input/output price for each on the Bedrock pricing page — Bedrock pricing is separate from first-party Anthropic API pricing.

Record what you found as a comment block at the top of `compare.py`, dated, with the price per MTok you used. That comment is the audit trail for the cost column.

- [ ] **Step 2: Write the harness**

Create `st-scrape/evaluation/compare.py`:

```python
"""Side-by-side model comparison for the meet evaluation. Hand-run only.

Runs the SAME agent configuration against the same digests with each candidate
model, applies the deterministic number check, and writes an HTML page plus a
stdout table of pass rate, tokens, cost and latency. A human reads the Danish
and picks the winner; the number check then stays in the pipeline forever.

Model ids and prices resolved <DATE> from `aws bedrock list-inference-profiles`
and the Bedrock pricing page:

    <model id>   $<in>/MTok in, $<out>/MTok out
    ...

Costs printed here are estimates from those figures; they are not billing data.
"""
import argparse
import html
import os
import sys
import time
from pathlib import Path

from analytics.loader import connect
from evaluation import agent as ag
from evaluation.check import check_numbers
from webbuild import digest as dg

# model_id -> (input $/MTok, output $/MTok), from the comment block above.
PRICES: dict[str, tuple[float, float]] = {}


def _cost(model_id, tokens_in, tokens_out):
    if model_id not in PRICES:
        return None
    pin, pout = PRICES[model_id]
    return (tokens_in * pin + tokens_out * pout) / 1_000_000


def _usage(result):
    """Token usage off a Strands AgentResult, defensively: the metrics shape
    varies by SDK version, so fall back to zeros rather than crashing a run."""
    try:
        u = result.metrics.accumulated_usage
        return int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0))
    except Exception:
        return 0, 0


def run_one(con, category, meet_id, model_id, guardrail_id, guardrail_version):
    digest = dg.build(con, category, meet_id)
    agent = ag.build_agent(model_id=model_id, guardrail_id=guardrail_id,
                           guardrail_version=guardrail_version)
    from evaluation.cache import canonical_json
    t0 = time.monotonic()
    error, sections, offenders = None, [], set()
    try:
        result = agent(f"<digest>{canonical_json(digest)}</digest>",
                       structured_output_model=ag.MeetEvaluation)
        sections = [{"heading": s.heading, "body": s.body}
                    for s in result.structured_output.sections]
        offenders = check_numbers("\n".join(s["body"] for s in sections), digest)
        tin, tout = _usage(result)
    except Exception as e:                      # a candidate that errors is a result
        error, tin, tout = f"{type(e).__name__}: {e}", 0, 0
    return {
        "category": category, "meet_id": meet_id, "model_id": model_id,
        "seconds": round(time.monotonic() - t0, 1),
        "tokens_in": tin, "tokens_out": tout,
        "cost": _cost(model_id, tin, tout),
        "offenders": sorted(offenders), "sections": sections, "error": error,
    }


def _html(rows) -> str:
    out = ["<meta charset='utf-8'><title>Model comparison</title>",
           "<style>body{font:15px/1.5 system-ui;max-width:1200px;margin:2rem auto}",
           "table{border-collapse:collapse;margin-bottom:2rem}",
           "td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}",
           ".bad{color:#b00}.cols{display:flex;gap:1.5rem;align-items:flex-start}",
           ".col{flex:1;min-width:0}</style>",
           f"<p>prompt_version={html.escape(ag.PROMPT_VERSION)}</p>",
           "<table><tr><th>meet<th>model<th>numbers<th>in<th>out<th>$<th>s</tr>"]
    for r in rows:
        bad = "bad" if (r["offenders"] or r["error"]) else ""
        verdict = r["error"] or (", ".join(r["offenders"]) if r["offenders"] else "ok")
        cost = "-" if r["cost"] is None else f"{r['cost']:.4f}"
        out.append(
            f"<tr class='{bad}'><td>{html.escape(r['category'])}/{html.escape(r['meet_id'])}"
            f"<td>{html.escape(r['model_id'])}<td>{html.escape(verdict)}"
            f"<td>{r['tokens_in']}<td>{r['tokens_out']}<td>{cost}<td>{r['seconds']}</tr>")
    out.append("</table>")

    for meet in dict.fromkeys((r["category"], r["meet_id"]) for r in rows):
        out.append(f"<h2>{html.escape(meet[0])}/{html.escape(meet[1])}</h2><div class='cols'>")
        for r in [x for x in rows if (x["category"], x["meet_id"]) == meet]:
            out.append(f"<div class='col'><h3>{html.escape(r['model_id'])}</h3>")
            if r["error"]:
                out.append(f"<p class='bad'>{html.escape(r['error'])}</p>")
            for s in r["sections"]:
                out.append(f"<h4>{html.escape(s['heading'])}</h4>"
                           f"<p>{html.escape(s['body'])}</p>")
            out.append("</div>")
        out.append("</div>")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compare models on meet evaluations.")
    ap.add_argument("--meets", required=True, help="comma-separated CATEGORY/MEET_ID")
    ap.add_argument("--models", required=True, help="comma-separated Bedrock model ids")
    ap.add_argument("--out", type=Path, default=Path("db/model-eval.html"))
    args = ap.parse_args(argv)

    guardrail_id = os.environ.get("EVAL_GUARDRAIL_ID")
    guardrail_version = os.environ.get("EVAL_GUARDRAIL_VERSION")
    if not (guardrail_id and guardrail_version):
        raise SystemExit("set EVAL_GUARDRAIL_ID and EVAL_GUARDRAIL_VERSION")

    con = connect()
    meets = [tuple(m.strip().split("/", 1)) for m in args.meets.split(",") if m.strip()]
    rows = []
    for category, meet_id in meets:
        for model_id in [m.strip() for m in args.models.split(",") if m.strip()]:
            print(f"… {category}/{meet_id} on {model_id}", flush=True)
            rows.append(run_one(con, category, meet_id, model_id,
                                guardrail_id, guardrail_version))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_html(rows), encoding="utf-8")

    print(f"\n{'model':40} {'numbers':10} {'in':>7} {'out':>7} {'$/meet':>9} {'s':>6}")
    for r in rows:
        verdict = "ERROR" if r["error"] else ("FAIL" if r["offenders"] else "ok")
        cost = "-" if r["cost"] is None else f"{r['cost']:.4f}"
        print(f"{r['model_id'][:40]:40} {verdict:10} {r['tokens_in']:>7} "
              f"{r['tokens_out']:>7} {cost:>9} {r['seconds']:>6}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Add the Makefile target**

In `Makefile`, add (and append `eval-models` to `.PHONY`):

```make
# Compare candidate models on the same meets. Hand-run; reaches Bedrock.
# e.g. make eval-models MEETS=DM-L/12486,DM-L/11902 MODELS=id1,id2
eval-models:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation.compare \
		--meets $(MEETS) --models $(MODELS)
```

- [ ] **Step 4: Run the comparison**

Pick three meets with different shapes — a large senior LCM championship, a junior meet (`DMJ-L`, to read the tone on minors), and one from an early season with little history:

```bash
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli meets --category DM-L | head
cd .. && make eval-models MEETS=<cat/id>,<cat/id>,<cat/id> MODELS=<id1>,<id2>,<id3>,<id4>
```

Open `st-scrape/db/model-eval.html` and read all twelve reports. Judge on: does the Danish read like a coach; are the standout-swim sentences specific and correct; does the junior report stay inside the safety rules; is the "little history" report honest about it.

- [ ] **Step 5: Record the decision**

Append a section to `docs/analytics.md` with the table from stdout, the chosen model id, and one or two sentences on why. Set the chosen id as the documented `EVAL_MODEL_ID`, and add its human label to `MODEL_LABELS` in `evaluation/agent.py` so the page footer reads as a name rather than an id.

Then tune: if the guardrail's grounding check blocked a report that the number check passed, lower `GROUNDING_THRESHOLD` in the CDK stack a step and note it. If it passed something the number check caught, leave it — the number check is the backstop.

- [ ] **Step 6: Commit**

```bash
git add st-scrape/evaluation/compare.py st-scrape/evaluation/agent.py Makefile docs/analytics.md
git commit -m "feat(eval): model comparison harness and the model decision"
```

---

### Task 10: Verify, deploy, ship

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a merged PR and a live section on swimtrends.dk.

- [ ] **Step 1: Run every suite**

```bash
cd st-scrape && .venv/bin/python -m pytest -q
cd ../swimtrends-app && .venv/bin/python -m pytest tests/unit -q
cd ../web && npm test
```
Expected: all three green. Paste the actual counts into the PR body — do not claim a pass you have not seen.

- [ ] **Step 2: Document the feature in CLAUDE.md**

Add to the "Common commands" block:

```
# AI meet evaluations (needs EVAL_MODEL_ID + EVAL_GUARDRAIL_ID/_VERSION)
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation --out ../web/public/data --dry-run
```

And a bullet under "Domain conventions":

- **AI evaluations**: each meet page can carry a batch-generated Danish coach
  report. Every number in it must exist in the digest (`evaluation/check.py`);
  the text is cached by `sha256(digest + prompt/schema version + model id)`, so
  bumping `PROMPT_VERSION` regenerates all meets. Named-swimmer prose is limited
  to results facts — juniors are minors. See `docs/analytics.md`.

- [ ] **Step 3: Ask for confirmation, then deploy the guardrail**

The guardrail is a **CDK stack deploy** — infra, and per the repo guardrails it needs explicit confirmation. Ask the user, then:

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
npx aws-cdk@2.1133.0 deploy SwimtrendsEvaluationStack \
  --app ".venv/bin/python3 app.py" \
  -c alert_email=mortench.privat@gmail.com \
  --require-approval never
```

Docker must be running. `-c alert_email` is mandatory on every deploy in this app — omitting it deletes the existing SNS email subscription and alerts silently stop.

Capture the outputs:

```bash
AWS_PROFILE=swimtrends aws cloudformation describe-stacks \
  --stack-name SwimtrendsEvaluationStack --region eu-west-1 \
  --query "Stacks[0].Outputs" --output table
```

- [ ] **Step 4: Generate for real, one meet first**

```bash
export EVAL_MODEL_ID=<chosen id> EVAL_GUARDRAIL_ID=<id> EVAL_GUARDRAIL_VERSION=<version>
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation \
  --out ../web/public/data --meets <cat>/<id>
```

Read the generated `web/public/data/<cat>/<id>/evaluation.json`. Then run it again unchanged and confirm the second run reports `hit=1, generated=0` — that is the determinism guarantee working. Only then run the full set (no `--meets`).

- [ ] **Step 5: Open the PR**

```bash
git push -u origin ai-meet-evaluation
gh pr create --title "feat: AI coach evaluation on meet pages" --body "$(cat <<'EOF'
Batch-generated Danish coach-style evaluation on each meet page, behind a
collapsed `<details>` below the charts.

- `webbuild/digest.py` — the only facts the model sees (facts, 6-season history,
  top swims, per-stroke trend, precomputed percentage deltas).
- `evaluation/` — Strands agent on Bedrock Converse with a versioned Guardrail,
  content-addressed S3 cache, deterministic number check, batch CLI.
- CDK: `SwimtrendsEvaluationStack` — guardrail with three denied topics plus a
  contextual grounding check.
- Web: collapsible section, labelled AI-generated and experimental, with the
  numbers checkable in the tables above it.

Same data + same prompt + same model → byte-identical published text. No runtime
LLM endpoint, no per-view cost. A failed generation leaves the page unchanged.

Model choice and the comparison table: `docs/analytics.md`.
Spec: `docs/superpowers/specs/2026-07-27-ai-meet-evaluation-design.md`
Plan: `docs/superpowers/plans/2026-07-27-ai-meet-evaluation.md`

Tests: st-scrape <N> passed, CDK <N> passed, web <N> passed.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Attach the screenshot from Task 8 Step 7.

- [ ] **Step 6: After the PR merges, publish**

The SPA deploys itself: `.github/workflows/ci.yml` builds and publishes it on every merge to `master`. Watch that run finish, then publish the data — CI never deploys data:

```bash
gh run watch                       # the deploy job on the merge commit
git checkout master && git pull
make web-refresh                   # ~50 min; webbuild is silent until "wrote N files"
```

`web-refresh` is webbuild → web-eval → sync → invalidate. This step is required here even though the change is mostly frontend, because `evaluation.json` is generated data that only `web-eval` produces. Web deploys are low-stakes and need no confirmation. Then load a meet page on swimtrends.dk and confirm the section is there.

---

## Self-review

**Spec coverage.** Digest scope → Tasks 1–2. Two-step offline pipeline, `webbuild` never calling Bedrock → Task 6. Cache key including prompt/schema/model, `--force` revoke → Tasks 3, 6. Agent via Strands `BedrockModel`/Converse, structured output, no tools, `max_tokens` sizing, prompt caching → Task 5. Named-swimmer policy in prompt **and** guardrail → Tasks 5, 7. Guardrail with denied topics, numbered version, grounding thresholds → Task 7. Number check with retry → Tasks 4, 5. Frontend section, collapsed, disclosure copy, 404 → absent → Task 8. Model evaluation with pass rate/tokens/cost/latency and live-verified IDs and prices → Task 9. Error handling (skip, never delete a good cached report, never block the refresh) → Task 6. Testing matrix → every task. Cost/ops and IAM scoping → Global Constraints, Task 10.

**Deliberate deviation from the spec.** The spec allowed percentages "if derivable from two digest numbers"; the plan instead precomputes them into `digest["derived"]` and forbids the model from calculating at all. Same reader-facing output, but the number check needs no arithmetic-licensing special case and stays a simple set-membership test. This tightening is described in Task 2 Step 3.

**Placeholders.** Two intentional fill-ins, both with an explicit resolution step rather than a guess: the `strands-agents` version floor (Task 5 Step 1 installs it and records what resolved) and the model IDs/prices in `compare.py` (Task 9 Step 1 queries Bedrock and the pricing page). Both are values that would be wrong if invented from memory.

**Type consistency.** `digest.build(con, category, meet_id)` returns the six keys used identically in Tasks 3, 4, 5, 6, 9. `cache_key(digest, *, prompt_version, schema_version, model_id)` is called with those exact keywords in Tasks 3, 6. `evaluate(digest, *, agent, retries=1)` returns `list[dict]` with `heading`/`body`, matching the `sections` array read by the frontend fixture and `Meet.svelte`. `check_numbers(text, digest) -> set` is used consistently in Tasks 4, 5, 9. `HEADINGS` is the single source for the four headings in the schema validator, the prompt, and the web fixture. `getEvaluation(cat, meetId)` matches the `dataClient` naming of `getMeet`/`getRaces`.
