# Site traffic — a walkthrough

How to find out whether anyone is visiting swimtrends.dk, and how to read the
numbers without fooling yourself.

Every request to the site is logged by CloudFront into
`s3://swimtrends-web-logs/cf/` as gzipped, tab-separated files. The
`swimtrends traffic` command reads them with DuckDB. There is no dashboard, no
tracking script on the site, and no cookie — which also means no consent banner.

Related: [`analytics.md`](analytics.md) for the curated swim data (a different
dataset entirely), and the design notes in
[`superpowers/specs/2026-08-02-web-traffic-analytics-design.md`](superpowers/specs/2026-08-02-web-traffic-analytics-design.md).

## Before you start

You need AWS credentials for the `swimtrends` profile. Normally that is all:

```bash
cd st-scrape
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic
```

`traffic` is a read-only command — it needs S3 credentials only, not
`REGISTRY_TABLE` or the rest of the ingestion environment.

## The first run

```
Page requests since 2026-07-26 (human / bot)

date        human  bot
2026-08-02  2      1

top paths
path                    human  bot
/                       1      0
/DM-L/12486             1      0
/DO/10969/F-400-IM-LCM  0      1

top referrers
referrer  human  bot
(direct)  2      1
```

Three tables, each split human vs bot:

- **hits per day** — the whole window, never truncated.
- **top paths** — which pages, capped at `--limit` (default 15).
- **top referrers** — reduced to the host, `www.` stripped. `(direct)` means no
  referrer: typed URLs, bookmarks, most crawlers, and anything from an app.

Flags: `--days N` (default 14), `--limit N` (default 15, affects the path and
referrer tables only), `--bucket NAME`, and `--path GLOB` to read some other
location — a local path works, which is how the tests run.

## Reading it honestly

**Only page requests are counted.** The filter is `sc-status` 200 or 304,
method `GET`, and a URL whose last segment has no file extension or ends in
`.html`. Without it, `/assets/*.js` and `/data/*.json` outnumber real pages by
roughly fifty to one and the tables become useless.

**`/index.html` is folded away.** `/DM-L/12486` and `/DM-L/12486/index.html`
are one page. (In practice CloudFront logs the URL *as requested*, before
`viewer_request.js` appends the suffix, so this rarely fires — it is insurance.)

**"bot" is a substring match** on the user agent — `bot`, `crawl`, `spider`,
`slurp`. Honest crawlers identify themselves. A scanner posing as Chrome counts
as human, and `curl` counts as human. Treat the split as a strong hint, not a
measurement.

**Your own visits count.** There is no cookie and no way to exclude yourself.
On a site this quiet, assume a meaningful share of the human column is you.

## Recipes

### Is anyone actually visiting?

```bash
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic --days 30
```

Read the **human** column of the daily table, and subtract your own visits. A
couple a day is you. A step change is not.

### Is Google crawling the new pages?

This is the question the bot column exists for, and the one Search Console
*cannot* answer — uncrawled pages simply never appear there.

```bash
AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli traffic --days 30 --limit 50
```

Look for the prerendered shells (`/`, the five category pages, the 41 meet
pages) in the bot column. If meet pages never appear, prerendering or the
CloudFront viewer function is not doing its job.

### What did Googlebot actually fetch?

Beyond the three tables, query the log directly. `analytics.traffic.LOG_COLUMNS`
holds CloudFront's 33 field names in order, so you do not have to retype them:

```python
import duckdb
from analytics import loader, traffic

con = loader.bind_s3(duckdb.connect())
cols = "{" + ", ".join(f"'{c}': 'VARCHAR'" for c in traffic.LOG_COLUMNS) + "}"
LOGS = (f"read_csv('s3://swimtrends-web-logs/cf/*.gz', delim='\t', "
        f"header=false, skip=2, columns={cols})")

print(con.sql(f"""
    SELECT cs_uri_stem, sc_status, x_edge_result_type
    FROM {LOGS}
    WHERE url_decode(cs_user_agent) ILIKE '%googlebot%'
    ORDER BY cs_uri_stem
"""))
```

Run it with `AWS_PROFILE=swimtrends .venv/bin/python`. The `skip=2` is
CloudFront's `#Version` / `#Fields:` preamble, which DuckDB's header detection
cannot use; it is applied per file, so the glob is safe. Fields are
percent-encoded in the log — wrap anything you want to read in `url_decode()`.

### Which user agents are hitting the site?

```python
print(con.sql(f"""
    SELECT url_decode(cs_user_agent) AS agent, count(*) AS hits
    FROM {LOGS} GROUP BY 1 ORDER BY hits DESC LIMIT 10
"""))
```

## Things that look wrong but aren't

**A flood of `/data/**/*.json` from a `node` user agent.** That is CI. The
`prerender.mjs` step fetches the live `/data` tree during every build, ~90
requests per merge. It dominates the raw log and is excluded from the three
tables. Do not chase it.

**`x-edge-result-type = Error` on a race page that returned 200.** By design.
Race pages are not among the prerendered shells, so S3 has no object; CloudFront
turns the 403/404 into a 200 serving `index.html`, and the SPA renders the route
client-side. `Error` here means "the origin had nothing", not "the visitor saw a
failure".

**Requests for `/.env`, `/wp-login.php` and similar.** Vulnerability scanners,
usually spoofing a browser user agent. They have a dot in the last path segment,
so the page filter already drops them. Nothing is exposed — the bucket is
private and served through OAC.

**An empty report right after a deploy.** CloudFront delivers logs several times
an hour and reserves the right to take 24 hours. In practice the first files
appear within minutes. The command prints `No traffic since <date>` rather than
failing.

## Troubleshooting

**`ExpiredToken`** — usually *not* a stale session. The shell often carries
inherited, expired `AWS_*` variables that override `AWS_PROFILE`:

```bash
env | grep '^AWS_'
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
AWS_PROFILE=swimtrends aws sts get-caller-identity
```

If that succeeds, clearing the variables was the fix. Only if it genuinely needs
a new token: `awsume swimtrends --region eu-west-1`.

**`cf/` is empty more than 24 hours after enabling logging** — check the log
bucket's Object Ownership first:

```bash
aws s3api get-bucket-ownership-controls --bucket swimtrends-web-logs --profile swimtrends
```

It must be `BucketOwnerPreferred`. CloudFront's legacy standard logging delivers
via an **ACL grant**, and the post-April-2023 S3 default
(`BucketOwnerEnforced`) disables ACLs, so delivery fails **silently**. A healthy
bucket ACL shows two `CanonicalUser` FULL_CONTROL grants: the owner and
`awslogsdelivery`.

## What this cannot tell you

- **Search queries.** Google strips them from the referrer. They exist only in
  Google Search Console, which is the other half of the picture: it has queries,
  impressions, clicks and positions, but no direct traffic and no crawler view.
- **Unique visitors.** IP addresses are logged but not modelled. Fifty hits
  could be fifty people or one person reloading.
- **Anything older than 90 days.** A lifecycle rule expires the logs — they
  carry `c-ip`, which is personal data under GDPR, and the expiry is the
  mitigation.
- **Whether a visitor read anything.** No scroll depth, no time on page, no
  events. That would need a client-side script, which was deliberately not
  built.

## How it works

`SwimtrendsWebStack` enables CloudFront **standard logging (legacy)** on the
distribution, writing to `swimtrends-web-logs` under `cf/`. Legacy rather than
v2 because a v2 delivery source must be created in us-east-1 even when the
bucket is in eu-west-1 — a second cross-region stack, not worth Parquet output
at this volume. Neither generation is billed by CloudFront for delivery to S3;
the only cost is S3 storage, which is cents.

The query lives in `st-scrape/analytics/traffic.py`; the CLI wiring is the
`traffic` branch of `st-scrape/ingestion/cli.py`.
