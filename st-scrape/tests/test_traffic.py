"""Parsing + human/bot split over CloudFront standard (legacy) access logs.

Writes a tiny pair of gzipped log files to tmp_path and reads them with a plain
in-memory DuckDB — no S3, no httpfs, no credentials.
"""
import gzip
from datetime import date

import duckdb
import pytest

from analytics import traffic

FIELDS = (
    "date time x-edge-location sc-bytes c-ip cs-method cs(Host) cs-uri-stem "
    "sc-status cs(Referer) cs(User-Agent) cs-uri-query cs(Cookie) "
    "x-edge-result-type x-edge-request-id x-host-header cs-protocol cs-bytes "
    "time-taken x-forwarded-for ssl-protocol ssl-cipher "
    "x-edge-response-result-type cs-protocol-version fle-status "
    "fle-encrypted-fields c-port time-to-first-byte "
    "x-edge-detailed-result-type sc-content-type sc-content-len "
    "sc-range-start sc-range-end"
)
HEADER = f"#Version: 1.0\n#Fields: {FIELDS}\n"
# CloudFront percent-encodes these fields in the log.
GOOGLEBOT = ("Mozilla/5.0%20(compatible;%20Googlebot/2.1;"
             "%20+http://www.google.com/bot.html)")
CHROME = ("Mozilla/5.0%20(Macintosh;%20Intel%20Mac%20OS%20X%2010_15_7)"
          "%20Chrome/120.0")


def _row(day, uri, ua, *, status="200", referer="-", method="GET"):
    cells = [day, "10:00:00", "CPH50-C1", "1234", "192.0.2.1", method,
             "d1.cloudfront.net", uri, status, referer, ua, "-", "-", "Hit",
             "rid", "swimtrends.dk", "https", "123", "0.001", "-", "TLSv1.3",
             "TLS_AES", "Hit", "HTTP/2.0", "-", "-", "443", "0.001", "Hit",
             "text/html", "1234", "-", "-"]
    return "\t".join(cells)


def _write(tmp_path, name, rows):
    p = tmp_path / name
    with gzip.open(p, "wt") as fh:
        fh.write(HEADER)
        fh.write("\n".join(rows) + "\n")
    return p


@pytest.fixture
def logs(tmp_path):
    """Two files, so the per-file `skip=2` preamble handling is exercised."""
    _write(tmp_path, "f1.gz", [
        _row("2026-08-01", "/DM-L/12486/index.html", CHROME,
             referer="https://www.google.com/search?q=dm"),
        _row("2026-08-01", "/assets/app-abc.js", CHROME),
        _row("2026-08-01", "/DM-L/12486", GOOGLEBOT),
    ])
    _write(tmp_path, "f2.gz", [
        _row("2026-07-31", "/", GOOGLEBOT),
        _row("2026-07-31", "/data/meets.json", CHROME),
        _row("2026-07-31", "/DM-K", CHROME, status="304",
             referer="https://www.facebook.com/groups/svom"),
    ])
    return str(tmp_path / "*.gz")


@pytest.fixture
def con():
    return duckdb.connect()


def test_splits_human_and_bot_per_day(con, logs):
    rows = traffic.report(con, logs, since=date(2026, 7, 1))["by_day"]
    assert rows == [
        {"date": date(2026, 7, 31), "human": 1, "bot": 1},
        {"date": date(2026, 8, 1), "human": 1, "bot": 1},
    ]


def test_excludes_assets_and_data_files(con, logs):
    paths = {r["path"] for r in traffic.report(
        con, logs, since=date(2026, 7, 1))["by_path"]}
    assert "/assets/app-abc.js" not in paths
    assert "/data/meets.json" not in paths
    assert paths == {"/DM-L/12486", "/", "/DM-K"}


def test_index_html_folds_into_the_directory_path(con, logs):
    by_path = {r["path"]: r for r in traffic.report(
        con, logs, since=date(2026, 7, 1))["by_path"]}
    # /DM-L/12486/index.html (human) and /DM-L/12486 (bot) are one page.
    assert by_path["/DM-L/12486"] == {
        "path": "/DM-L/12486", "human": 1, "bot": 1}


def test_referrers_group_by_host_with_a_direct_bucket(con, logs):
    rows = traffic.report(con, logs, since=date(2026, 7, 1))["by_referrer"]
    assert {r["referrer"] for r in rows} == {
        "(direct)", "google.com", "facebook.com"}
    direct = next(r for r in rows if r["referrer"] == "(direct)")
    assert direct == {"referrer": "(direct)", "human": 0, "bot": 2}


def test_since_excludes_older_days(con, logs):
    rows = traffic.report(con, logs, since=date(2026, 8, 1))["by_day"]
    assert rows == [{"date": date(2026, 8, 1), "human": 1, "bot": 1}]


def test_limit_caps_the_path_table(con, logs):
    rows = traffic.report(con, logs, since=date(2026, 7, 1), limit=1)["by_path"]
    assert len(rows) == 1


def test_default_path_points_at_the_cf_prefix():
    assert traffic.default_path("swimtrends-web-logs") == (
        "s3://swimtrends-web-logs/cf/*.gz")
