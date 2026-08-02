# Web traffic analytics — design

Date: 2026-08-02
Status: approved, ready for planning

## Problem

swimtrends.dk was submitted to the Google index on 2026-07-30 (see
[the search-indexing spec](2026-07-30-search-indexable-pages-design.md)). We
have no way to tell whether anyone other than the two of us has visited the
site, which pages they land on, or whether crawlers are reaching the 41
prerendered meet shells at all.

We want to answer two questions:

1. **Is there traffic?** — hits over time, which pages, where from.
2. **What does search bring in?** — queries, impressions, clicks.

## Decision

Question 2 needs **no build**: Google Search Console already reports queries,
impressions, clicks, CTR and landing pages. It is treated here as
already-shipped, not as scope.

Question 1 is answered by **CloudFront standard logging (legacy) to S3**,
queried locally with the DuckDB tooling this repo already has.

### Why not a client-side script

GoatCounter / Plausible / Umami give a dashboard for one `<script>` tag, but:
they undercount behind ad blockers, put the data outside this account, and —
decisively — cannot see crawler traffic. "Did Googlebot fetch the prerendered
shells?" is the question we are actually uncertain about this month, and only
server-side logs answer it. A homegrown pixel (Lambda URL + DynamoDB) is the
same thing with us as the maintainer; rejected.

### Why legacy logging and not v2

Standard logging v2 is the newer path and is better on paper: selectable
fields, Parquet output, Hive-compatible partitioning — which would match the
curated zone's shape exactly.

It is rejected because **the v2 delivery source must be created in us-east-1**
even when the destination bucket is in eu-west-1
([docs](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging.html)).
That means a second cross-region stack — the same shape that produced the ACM
cross-region deadlock. Not worth Parquet for a site with near-zero traffic.

Legacy is one property on the existing `Distribution` plus one bucket, entirely
in eu-west-1. Its cost is gzipped TSV instead of Parquet, which is a one-time
column list in one SQL string.

Neither generation is billed by CloudFront for delivery to S3; we pay only S3
storage, which is cents at this volume.

## Components

### 1. Log bucket + distribution logging — `swimtrends-app/swimtrends_app/swimtrends_web_stack.py`

A second bucket in the existing web stack:

- `bucket_name="swimtrends-web-logs"` — explicitly named, like
  `swimtrends-meet-data`, so the CLI can default to it instead of resolving a
  CDK-generated name from stack outputs.
- `block_public_access=BLOCK_ALL`, `encryption=S3_MANAGED`, `enforce_ssl=True`
  — matching `SiteBucket`.
- `object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED`. **Load-bearing.**
  Legacy logging delivers via an ACL grant to the log-delivery canonical user.
  Buckets created after April 2023 default to `BUCKET_OWNER_ENFORCED`, which
  disables ACLs and makes CloudFront silently fail to deliver
  ([docs](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/standard-logging-legacy-s3.html)).
- One lifecycle rule: `expiration=Duration.days(90)`.
- `removal_policy=RemovalPolicy.DESTROY` + `auto_delete_objects=True`. Logs are
  disposable; no IAM Deny on delete, because this is not a data zone.

On the existing `Distribution`: `enable_logging=True`,
`log_bucket=logs_bucket`, `log_file_prefix="cf/"`,
`log_includes_cookies=False`.

Plus `CfnOutput` `LogsBucketName`.

### 2. `traffic` subcommand — `st-scrape/ingestion/cli.py`

A new read-only subcommand alongside `query` / `meets` / `categories` /
`summary`; added to `READONLY_COMMANDS` so it short-circuits before
`REGISTRY_TABLE` and the rest of the ingestion wiring are required.

```
python -m ingestion.cli traffic [--days 14] [--bucket swimtrends-web-logs]
```

It reuses `analytics.loader.bind_s3()` for the httpfs extension and the
`credential_chain` secret. `bind_s3` also defines the `cur_*` curated views;
defining a view scans nothing, so the reuse is free.

The query reads `s3://<bucket>/cf/*.gz` via `read_csv` with `delim='\t'`,
`header=false`, and an explicit 33-name column list — CloudFront writes a
two-line `#Version` / `#Fields:` preamble that defeats DuckDB's header
detection, and the `#`-prefixed lines are skipped as comments.

Field order (CloudFront legacy standard log format):

```
date, time, x-edge-location, sc-bytes, c-ip, cs-method, cs(Host), cs-uri-stem,
sc-status, cs(Referer), cs(User-Agent), cs-uri-query, cs(Cookie),
x-edge-result-type, x-edge-request-id, x-host-header, cs-protocol, cs-bytes,
time-taken, x-forwarded-for, ssl-protocol, ssl-cipher,
x-edge-response-result-type, cs-protocol-version, fle-status,
fle-encrypted-fields, c-port, time-to-first-byte, x-edge-detailed-result-type,
sc-content-type, sc-content-len, sc-range-start, sc-range-end
```

### 3. Output

Three small tables over the last `--days`, each split **human vs bot** rather
than bot-filtered — right after indexing, "Googlebot fetched 41 meet shells" is
a result we want to see, not noise:

- hits per day
- top paths
- top referrers

Rows are restricted to page requests so `/assets/*.js` and `/data/*.json` do
not drown out the pages. Concretely: `sc-status` in (200, 304), `cs-method` =
`GET`, and `cs-uri-stem` either has no file extension in its last segment or
ends in `.html`.

### 4. Bot detection

A user-agent regex — `bot|crawl|spider|slurp` — case-insensitive, marked with a
`ponytail:` comment naming the ceiling (crude substring match; upgrade to a
maintained UA list only if it visibly misclassifies).

Log field values are percent-encoded by CloudFront. The regex deliberately
matches the **encoded** string: those tokens are alphanumeric and survive
percent-encoding unchanged, so no decoding step is needed for classification.
Decoding is only a display concern, and truncating the UA in output sidesteps
it.

## Testing

- **CDK assertion test** (`swimtrends-app/tests/unit`), in the same PR per the
  infra rule: the distribution has a `Logging` block pointing at the logs
  bucket with prefix `cf/`; the bucket has `ObjectOwnership`
  `BucketOwnerPreferred` and a 90-day expiration rule.
- **One pytest** (`st-scrape/tests`) over a small fixture log file — a
  handful of lines including the `#Version`/`#Fields:` preamble, one Googlebot
  row, one browser row, one asset request — asserting the parse, the asset
  exclusion and the human/bot split. In-memory DuckDB reading a local file; no
  S3.

## Privacy

`c-ip` is logged and is personal data under GDPR. The mitigation is the 90-day
lifecycle expiry. No cookies and no client-side script are involved, so no
consent banner is required.

Whether the site should carry a privacy note is a separate product decision and
is **out of scope** here.

## Out of scope

Dashboard or web UI. Unique-visitor modelling. Glue/Athena table. Standard
logging v2 / Parquet. Real-time logs. Alerting on traffic. A privacy policy
page.

## Verify during implementation

Three things this design assumes that should be confirmed rather than trusted:

1. **Does `cs-uri-stem` record the URI before or after the viewer-request
   function rewrites it?** `cloudfront/viewer_request.js` appends `/index.html`
   to extensionless paths. If the log shows the rewritten form, path grouping
   must strip the suffix to keep `/DM-L/12486` and `/DM-L/12486/index.html`
   from splitting into two rows.
2. **Does DuckDB expose `url_decode`?** If it does, use it for the referrer and
   UA display columns. If not, truncate instead — bot classification does not
   depend on it either way.
3. **Cache hits still log.** `CACHING_OPTIMIZED` means repeat views are served
   from the edge; those requests do appear in the access logs (with
   `x-edge-result-type=Hit`) but never reach S3. Counts are therefore complete;
   an origin-request count near zero is expected and not a bug.
