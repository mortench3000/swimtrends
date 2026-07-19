"""One function per JSON payload. Each takes a bound DuckDB connection."""

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
