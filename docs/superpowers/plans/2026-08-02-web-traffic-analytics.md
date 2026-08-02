# Web Traffic Analytics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn on CloudFront access logging for swimtrends.dk and add a read-only `swimtrends traffic` CLI command that reports hits, paths and referrers split human vs bot.

**Architecture:** CloudFront standard logging (legacy) delivers gzipped TSV to a new, explicitly-named S3 bucket `swimtrends-web-logs` under the `cf/` prefix, in the existing eu-west-1 web stack. A new `analytics/traffic.py` module runs three grouped queries over that glob with DuckDB; `ingestion/cli.py` gains a `traffic` subcommand that formats them with the existing `render_table`. No client-side script, no dashboard, no new dependency.

**Tech Stack:** Python 3.12, aws-cdk-lib (Python), DuckDB 1.5.4 + httpfs, pytest.

**Spec:** [`docs/superpowers/specs/2026-08-02-web-traffic-analytics-design.md`](../specs/2026-08-02-web-traffic-analytics-design.md)

## Global Constraints

- Branch is `web-traffic-analytics`, already created off `master`. Do not commit to `master`.
- App venv: `st-scrape/.venv`. CDK venv: `swimtrends-app/.venv`. They are separate.
- Do not add any new dependency. DuckDB, argparse and gzip are already available.
- Do not hardcode the AWS account id in any **new** file. (`swimtrends-app/tests/unit/test_web_stack.py` already contains `ACC`; reuse the existing constant, do not introduce another.)
- Log bucket name is exactly `swimtrends-web-logs`. Log prefix is exactly `cf/`.
- Retention is exactly 90 days.
- Bot-detection regex is exactly `(?i)bot|crawl|spider|slurp`.
- Deliberate simplifications get a `ponytail:` comment naming the ceiling.
- TDD: write the failing test, run it, watch it fail, then implement.

## File Structure

| File | Responsibility |
| --- | --- |
| `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` (modify) | Add `LogsBucket`; enable logging on the existing `Distribution`; output the bucket name. |
| `swimtrends-app/tests/unit/test_web_stack.py` (modify) | Assert the bucket's ownership/lifecycle and the distribution's logging block. |
| `st-scrape/analytics/traffic.py` (create) | Parse the CloudFront log glob and produce the three grouped reports. Pure SQL over an injected connection — knows nothing about argparse or S3 credentials. |
| `st-scrape/tests/test_traffic.py` (create) | Fixture `.gz` logs in `tmp_path` + plain in-memory DuckDB. No S3. |
| `st-scrape/ingestion/cli.py` (modify) | `traffic` subcommand, argument parsing, table formatting. |
| `st-scrape/tests/test_cli_traffic.py` (create) | CLI wiring via `cli.run(..., connect=…)`, same pattern as `test_cli_overview.py`. |
| `docs/analytics.md` (modify) | Operator documentation for the new command. |

---

### Task 1: CloudFront access logging (CDK)

**Files:**
- Modify: `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` (bucket after `SiteBucket` ~line 37; `Distribution` at lines 58-73; `CfnOutput`s at ~line 166)
- Test: `swimtrends-app/tests/unit/test_web_stack.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: an S3 bucket literally named `swimtrends-web-logs` receiving objects under `cf/`. Task 3 hardcodes that name as the CLI default.

All commands in this task run from `swimtrends-app/`.

- [ ] **Step 1: Write the failing tests**

Append to `swimtrends-app/tests/unit/test_web_stack.py`:

```python
def test_logs_bucket_has_acls_enabled_and_90_day_expiry():
    # Legacy CloudFront logging delivers via an ACL grant; buckets created
    # after April 2023 default to BUCKET_OWNER_ENFORCED, which disables ACLs
    # and makes delivery fail silently. BucketOwnerPreferred is load-bearing.
    _template().has_resource_properties("AWS::S3::Bucket", {
        "BucketName": "swimtrends-web-logs",
        "OwnershipControls": {
            "Rules": [{"ObjectOwnership": "BucketOwnerPreferred"}]
        },
        "LifecycleConfiguration": {
            "Rules": [assertions.Match.object_like({
                "ExpirationInDays": 90, "Status": "Enabled",
            })]
        },
    })


def test_distribution_logs_to_the_logs_bucket():
    _template().has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": assertions.Match.object_like({
            "Logging": assertions.Match.object_like({
                "Prefix": "cf/", "IncludeCookies": False,
            })
        })
    })
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/unit/test_web_stack.py -k "logs_bucket or logs_to_the" -v
```

Expected: both FAIL. The first reports no `AWS::S3::Bucket` matching `BucketName: swimtrends-web-logs`; the second reports no distribution with a `Logging` block.

- [ ] **Step 3: Add the logs bucket**

In `swimtrends_app/swimtrends_web_stack.py`, immediately after the `bucket = s3.Bucket(self, "SiteBucket", …)` block:

```python
        # CloudFront access logs (standard logging, legacy). Legacy rather than
        # v2 because a v2 delivery source must be created in us-east-1 even when
        # the bucket is in eu-west-1 — a second cross-region stack, which is not
        # worth Parquet output for a site with near-zero traffic.
        # BUCKET_OWNER_PREFERRED is load-bearing: legacy delivery uses an ACL
        # grant, and the post-April-2023 default (BUCKET_OWNER_ENFORCED)
        # disables ACLs, so CloudFront would silently deliver nothing.
        # Explicitly named so `swimtrends traffic` can default to it instead of
        # resolving a generated name from stack outputs.
        logs_bucket = s3.Bucket(
            self, "LogsBucket",
            bucket_name="swimtrends-web-logs",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            # Access logs carry c-ip, which is personal data under GDPR. The
            # expiry is the mitigation; nothing downstream needs older logs.
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))],
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
```

- [ ] **Step 4: Enable logging on the distribution**

In the same file, inside the existing `cloudfront.Distribution(...)` call, add these three arguments after `error_responses=spa_fallback,`:

```python
            enable_logging=True,
            log_bucket=logs_bucket,
            log_file_prefix="cf/",
            log_includes_cookies=False,
```

- [ ] **Step 5: Output the bucket name**

Next to the existing `CfnOutput`s at the bottom of the stack:

```python
        CfnOutput(self, "LogsBucketName", value=logs_bucket.bucket_name)
```

- [ ] **Step 6: Run the new tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/unit/test_web_stack.py -k "logs_bucket or logs_to_the" -v
```

Expected: 2 passed.

- [ ] **Step 7: Run the whole CDK suite for regressions**

```bash
.venv/bin/python -m pytest tests/unit
```

Expected: all pass (44 before this change, 46 after). If a pre-existing test asserted an exact `AWS::S3::Bucket` **count**, the second bucket will break it — update that count rather than removing the assertion.

- [ ] **Step 8: Commit**

```bash
git add swimtrends_app/swimtrends_web_stack.py tests/unit/test_web_stack.py
git commit -m "feat(infra): log CloudFront access logs to swimtrends-web-logs"
```

---

### Task 2: The traffic queries

**Files:**
- Create: `st-scrape/analytics/traffic.py`
- Test: `st-scrape/tests/test_traffic.py`

**Interfaces:**
- Consumes: the `cf/` layout from Task 1 (only as a default path string).
- Produces, relied on by Task 3:
  - `LOG_COLUMNS: list[str]` — the 33 CloudFront field names, in order.
  - `default_path(bucket: str) -> str` — returns `f"s3://{bucket}/cf/*.gz"`.
  - `report(con, path: str, *, since: datetime.date, limit: int = 15) -> dict` —
    returns `{"by_day": [...], "by_path": [...], "by_referrer": [...]}`.
    `by_day` rows are `{"date": datetime.date, "human": int, "bot": int}`;
    `by_path` rows are `{"path": str, "human": int, "bot": int}`;
    `by_referrer` rows are `{"referrer": str, "human": int, "bot": int}`.
    `by_day` is ordered by date ascending; the other two by total hits
    descending, then by the group key, capped at `limit`.

All commands in this task run from `st-scrape/`.

- [ ] **Step 1: Write the failing tests**

Create `st-scrape/tests/test_traffic.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_traffic.py -v
```

Expected: collection error — `ImportError: cannot import name 'traffic' from 'analytics'`.

- [ ] **Step 3: Write the implementation**

Create `st-scrape/analytics/traffic.py`:

```python
"""Traffic over the CloudFront standard (legacy) access logs.

CloudFront delivers one gzipped, tab-separated file per batch under
s3://<bucket>/cf/. Each file starts with a two-line `#Version` / `#Fields:`
preamble that DuckDB's header detection cannot use, hence `skip=2` (applied
per file) and the explicit LOG_COLUMNS list below, in CloudFront's documented
field order.

Every function takes a live DuckDB connection and a glob, so tests point it at
local files and the CLI points it at S3.
"""

LOG_COLUMNS = [
    "date", "time", "x_edge_location", "sc_bytes", "c_ip", "cs_method",
    "cs_host", "cs_uri_stem", "sc_status", "cs_referer", "cs_user_agent",
    "cs_uri_query", "cs_cookie", "x_edge_result_type", "x_edge_request_id",
    "x_host_header", "cs_protocol", "cs_bytes", "time_taken",
    "x_forwarded_for", "ssl_protocol", "ssl_cipher",
    "x_edge_response_result_type", "cs_protocol_version", "fle_status",
    "fle_encrypted_fields", "c_port", "time_to_first_byte",
    "x_edge_detailed_result_type", "sc_content_type", "sc_content_len",
    "sc_range_start", "sc_range_end",
]

# ponytail: substring match on the user agent. Well-behaved crawlers identify
# themselves and land in the bot column; anything spoofing Chrome counts as
# human. Swap in a maintained UA list only if the split visibly misleads.
BOT_RE = "(?i)bot|crawl|spider|slurp"


def default_path(bucket):
    """The glob the CLI reads by default; matches log_file_prefix='cf/'."""
    return f"s3://{bucket}/cf/*.gz"


def _columns_struct():
    """DuckDB `columns=` struct — all VARCHAR; we cast the two we care about."""
    return "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in LOG_COLUMNS) + "}"


def _pages_cte():
    r"""CTE narrowing the raw log to one row per *page* view.

    - sc_status 200/304 and GET: skip redirects, errors and preflights.
    - last path segment without a dot (or ending .html): keeps /DM-L/12486 and
      / while dropping /assets/*.js and /data/*.json, which would otherwise
      outnumber the pages several to one.
    - /index.html is folded away: cloudfront/viewer_request.js appends it to
      extensionless paths, so the same page can appear both ways.
    - referrer reduced to its host, minus a www. prefix; missing/'-' becomes
      '(direct)'.
    """
    return f"""
    WITH raw AS (
        SELECT * FROM read_csv(?, delim='\t', header=false, skip=2,
                               columns={_columns_struct()})
    ), pages AS (
        SELECT
            CAST(date AS DATE) AS day,
            coalesce(nullif(
                regexp_replace(cs_uri_stem, '/?index\\.html$', ''), ''), '/')
                AS path,
            coalesce(nullif(regexp_extract(
                url_decode(cs_referer), '^https?://(?:www\\.)?([^/]+)', 1),
                ''), '(direct)') AS referrer,
            regexp_matches(url_decode(cs_user_agent), '{BOT_RE}') AS is_bot
        FROM raw
        WHERE sc_status IN ('200', '304')
          AND cs_method = 'GET'
          AND (regexp_matches(cs_uri_stem, '/[^/.]*$')
               OR cs_uri_stem LIKE '%.html')
          AND CAST(date AS DATE) >= ?
    )
    """


def _grouped(con, path, since, group, order, limit):
    sql = _pages_cte() + f"""
        SELECT {group} AS key,
               count(*) FILTER (WHERE NOT is_bot) AS human,
               count(*) FILTER (WHERE is_bot)     AS bot
        FROM pages
        GROUP BY key
        ORDER BY {order}
    """
    params = [path, since]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return con.execute(sql, params).fetchall()


def report(con, path, *, since, limit=15):
    """Hits per day, top paths and top referrers, each split human vs bot.

    `since` is an inclusive date floor. `limit` caps the path and referrer
    tables only — the daily series is always complete.
    """
    by_day = [
        {"date": d, "human": h, "bot": b}
        for d, h, b in _grouped(con, path, since, "day", "key", None)
    ]
    # Total descending, then the key, so ties are stable run to run.
    top = "human + bot DESC, key"
    by_path = [
        {"path": k, "human": h, "bot": b}
        for k, h, b in _grouped(con, path, since, "path", top, limit)
    ]
    by_referrer = [
        {"referrer": k, "human": h, "bot": b}
        for k, h, b in _grouped(con, path, since, "referrer", top, limit)
    ]
    return {"by_day": by_day, "by_path": by_path, "by_referrer": by_referrer}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_traffic.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add analytics/traffic.py tests/test_traffic.py
git commit -m "feat(analytics): query CloudFront access logs for page traffic"
```

---

### Task 3: The `traffic` CLI command and docs

**Files:**
- Modify: `st-scrape/ingestion/cli.py` (module docstring ~lines 12-16; `build_parser` ~line 74; `READONLY_COMMANDS` ~line 148; `run` — add a branch next to the `meets`/`categories`/`summary` branch)
- Create: `st-scrape/tests/test_cli_traffic.py`
- Modify: `docs/analytics.md`

**Interfaces:**
- Consumes: `analytics.traffic.report`, `analytics.traffic.default_path` (Task 2 signatures), `analytics.overview.render_table(headers, rows)`, and the existing `run(argv, *, registry, invoke, curate=None, overrides=None, connect=None)` injection point.
- Produces: `swimtrends traffic [--days N] [--bucket NAME] [--path GLOB] [--limit N]`.

All commands in this task run from `st-scrape/`.

- [ ] **Step 1: Write the failing tests**

Create `st-scrape/tests/test_cli_traffic.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_cli_traffic.py -v
```

Expected: FAIL — argparse exits with `invalid choice: 'traffic'`, and `test_traffic_is_read_only` fails on the missing set member.

- [ ] **Step 3: Add the subcommand to the parser**

In `ingestion/cli.py`, in `build_parser()`, after the `summary` parser line:

```python
    tra = sub.add_parser(
        "traffic",
        help="Page hits, paths and referrers from the CloudFront access logs.")
    tra.add_argument("--days", type=int, default=14,
                     help="How far back to look. Default 14; logs expire at 90.")
    tra.add_argument("--bucket", default="swimtrends-web-logs",
                     help="Access-log bucket. Default swimtrends-web-logs.")
    tra.add_argument("--path", default=None,
                     help="Read this glob instead of the bucket's cf/ prefix "
                          "(a local path works, which is how the tests run).")
    tra.add_argument("--limit", type=int, default=15,
                     help="Rows in the path and referrer tables. Default 15.")
```

- [ ] **Step 4: Register it as read-only**

Change the `READONLY_COMMANDS` line to:

```python
READONLY_COMMANDS = frozenset({"query", "meets", "categories", "summary", "traffic"})
```

- [ ] **Step 5: Add the run() branch**

In `run()`, immediately before the `if args.command in ("meets", "categories", "summary"):` branch:

```python
    if args.command == "traffic":
        from datetime import date, timedelta

        from analytics import overview, traffic as traffic_mod

        con = (connect or _default_query_connect)()
        path = args.path or traffic_mod.default_path(args.bucket)
        since = date.today() - timedelta(days=args.days)
        rep = traffic_mod.report(con, path, since=since, limit=args.limit)

        if not rep["by_day"]:
            # Logs are delivered several times an hour and may lag up to 24h,
            # so an empty recent window is normal rather than an error.
            print(f"No traffic since {since}. "
                  "Note CloudFront can take up to 24h to deliver logs.")
            return 0

        print(f"Page requests since {since} (human / bot)\n")
        print(overview.render_table(
            ["date", "human", "bot"],
            [[r["date"], r["human"], r["bot"]] for r in rep["by_day"]]))
        print("\ntop paths")
        print(overview.render_table(
            ["path", "human", "bot"],
            [[r["path"], r["human"], r["bot"]] for r in rep["by_path"]]))
        print("\ntop referrers")
        print(overview.render_table(
            ["referrer", "human", "bot"],
            [[r["referrer"], r["human"], r["bot"]] for r in rep["by_referrer"]]))
        return 0
```

- [ ] **Step 6: Update the module docstring**

In `ingestion/cli.py`, extend the read-only block of the docstring:

```
  swimtrends summary                       # top-level totals
  swimtrends traffic [--days 14]           # site page hits, human vs bot
```

- [ ] **Step 7: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_cli_traffic.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Run the full app suite for regressions**

```bash
.venv/bin/python -m pytest -q
```

Expected: all pass (276 before this branch, 286 after Tasks 2 and 3).

- [ ] **Step 9: Document it**

Add to `docs/analytics.md`, as a new section at the end:

```markdown
## Site traffic

CloudFront writes an access log for every request to swimtrends.dk into
`s3://swimtrends-web-logs/cf/` (gzipped TSV, expired after 90 days). To read it:

```bash
cd st-scrape
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic
```

Three tables — hits per day, top paths, top referrers — each split human vs
bot. Flags: `--days N` (default 14), `--limit N` (default 15, path/referrer
tables only), `--bucket`, and `--path` to read some other glob.

Notes for whoever reads the numbers:

- **Bot is a guess.** It is a user-agent substring match (`bot|crawl|spider|
  slurp`). Honest crawlers say so; a scraper posing as Chrome counts as human.
- **The bot column is the point right after an indexing change** — it is how
  you confirm Googlebot is actually fetching the prerendered meet shells.
  Search Console cannot tell you that, because uncrawled pages never appear
  there.
- **Logs lag.** CloudFront delivers several times an hour but may take up to
  24 hours. Judge by yesterday, not the last five minutes.
- **Your own visits count.** There is no cookie and no way to exclude yourself.
- **Edge cache hits are logged** (`x-edge-result-type=Hit`), so the counts are
  complete even though most requests never reach S3.
- **Search queries are not here.** Google strips them from the referrer; they
  live only in Google Search Console.
```

- [ ] **Step 10: Commit**

```bash
git add ingestion/cli.py tests/test_cli_traffic.py ../docs/analytics.md
git commit -m "feat(cli): add read-only 'traffic' command over the access logs"
```

---

### Task 4: Deploy and verify (operator-gated)

**Files:** none — this task changes no code.

**Interfaces:** consumes the deployed stack from Task 1.

> **STOP.** This task deploys infrastructure. Per the repo guardrails, CDK
> stack deploys need explicit confirmation from the user. Do not run Step 2
> without it. Tasks 1-3 must be merged first.

- [ ] **Step 1: Open the PR and wait for CI**

From the repo root:

```bash
git push -u origin web-traffic-analytics
gh pr create --base master \
  --title "feat: web traffic analytics from CloudFront access logs" \
  --body "Enables CloudFront standard logging (legacy) to swimtrends-web-logs and adds a read-only \`swimtrends traffic\` command. Spec: docs/superpowers/specs/2026-08-02-web-traffic-analytics-design.md"
gh pr checks --watch
gh pr merge --squash --delete-branch
```

- [ ] **Step 2: Deploy the web stack (needs user confirmation)**

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
npx aws-cdk@2.1133.0 deploy SwimtrendsWebStack \
  --app ".venv/bin/python3 app.py" \
  -c alert_email=<address> \
  --require-approval never
```

`-c alert_email` is mandatory — omitting it drops the existing SNS email
subscription and the cost-budget notification silently stops.

If the deploy fails with `BucketAlreadyExists`, the name `swimtrends-web-logs`
is taken in another AWS account (S3 bucket names are globally unique). Pick
another name and change it in both `swimtrends_web_stack.py` and the CLI
default in `ingestion/cli.py`.

- [ ] **Step 3: Confirm logs are arriving**

Wait at least an hour after the deploy, load a page on swimtrends.dk, then:

```bash
aws s3 ls s3://swimtrends-web-logs/cf/ --profile swimtrends | head
```

Expected: at least one `.gz` object. **If the prefix is still empty after 24
hours, the ACL setting is the first suspect** — check that the bucket's Object
Ownership really is `BucketOwnerPreferred` in the console; legacy logging fails
silently when ACLs are disabled.

- [ ] **Step 4: Confirm the command reads them**

```bash
cd st-scrape
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic --days 7
```

Expected: three tables. Sanity-check one open question from the spec while you
are here — **whether `cs-uri-stem` logs the URI before or after
`cloudfront/viewer_request.js` appends `/index.html`.** Either form folds to
the same path (Task 2 strips the suffix), so nothing breaks; just confirm you
do not see both `/DM-L/12486` and `/DM-L/12486/index.html` as separate rows.

---

## Notes on spec verification items

The spec listed three assumptions to confirm. Two were resolved while writing
this plan, by prototyping against fixture logs on DuckDB 1.5.4:

1. **`url_decode` exists** — confirmed present, used for the referrer and
   user-agent columns.
2. **`skip=2` applies per file** — confirmed: two 3-row files glob to 6 rows.

The third — whether `cs-uri-stem` is logged pre- or post-rewrite — can only be
answered against real logs, so it is Step 4 of Task 4. The implementation is
correct either way; the check is only to confirm paths are not double-counted.
