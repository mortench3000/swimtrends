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
