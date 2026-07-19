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


def build_index(con) -> dict:
    rows = con.execute(
        "SELECT category, list(DISTINCT season ORDER BY season DESC) AS seasons "
        "FROM results_by_category GROUP BY category ORDER BY category"
    ).fetchall()
    return {
        "attribution": ATTRIBUTION,
        "categories": [{"code": cat, "seasons": seasons} for cat, seasons in rows],
    }


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


_RACES_SQL = """
    SELECT gender, distance, stroke, course,
           count(DISTINCT swimmer_id) AS contestants,
           arg_min(name, completed_centiseconds)
               FILTER (WHERE phase IN ('final','timed_final')) AS winner_name,
           arg_min(completed_time, completed_centiseconds)
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
      AND course = ? AND is_dq AND NOT is_relay
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
