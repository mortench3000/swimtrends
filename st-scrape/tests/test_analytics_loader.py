import duckdb

from analytics import loader
from tests.analytics_fixtures import build_curated


def _con(**rows):
    con = duckdb.connect()
    build_curated(con, **rows)
    loader.create_views(con)
    return con


def test_create_views_defines_base_views():
    con = _con()
    names = {r[0] for r in con.execute(
        "SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
    assert {"results", "individual_results"} <= names


def test_individual_results_excludes_dq_and_relays():
    con = _con(obt=[
        dict(result_id="r1", swimmer_id="s1", rank=1, relay_count=1, type="Final",
             season=2024, birth_year=2008),
        dict(result_id="r2", swimmer_id="s2", rank=-1, relay_count=1, type="Final",
             season=2024, birth_year=2009),                       # DQ
        dict(result_id="r3", swimmer_id=None, rank=1, relay_count=4, type="Final",
             season=2024, birth_year=None),                        # relay
    ])
    ids = [r[0] for r in con.execute(
        "SELECT result_id FROM individual_results ORDER BY result_id").fetchall()]
    assert ids == ["r1"]


def test_results_derives_age_and_phase():
    con = _con(obt=[
        dict(result_id="r1", swimmer_id="s1", rank=1, relay_count=1, type="Heats",
             season=2024, birth_year=2008),
    ])
    age, phase = con.execute(
        "SELECT age, phase FROM results WHERE result_id = 'r1'").fetchone()
    assert age == 16
    assert phase == "heats"


def test_assemble_sql_includes_s3_source_binding():
    sql = loader.assemble_sql()
    assert "read_parquet('s3://swimtrends-meet-data/curated/obt_result/" in sql
    assert "credential_chain" in sql
    assert "hive_partitioning = false" in sql  # season/course come from file columns
    # base views must come after the source binding
    assert sql.index("CREATE SECRET") < sql.index("CREATE OR REPLACE VIEW results")


def test_assemble_sql_binds_all_five_curated_tables():
    sql = loader.assemble_sql()
    for table in ["obt_result", "dim_meet", "dim_race", "fact_result", "fact_split"]:
        assert f"curated/{table}/" in sql
