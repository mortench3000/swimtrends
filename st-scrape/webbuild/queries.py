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
