import sys

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


def test_main_query_does_not_require_ingestion_env(monkeypatch, capsys):
    # The documented `swimtrends query` path must work for an analyst who only
    # has AWS creds — not the ingestion REGISTRY_TABLE/DISPATCHER_FUNCTION env.
    con = duckdb.connect()
    con.execute("CREATE TABLE t AS SELECT 7 AS x")
    monkeypatch.setattr(cli, "_default_query_connect", lambda: con)
    monkeypatch.delenv("REGISTRY_TABLE", raising=False)
    monkeypatch.delenv("DISPATCHER_FUNCTION", raising=False)
    monkeypatch.setattr(sys, "argv", ["swimtrends", "query", "--sql", "SELECT x FROM t"])
    cli.main()
    assert "7" in capsys.readouterr().out
