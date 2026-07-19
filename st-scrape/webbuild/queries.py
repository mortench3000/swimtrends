"""One function per JSON payload. Each takes a bound DuckDB connection."""

ATTRIBUTION = "Data fra svømmetider.dk"


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
