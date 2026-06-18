import duckdb

from ingestion import cli


def test_query_runs_one_shot_sql_and_prints(capsys):
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT 42 AS answer")
    rc = cli.run(
        ["query", "--sql", "SELECT answer FROM t"],
        registry=None, invoke=None, connect=lambda: con,
    )
    assert rc == 0
    assert "42" in capsys.readouterr().out
