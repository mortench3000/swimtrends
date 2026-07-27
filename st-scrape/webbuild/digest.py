"""The digest: the only facts the evaluation agent is allowed to see.

Pure SQL over the curated views, deterministic for a given (category, meet).
Every number that may appear in a published evaluation comes from here — see
evaluation/check.py, which enforces exactly that.

Window: the meet's own season plus the five prior seasons ON RECORD (not
season-5, since a category may have gaps).
"""

from webbuild.queries import _meet_is_combined

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
