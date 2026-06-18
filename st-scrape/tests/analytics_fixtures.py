"""Build in-memory curated base tables for analytics view tests (no S3).

Mirrors the Spec 2 curated schema (curate/parquet.py). Each builder creates a
`cur_*` table that the analytics views bind to, so view SQL is exercised exactly
as in production but against hand-built rows instead of S3 Parquet.
"""

OBT_COLS = [
    ("result_id", "VARCHAR"), ("race_id", "BIGINT"), ("meet_id", "VARCHAR"),
    ("rank", "BIGINT"), ("name", "VARCHAR"), ("swimmer_id", "VARCHAR"),
    ("nationality", "VARCHAR"), ("club", "VARCHAR"), ("birth_year", "BIGINT"),
    ("completed_time", "VARCHAR"), ("completed_centiseconds", "BIGINT"),
    ("points", "BIGINT"), ("points_fixed", "BIGINT"), ("season", "BIGINT"),
    ("course", "VARCHAR"), ("meet_name", "VARCHAR"), ("venue", "VARCHAR"),
    ("meet_date", "VARCHAR"), ("number", "BIGINT"), ("race_name", "VARCHAR"),
    ("distance", "BIGINT"), ("stroke", "VARCHAR"), ("gender", "VARCHAR"),
    ("relay_count", "BIGINT"), ("type", "VARCHAR"), ("class", "VARCHAR"),
]
MEET_COLS = [
    ("meet_id", "VARCHAR"), ("meet_name", "VARCHAR"), ("venue", "VARCHAR"),
    ("course", "VARCHAR"), ("season", "BIGINT"), ("meet_date", "VARCHAR"),
    ("category", "VARCHAR[]"),
]
SPLIT_COLS = [
    ("result_id", "VARCHAR"), ("race_id", "BIGINT"), ("distance", "BIGINT"),
    ("split_time", "VARCHAR"), ("split_centiseconds", "BIGINT"),
    ("cumulative_time", "VARCHAR"), ("cumulative_centiseconds", "BIGINT"),
    ("season", "BIGINT"), ("course", "VARCHAR"),
]


def _create(con, name, cols, rows):
    coldef = ", ".join(f"{c} {t}" for c, t in cols)
    con.execute(f"CREATE OR REPLACE TABLE {name} ({coldef})")
    if rows:
        names = [c for c, _ in cols]
        placeholders = ", ".join("?" for _ in cols)
        con.executemany(
            f"INSERT INTO {name} VALUES ({placeholders})",
            [[r.get(n) for n in names] for r in rows],
        )


def build_curated(con, *, obt=None, meets=None, splits=None):
    """Create cur_obt / cur_dim_meet / cur_fact_split from lists of dicts.

    Every view in the catalog binds to these three names, so all three are
    always created (empty by default) to keep create_views() resolvable."""
    _create(con, "cur_obt", OBT_COLS, obt or [])
    _create(con, "cur_dim_meet", MEET_COLS, meets or [])
    _create(con, "cur_fact_split", SPLIT_COLS, splits or [])
    return con
