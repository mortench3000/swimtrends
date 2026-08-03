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


def test_report_is_empty_when_no_files_match(con, tmp_path):
    # The state of the log prefix for the first hour after the stack is
    # deployed: CloudFront has not delivered anything yet.
    empty = traffic.report(
        con, str(tmp_path / "nothing" / "*.gz"), since=date(2026, 7, 1))
    assert empty == {"by_day": [], "by_path": [], "by_referrer": []}


def test_report_still_raises_on_a_real_io_error(con):
    # Not a missing glob — a bucket we cannot reach must not be reported as
    # "no traffic".
    with pytest.raises(duckdb.Error):
        traffic.report(con, "s3://swimtrends-web-logs/cf/*.gz",
                       since=date(2026, 7, 1))


SCANNER = ("Mozilla/5.0%20(Windows%20NT%2010.0;%20Win64;%20x64)"
           "%20AppleWebKit/537.36%20(KHTML,%20like%20Gecko)%20Chrome/91.0")


@pytest.fixture
def probes(tmp_path):
    """Real scanner paths seen in the live logs on 2026-08-02/03. All end in a
    slash or a lowercase segment, so the old extension-only filter kept them."""
    _write(tmp_path, "probe.gz", [
        _row("2026-08-01", "/.tmb/", SCANNER),
        _row("2026-08-01", "/.well-known/acme-challenge/", SCANNER),
        _row("2026-08-01", "/admin/fckeditor/editor/filemanager/", SCANNER),
        _row("2026-08-01", "/admin/uploads/images/", SCANNER),
        _row("2026-08-01", "/administrator/", SCANNER),
        _row("2026-08-01", "/wp-content/plugins/", SCANNER),
        # …and the real routes, which must survive.
        _row("2026-08-01", "/", CHROME),
        _row("2026-08-01", "/DM-L", CHROME),
        _row("2026-08-01", "/DM-L/7833", CHROME),
        _row("2026-08-01", "/DM-L/7833/F-400-IM-LCM", CHROME),
        _row("2026-08-01", "/DO/10969/M-1500-Fri-LCM", CHROME),
        _row("2026-08-01", "/DMJ-K/10339/index.html", CHROME),
    ])
    return str(tmp_path / "probe.gz")


def test_scanner_probe_paths_are_excluded(con, probes):
    paths = {r["path"] for r in traffic.report(
        con, probes, since=date(2026, 7, 1))["by_path"]}
    assert paths == {"/", "/DM-L", "/DM-L/7833", "/DM-L/7833/F-400-IM-LCM",
                     "/DO/10969/M-1500-Fri-LCM", "/DMJ-K/10339"}


def test_probe_traffic_does_not_inflate_the_human_count(con, probes):
    day = traffic.report(con, probes, since=date(2026, 7, 1))["by_day"]
    # 6 real routes, not 12: the six probes are gone.
    assert day == [{"date": date(2026, 8, 1), "human": 6, "bot": 0}]


@pytest.mark.parametrize("agent", [
    "Mozilla/5.0%20(compatible;%20Dataprovider.com)",
    "Mozilla/5.0%20(compatible;%20CMS-Checker/1.0;%20+https://example.com)",
    "Mozilla/5.0%20(compatible;%20InternetMeasurement/1.0)",
    # Google's non-search crawler: no 'bot' token anywhere in the UA.
    "Mozilla/5.0%20(Linux;%20Android%206.0.1)%20Chrome/150.0"
    "%20Mobile%20Safari/537.36%20(compatible;%20GoogleOther)",
])
def test_named_commercial_crawlers_count_as_bots(con, tmp_path, agent):
    p = _write(tmp_path, "c.gz", [_row("2026-08-01", "/DM-L/7833", agent)])
    day = traffic.report(con, str(p), since=date(2026, 7, 1))["by_day"]
    assert day == [{"date": date(2026, 8, 1), "human": 0, "bot": 1}]
