"""The digest: the only facts the evaluation agent is allowed to see.

Pure SQL over the curated views, deterministic for a given (category, meet).
Every number that may appear in a published evaluation comes from here — see
evaluation/check.py, which enforces exactly that.

Window: the meet's own season plus the five prior seasons ON RECORD (not
season-5, since a category may have gaps).
"""

from webbuild.queries import _MEET_RELAY_EVENTS_SQL, _meet_is_combined

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
    -- Defensive, not load-bearing: junior_championship already filters to
    -- phase IN ('heats', 'timed_final'), so a junior appears at most once
    -- per event here; this mirrors the senior query's dedup for symmetry.
    QUALIFY row_number() OVER (
        PARTITION BY swimmer_id, gender, distance, stroke, course
        ORDER BY points DESC) = 1
    ORDER BY points DESC LIMIT {TOP_N}
"""

# median points this season vs the mean of the prior seasons in the window.
# `oldest` is history[-1]["season"] — the on-record window already computed
# for season_history — NOT season - 5, since a category may have gaps.
# per stroke x distance group. params: category, oldest, season, season, season
_BY_STROKE_SQL = f"""
    WITH best AS (
        SELECT season, stroke, {_DIST_GROUP} AS dist_group, swimmer_id,
               gender, distance, course, max(points) AS pts
        FROM results_by_category
        WHERE category = ? AND season BETWEEN ? AND ? AND class = 'open'
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

# params: oldest, season, season, season
_JUNIOR_BY_STROKE_SQL = f"""
    WITH best AS (
        SELECT season, stroke, {_DIST_GROUP} AS dist_group, swimmer_id,
               gender, distance, course, max(points) AS pts
        FROM junior_championship
        WHERE season BETWEEN ? AND ? AND points IS NOT NULL
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


def _with_stroke_deltas(rows: list[dict]) -> list[dict]:
    """Precomputed median_points - prev5_median per by_stroke row, so the
    report can quote a stroke's movement without subtracting two medians
    itself — same principle as _derived, applied at stroke granularity.
    None when there's no prior-window median (an early-season meet with no
    history), same as prev5_median itself.
    """
    for r in rows:
        r["delta"] = (r["median_points"] - r["prev5_median"]
                      if r["prev5_median"] is not None else None)
    return rows


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

    # Relay events on top of the individual count, exactly as queries.build_meet
    # does for the page's "Løb" tile. Without this the digest licenses an events
    # number that contradicts the tile the reader is told to check it against.
    # Senior-scoped in both places (there is no junior-relay title).
    facts["events"] += con.execute(
        _MEET_RELAY_EVENTS_SQL, [category, meet_id]).fetchone()[0]

    facts["elite_median_points"] = elite.get(season)
    hist_cols = ["season", "entrants", "clubs", "median_points"]
    history = [dict(zip(hist_cols, r)) for r in hist_rows]
    for h in history:
        h["elite_median_points"] = elite.get(h["season"])

    # by_stroke must use the SAME on-record window as season_history — a
    # category with a gap makes calendar arithmetic (season - 5) wrong.
    oldest = history[-1]["season"] if history else season

    swim_cols = ["name", "club", "event", "time", "points", "rank"]
    stroke_cols = ["stroke", "dist_group", "median_points", "prev5_median"]
    if junior:
        top = con.execute(_JUNIOR_TOP_SWIMS_SQL, [meet_id]).fetchall()
        strokes = con.execute(_JUNIOR_BY_STROKE_SQL,
                              [oldest, season, season, season]).fetchall()
    else:
        top = con.execute(_TOP_SWIMS_SQL, [category, meet_id]).fetchall()
        strokes = con.execute(_BY_STROKE_SQL,
                              [category, oldest, season, season, season]).fetchall()

    return {
        "meet": {"name": head[0], "date": head[1], "season": season,
                 "category": category, "course": head[3]},
        "facts": facts,
        "season_history": history,
        "top_swims": [dict(zip(swim_cols, r)) for r in top],
        "by_stroke": _with_stroke_deltas([dict(zip(stroke_cols, r)) for r in strokes]),
        "derived": _derived(facts, history),
    }
