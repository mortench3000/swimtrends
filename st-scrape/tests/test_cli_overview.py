"""CLI wiring for the curated-zone overview commands (meets/categories/summary).

Uses an injected in-memory DuckDB (same pattern as test_cli_query) so it
exercises run() + formatting without S3.
"""
import sys

import duckdb

from ingestion import cli
from tests.analytics_fixtures import build_curated

MEETS = [
    dict(meet_id="m1", meet_name="DM Langbane 2024", course="LCM", season=2024,
         meet_date="11-07-2024", category=["DM-L"]),
    dict(meet_id="m2", meet_name="DM Kortbane 2020", course="SCM", season=2021,
         meet_date="14-12-2020", category=["DM-K"]),
]
OBT = [
    dict(result_id="r1", meet_id="m1", race_id=10, rank=1, swimmer_id="s1",
         name="s1", season=2024, relay_count=1, distance=100, stroke="Fri",
         gender="M", course="LCM", **{"class": "open"}),
    dict(result_id="r2", meet_id="m2", race_id=20, rank=1, swimmer_id="s2",
         name="s2", season=2021, relay_count=1, distance=100, stroke="Fri",
         gender="M", course="SCM", **{"class": "open"}),
]


def _con():
    con = duckdb.connect()
    build_curated(con, obt=OBT, meets=MEETS)
    return con


def test_meets_command_prints_table(capsys):
    rc = cli.run(["meets"], registry=None, invoke=None, connect=_con)
    out = capsys.readouterr().out
    assert rc == 0
    assert "m1" in out and "m2" in out
    assert "races" in out and "results" in out


def test_meets_default_desc_and_asc_flag(capsys):
    cli.run(["meets"], registry=None, invoke=None, connect=_con)
    desc = capsys.readouterr().out
    assert desc.index("m1") < desc.index("m2")            # 2024 before 2021 (newest first)
    cli.run(["meets", "--asc"], registry=None, invoke=None, connect=_con)
    asc = capsys.readouterr().out
    assert asc.index("m2") < asc.index("m1")              # 2021 before 2024 (oldest first)


def test_meets_category_filter(capsys):
    cli.run(["meets", "--category", "DM-K"], registry=None, invoke=None, connect=_con)
    out = capsys.readouterr().out
    assert "m2" in out and "m1" not in out


def test_categories_command(capsys):
    cli.run(["categories"], registry=None, invoke=None, connect=_con)
    out = capsys.readouterr().out
    assert "DM-K" in out and "DM-L" in out


def test_summary_command(capsys):
    cli.run(["summary"], registry=None, invoke=None, connect=_con)
    out = capsys.readouterr().out
    assert "meets:" in out and "2" in out
    assert "2021-2024" in out


def test_overview_commands_are_readonly():
    # main() must short-circuit these before requiring ingestion env.
    assert {"meets", "categories", "summary"} <= cli.READONLY_COMMANDS


def test_main_meets_does_not_require_ingestion_env(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_default_query_connect", _con)
    monkeypatch.delenv("REGISTRY_TABLE", raising=False)
    monkeypatch.delenv("DISPATCHER_FUNCTION", raising=False)
    monkeypatch.setattr(sys, "argv", ["swimtrends", "meets"])
    cli.main()
    assert "m1" in capsys.readouterr().out
