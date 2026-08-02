"""CLI wiring for `swimtrends traffic`.

Injects a plain in-memory DuckDB and points --path at fixture files, so run()
and the formatting are exercised without S3 (same pattern as
test_cli_overview.py).
"""
import gzip

import duckdb
import pytest

from ingestion import cli
from tests.test_traffic import CHROME, GOOGLEBOT, HEADER, _row


@pytest.fixture
def logs(tmp_path):
    p = tmp_path / "f1.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(HEADER)
        fh.write("\n".join([
            _row("2026-08-01", "/DM-L/12486", CHROME,
                 referer="https://www.google.com/"),
            _row("2026-08-01", "/DM-L/12486", GOOGLEBOT),
        ]) + "\n")
    return str(tmp_path / "*.gz")


def test_traffic_prints_the_three_tables(capsys, logs):
    rc = cli.run(["traffic", "--days", "36500", "--path", logs],
                 registry=None, invoke=None, connect=duckdb.connect)
    out = capsys.readouterr().out
    assert rc == 0
    assert "human" in out and "bot" in out
    assert "/DM-L/12486" in out
    assert "google.com" in out
    assert "2026-08-01" in out


def test_traffic_reports_no_traffic_when_nothing_qualifies(capsys, tmp_path):
    # Asset-only log: every row is filtered out, so the window is empty
    # regardless of what today's date is.
    p = tmp_path / "assets.gz"
    with gzip.open(p, "wt") as fh:
        fh.write(HEADER)
        fh.write(_row("2026-08-01", "/assets/app-abc.js", CHROME) + "\n")
    rc = cli.run(["traffic", "--days", "36500", "--path", str(p)],
                 registry=None, invoke=None, connect=duckdb.connect)
    assert rc == 0
    assert "No traffic" in capsys.readouterr().out


def test_traffic_is_read_only():
    # Must not require REGISTRY_TABLE / DISPATCHER_FUNCTION.
    assert "traffic" in cli.READONLY_COMMANDS
