"""Top-level 'what data do we have' queries over the curated zone.

Read straight off the source-bound cur_obt / cur_dim_meet tables (no analytical
views needed), so these work against both the S3 zone and the in-memory test
fixtures. Each function takes a live DuckDB connection and returns plain rows;
render_table() formats them for the CLI.
"""


def list_meets(con, *, category=None, season=None, ascending=False):
    """One row per meet, sorted by season (descending by default; ascending=True
    for oldest-first). races = distinct race_id, results = result rows,
    dsq = rank -1. Optional category/season filters."""
    where, params = [], []
    if category is not None:
        where.append("list_contains(m.category, ?)"); params.append(category)
    if season is not None:
        where.append("m.season = ?"); params.append(season)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    direction = "ASC" if ascending else "DESC"
    rows = con.execute(f"""
        SELECT m.season, m.meet_id, m.course, m.meet_date, m.venue,
               list_sort(m.category) AS categories, m.meet_name,
               count(DISTINCT o.race_id)          AS races,
               count(o.result_id)                 AS results,
               count(*) FILTER (WHERE o.rank = -1) AS dsq
        FROM cur_dim_meet m
        LEFT JOIN cur_obt o USING (meet_id)
        {clause}
        GROUP BY m.season, m.meet_id, m.course, m.meet_date, m.venue, m.category, m.meet_name
        ORDER BY m.season {direction}, m.meet_id
    """, params).fetchall()
    cols = ["season", "meet_id", "course", "meet_date", "venue", "categories",
            "meet_name", "races", "results", "dsq"]
    return [dict(zip(cols, r)) for r in rows]


def list_categories(con):
    """One row per championship category: meet count, season span, result total.
    A meet tagged with several categories counts under each."""
    rows = con.execute("""
        WITH mc AS (
            SELECT meet_id, season, cat
            FROM cur_dim_meet CROSS JOIN UNNEST(category) AS t(cat))
        SELECT mc.cat AS category,
               count(DISTINCT mc.meet_id) AS meets,
               min(mc.season) AS season_min, max(mc.season) AS season_max,
               count(o.result_id) AS results
        FROM mc LEFT JOIN cur_obt o USING (meet_id)
        GROUP BY mc.cat
        ORDER BY mc.cat
    """).fetchall()
    cols = ["category", "meets", "season_min", "season_max", "results"]
    return [dict(zip(cols, r)) for r in rows]


def summary(con):
    """Top-level totals for the whole curated zone."""
    meets, smin, smax = con.execute(
        "SELECT count(DISTINCT meet_id), min(season), max(season) "
        "FROM cur_dim_meet").fetchone()
    results, = con.execute("SELECT count(*) FROM cur_obt").fetchone()
    swimmers, = con.execute(
        "SELECT count(DISTINCT swimmer_id) FROM cur_obt "
        "WHERE swimmer_id IS NOT NULL").fetchone()
    cats = [r[0] for r in con.execute(
        "SELECT DISTINCT unnest(category) AS c FROM cur_dim_meet ORDER BY c"
    ).fetchall()]
    return {"meets": meets, "results": results, "swimmers": swimmers,
            "season_min": smin, "season_max": smax, "categories": cats}


def render_table(headers, rows):
    """Aligned fixed-width text table. Cells stringified; lists -> comma-joined."""
    def cell(v):
        if isinstance(v, (list, tuple)):
            return ",".join(map(str, v))
        return "" if v is None else str(v)

    srows = [[cell(v) for v in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in srows:
        for i, c in enumerate(row):
            widths[i] = max(widths[i], len(c))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    out = [fmt.format(*headers)]
    out += [fmt.format(*row) for row in srows]
    return "\n".join(out)
