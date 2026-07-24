"""One function per JSON payload. Each takes a bound DuckDB connection."""

from webbuild.shape import race_key

ATTRIBUTION = "Data fra svømmetider.dk"

_MEET_FACTS_SQL = """
    SELECT count(*) AS swims,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           count(DISTINCT swimmer_id) FILTER (WHERE is_junior) AS juniors,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND class = 'open'
"""

_MEET_COMPARE_SQL = """
    SELECT season,
           count(DISTINCT swimmer_id) AS entrants,
           count(DISTINCT (gender, distance, stroke, course)) AS events,
           count(DISTINCT club) AS clubs,
           CAST(quantile_cont(points, 0.5) AS BIGINT) AS median_points,
           max(points) AS top_points
    FROM results_by_category
    WHERE category = ? AND season <= ? AND class = 'open'
    GROUP BY season
    ORDER BY season DESC
    LIMIT 5
"""

# Elite depth per season: median WA points among the top 10 (by points) in EACH
# individual event, pooled. A swimmer's heat/final is deduped to their best per
# event first; only scored open swims count.
_MEET_ELITE_SQL = """
    WITH best AS (
        SELECT season, gender, distance, stroke, course, swimmer_id,
               max(points) AS pts
        FROM results_by_category
        WHERE category = ? AND season <= ? AND class = 'open'
          AND points IS NOT NULL AND swimmer_id IS NOT NULL
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


def build_index(con) -> dict:
    rows = con.execute(
        "SELECT category, list(DISTINCT season ORDER BY season DESC) AS seasons "
        "FROM results_by_category WHERE class = 'open' GROUP BY category ORDER BY category"
    ).fetchall()
    return {
        "attribution": ATTRIBUTION,
        "categories": [{"code": cat, "seasons": seasons} for cat, seasons in rows],
    }


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


def build_meets(con, category: str) -> dict:
    rows = con.execute(
        """
        SELECT meet_id, any_value(meet_name) AS meet_name,
               any_value(meet_date) AS meet_date, any_value(season) AS season,
               count(DISTINCT swimmer_id) AS entrants,
               count(DISTINCT (gender, distance, stroke, course)) AS events,
               count(DISTINCT club) AS clubs
        FROM results_by_category
        WHERE category = ? AND class = 'open'
        GROUP BY meet_id
        ORDER BY season DESC, meet_date DESC
        """,
        [category],
    ).fetchall()
    cols = ["meet_id", "meet_name", "meet_date", "season", "entrants", "events", "clubs"]
    rel = dict(con.execute(_MEETS_RELAY_EVENTS_SQL, [category]).fetchall())
    result = [dict(zip(cols, r)) for r in rows]
    for m in result:
        m["events"] += rel.get(m["meet_id"], 0)
    return {"category": category, "meets": result}


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
    # Elite (top-10-per-event) median points, keyed by season, merged into the
    # facts (this meet's season) and each comparison row.
    elite = dict(con.execute(_MEET_ELITE_SQL, [category, head[2]]).fetchall())
    facts["elite_median_points"] = elite.get(head[2])
    for c in comp:
        c["elite_median_points"] = elite.get(c["season"])
    facts["events"] += con.execute(
        _MEET_RELAY_EVENTS_SQL, [category, meet_id]).fetchone()[0]
    rel_by_season = dict(con.execute(
        _MEET_RELAY_EVENTS_BY_SEASON_SQL, [category, head[2]]).fetchall())
    for c in comp:
        c["events"] += rel_by_season.get(c["season"], 0)
    return {"category": category, "meet_id": meet_id, "meet_name": head[0],
            "meet_date": head[1], "season": head[2],
            "facts": facts, "season_comparison": comp}


_RACES_SQL = """
    SELECT gender, distance, stroke, course,
           count(DISTINCT swimmer_id) AS contestants,
           arg_min(name, completed_centiseconds)
               FILTER (WHERE phase IN ('final','timed_final')) AS winner_name,
           arg_min(completed_time, completed_centiseconds)
               FILTER (WHERE phase IN ('final','timed_final')) AS winning_time
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND NOT is_dq AND class = 'open'
    GROUP BY gender, distance, stroke, course
    ORDER BY gender, distance, stroke, course
"""


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


_RACE_FACTS_SQL = """
    WITH e AS (
        SELECT * FROM results_by_category
        WHERE category = ? AND meet_id = ?
          AND gender = ? AND distance = ? AND stroke = ? AND course = ?
          AND class = 'open'
    ),
    fin AS (SELECT * FROM e WHERE phase IN ('final','timed_final') AND NOT is_dq),
    heats AS (
        SELECT completed_centiseconds,
               row_number() OVER (ORDER BY completed_centiseconds) AS hr
        FROM e WHERE phase = 'heats' AND NOT is_dq
    )
    SELECT
        (SELECT count(DISTINCT swimmer_id) FROM e WHERE NOT is_dq) AS contestants,
        (SELECT arg_min(completed_time, completed_centiseconds) FROM fin) AS winning_time,
        (SELECT max(points) FROM fin) AS winner_points,
        (SELECT completed_centiseconds FROM heats WHERE hr = 8) AS cutline_cs,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds)
         FROM (SELECT completed_centiseconds FROM heats WHERE hr <= 8)) AS spread_1_8_cs,
        (SELECT max(completed_centiseconds) - min(completed_centiseconds) FROM e WHERE NOT is_dq) AS spread_1_last_cs,
        (SELECT CAST(quantile_cont(completed_centiseconds, 0.5) AS BIGINT) FROM e WHERE NOT is_dq) AS median_cs,
        (SELECT CAST(quantile_cont(points, 0.5) AS BIGINT) FROM e WHERE NOT is_dq) AS median_points,
        (SELECT count(DISTINCT swimmer_id) FROM e WHERE is_junior) AS juniors
"""

_RACE_DSQ_SQL = """
    SELECT count(*) FROM results
    WHERE meet_id = ? AND gender = ? AND distance = ? AND stroke = ?
      AND course = ? AND is_dq AND NOT is_relay AND class = 'open'
"""

_PODIUM_SQL = """
    SELECT rank, name, swimmer_id, club, completed_time AS time, points
    FROM results_by_category
    WHERE category = ? AND meet_id = ? AND gender = ? AND distance = ?
      AND stroke = ? AND course = ? AND phase IN ('final','timed_final')
      AND rank IN (1, 2, 3) AND class = 'open'
    ORDER BY rank
"""

# ponytail: para not excluded here — event_standard_by_season/final_cutline_by_season
# are pre-aggregated without class; deferred to Plan 2.
_RACE_COMPARE_SQL = """
    SELECT s.season, s.best_cs, CAST(s.median_cs AS BIGINT) AS median_cs,
           CAST(s.top8_avg_cs AS BIGINT) AS top8_avg_cs,
           c.cutline_centiseconds AS cutline_cs, s.swims
    FROM event_standard_by_season s
    LEFT JOIN final_cutline_by_season c USING (category, season, course, gender, distance, stroke)
    WHERE s.category = ? AND s.gender = ? AND s.distance = ? AND s.stroke = ?
      AND s.course = ? AND s.season <= ?
    ORDER BY s.season DESC
    LIMIT 5
"""


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


def _meet_is_combined(con, meet_id) -> bool:
    """True when the meet is tagged with a senior (non-junior) category alongside a
    junior one. At such a meet juniors have no separate final, so the junior title
    comes from the qualifying swim (see analytics/views/60_junior.sql). Detected via
    the raw category list on cur_dim_meet: needs both a tag not starting with 'DMJ'
    (a senior tag) and a tag starting with 'DMJ' (a junior tag)."""
    row = con.execute(
        "SELECT category FROM cur_dim_meet WHERE meet_id = ?", [meet_id]).fetchone()
    if not row:
        return False
    cats = row[0]
    return (any(not c.startswith("DMJ") for c in cats)
            and any(c.startswith("DMJ") for c in cats))


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


def build_race(con, category, meet_id, gender, distance, stroke, course, relay_count=1) -> dict:
    if relay_count > 1:
        return _build_relay_race(con, category, meet_id, gender, distance, stroke, course, relay_count)
    if category == "DMJ-L" and _meet_is_combined(con, meet_id):
        return _build_junior_race(con, meet_id, gender, distance, stroke, course)
    args = [category, meet_id, gender, distance, stroke, course]
    fact_cols = ["contestants", "winning_time", "winner_points",
                 "cutline_centiseconds", "spread_1_8_cs", "spread_1_last_cs",
                 "median_cs", "median_points", "juniors"]
    facts = dict(zip(fact_cols, con.execute(_RACE_FACTS_SQL, args).fetchone()))
    # DSQ rows are excluded from results_by_category (individual_results filters
    # NOT is_dq upstream, see analytics/views/00_base.sql), so they must be
    # counted from the base `results` view instead. Not category-scoped, but
    # the meet_id + event tuple already pins the data unambiguously.
    facts["dsq"] = con.execute(
        _RACE_DSQ_SQL, [meet_id, gender, distance, stroke, course]).fetchone()[0]
    facts["cutline_time"] = None  # centiseconds is the comparable value; label formatted client-side
    season = con.execute(
        "SELECT any_value(season) FROM results_by_category WHERE meet_id = ?",
        [meet_id]).fetchone()[0]
    podium = [dict(zip(["rank", "name", "swimmer_id", "club", "time", "points"], r))
              for r in con.execute(_PODIUM_SQL, args).fetchall()]
    comp_cols = ["season", "best_cs", "median_cs", "top8_avg_cs", "cutline_cs", "swims"]
    comp = [dict(zip(comp_cols, r)) for r in con.execute(
        _RACE_COMPARE_SQL,
        [category, gender, distance, stroke, course, season]).fetchall()]
    return {"category": category, "meet_id": meet_id,
            "race_key": race_key(gender, distance, stroke, course),
            "label": f"{gender} {distance}m {stroke}",
            "is_relay": False, "junior_scoped": False,
            "facts": facts, "podium": podium, "season_comparison": comp}
