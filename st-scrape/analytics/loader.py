"""Assemble and execute the analytics SQL against a DuckDB connection.

create_views() depends only on the cur_* names existing (S3 views in
production, fixture tables in tests). bind_s3() supplies the production cur_*
views from S3. connect() is the production entry point used by the CLI.
"""
from pathlib import Path

import duckdb

_DIR = Path(__file__).resolve().parent
BOOTSTRAP_SQL = _DIR / "bootstrap.sql"
VIEWS_DIR = _DIR / "views"


def _view_files():
    return sorted(VIEWS_DIR.glob("*.sql"))


def create_views(con):
    """Define the base + analytical views. Requires cur_* to already exist."""
    for path in _view_files():
        con.execute(path.read_text(encoding="utf-8"))
    return con


def bind_s3(con):
    """Load S3 extensions + secret and define the cur_* source-binding views."""
    con.execute(BOOTSTRAP_SQL.read_text(encoding="utf-8"))
    return con


def assemble_sql():
    """Full bootstrap + views SQL as one script (for notebooks / duckdb CLI -init)."""
    parts = [BOOTSTRAP_SQL.read_text(encoding="utf-8")]
    parts += [p.read_text(encoding="utf-8") for p in _view_files()]
    return "\n\n".join(parts)


def connect():
    """Production: an in-memory DuckDB bound to the curated zone with all views."""
    con = duckdb.connect()
    bind_s3(con)
    create_views(con)
    return con
