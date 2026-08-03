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
#
# The ORDER BY must be a TOTAL order. `points DESC` alone is not: when several
# swims tie across the LIMIT cutoff, DuckDB returns whichever it scanned first,
# so the digest — the model's entire world, and part of the evaluation cache
# key — changes between two calls on unchanged data. Measured on the live zone:
# six builds of DM-K/10340 gave 5 different top_swims (three swimmers tie on
# 845), and DM-L/10334 alternated its last row between two swimmers on 779.
# The cost is a silently invalidated cache entry (a paid regeneration), a
# published report naming a swimmer the next build drops, and false positives
# in any check that compares published text against a fresh digest.
# params: category, meet_id
_TOP_SWIMS_SQL = f"""
    SELECT name, club, event, completed_time AS time, points, rank
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
      AND points IS NOT NULL AND swimmer_id IS NOT NULL
    QUALIFY row_number() OVER (
        PARTITION BY swimmer_id, gender, distance, stroke, course
        ORDER BY points DESC) = 1
    ORDER BY points DESC, name, distance, stroke, gender LIMIT {TOP_N}
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
    ORDER BY points DESC, name, distance, stroke, gender LIMIT {TOP_N}
"""

# --- per-entity aggregates within one meet ------------------------------------
# The phase/rank rule -- a heat win is not a medal, a timed final counts as a
# final, and dead heats share a rank so one event can yield two titles -- is
# medal_count's definition (analytics/views/50_field_evolution.sql). medal_count
# carries no class filter; these queries additionally exclude para swims
# (WHERE class = 'open'), so titles and podiums here count open results only.
# Counted per result row for exactly that reason.
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
               count(*) FILTER (WHERE {_FINAL_PHASES} AND rank = 1
                                  AND points IS NOT NULL) AS titles,
               count(*) FILTER (WHERE {_FINAL_PHASES}
                                  AND rank BETWEEN 1 AND 3
                                  AND points IS NOT NULL) AS podiums
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
               count(*) FILTER (WHERE junior_rank = 1
                                  AND points IS NOT NULL) AS titles,
               count(*) FILTER (WHERE junior_rank BETWEEN 1 AND 3
                                  AND points IS NOT NULL) AS podiums
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
# `wins` dedups to one row per swimmer per event before counting: a para
# override (`swimtrends class set`) can leave a final AND its duplicate timed
# final both class='open' for the same swim, and counting rows would then
# inflate that swimmer's title count and can wrongly admit a two-title
# swimmer to the block. `phase` breaks the tie deterministically when the
# duplicate rows also tie on points -- the only way two rows share a
# (swimmer_id, event) here. points IS NOT NULL matches _TOP_SWIMS_SQL: a rank-1
# final with no base time is not a scored title, and every points value
# elsewhere in the digest is non-null.
#
# The outer ORDER BY is total (swimmer_id last), and it also groups each
# swimmer's rows together so _multi_title_swimmers can fold them in one pass.
# params: category, meet_id
_MULTI_TITLE_SQL = f"""
    WITH wins AS (
        SELECT swimmer_id, name, club, event, stroke, points
        FROM results_by_category
        WHERE category = ? AND meet_id = ? AND class = 'open'
          AND {_FINAL_PHASES} AND rank = 1 AND swimmer_id IS NOT NULL
          AND points IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY swimmer_id, event ORDER BY points DESC, phase) = 1
    )
    SELECT swimmer_id, name, club, event, stroke, points,
           count(*) OVER (PARTITION BY swimmer_id) AS titles
    FROM wins
    QUALIFY titles >= {MIN_TITLES}
    ORDER BY titles DESC, name, swimmer_id, points DESC, event
"""

# params: meet_id
# junior_championship holds at most one row per swimmer per event (it filters
# phase IN ('heats', 'timed_final')), so the dedup below never removes a real
# row here -- it only keeps this query the same shape as its senior pair.
_JUNIOR_MULTI_TITLE_SQL = f"""
    WITH wins AS (
        SELECT swimmer_id, name, club, event, stroke, points
        FROM junior_championship
        WHERE meet_id = ? AND junior_rank = 1 AND points IS NOT NULL
        QUALIFY row_number() OVER (
            PARTITION BY swimmer_id, event ORDER BY points DESC) = 1
    )
    SELECT swimmer_id, name, club, event, stroke, points,
           count(*) OVER (PARTITION BY swimmer_id) AS titles
    FROM wins
    QUALIFY titles >= {MIN_TITLES}
    ORDER BY titles DESC, name, swimmer_id, points DESC, event
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
    club_cols = ["club", "swimmers", "titles", "podiums", "rank"]
    if junior:
        top = con.execute(_JUNIOR_TOP_SWIMS_SQL, [meet_id]).fetchall()
        strokes = con.execute(_JUNIOR_BY_STROKE_SQL,
                              [oldest, season, season, season]).fetchall()
        clubs = con.execute(_JUNIOR_CLUBS_SQL, [meet_id]).fetchall()
        multi = con.execute(_JUNIOR_MULTI_TITLE_SQL, [meet_id]).fetchall()
    else:
        top = con.execute(_TOP_SWIMS_SQL, [category, meet_id]).fetchall()
        strokes = con.execute(_BY_STROKE_SQL,
                              [category, oldest, season, season, season]).fetchall()
        clubs = con.execute(_CLUBS_SQL, [category, meet_id]).fetchall()
        multi = con.execute(_MULTI_TITLE_SQL, [category, meet_id]).fetchall()

    return {
        "meet": {"name": head[0], "date": head[1], "season": season,
                 "category": category, "course": head[3]},
        "facts": facts,
        "season_history": history,
        "top_swims": [dict(zip(swim_cols, r)) for r in top],
        "clubs": [dict(zip(club_cols, r)) for r in clubs],
        "multi_title_swimmers": _multi_title_swimmers(multi),
        "by_stroke": _with_stroke_deltas([dict(zip(stroke_cols, r)) for r in strokes]),
        "derived": _derived(facts, history),
    }
