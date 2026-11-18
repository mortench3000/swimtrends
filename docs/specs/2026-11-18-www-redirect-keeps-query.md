# www → apex redirect keeps the query string

## Why
`cloudfront/viewer_request.js` 301s any non-apex host (www) to
`https://swimtrends.dk` + path, dropping the query. Since meet pages carry their
filters in the URL (`?discipline=IM&gender=M`, see
`2026-11-18-meet-filters-in-url.md`), a shared `www.` link loses them, and so do
inbound `utm_*` tags.

## Change
- The redirect's `Location` appends the original query string, rebuilt from
  `request.querystring` (CloudFront Functions object form:
  `{ name: { value, multiValue?: [{ value }] } }`).
  - Parameter order kept; every value of a repeated parameter written
    (`multiValue` when present, else `value`).
  - Each name and value is decoded then re-encoded (`encodeURIComponent`), so
    the result is correct whether CloudFront hands the values over encoded or
    not; a malformed `%` sequence passes through unchanged instead of throwing.
  - No query → no `?` (today's behaviour).
- Apex requests are unchanged (only the `/index.html` rewrite; the query is not
  touched).
- ES5 only (CloudFront Functions runtime).

## Affected paths
- `swimtrends-app/cloudfront/viewer_request.js`
- `swimtrends-app/tests/unit/test_web_stack.py` (runs the real function in node;
  CI runs it)
- `docs/specs/2026-11-18-meet-filters-in-url.md` (known-gap line → fixed)
- Deploy: `SwimtrendsWebStack` only, with `-c alert_email` (its cost-budget alert
  uses it). `SwimtrendsCertStack` untouched.

## Verification
- Unit: www + filters keeps `?discipline=IM&gender=M`; repeated parameter keeps
  both values; encoded value stays correctly encoded; no query → no `?`; apex
  with a query is only rewritten.
- `cdk diff` shows only the function code changing.
- Live: `curl -sI 'https://www.swimtrends.dk/DM-L/10334?discipline=IM&gender=M'`
  → 301 to `https://swimtrends.dk/DM-L/10334?discipline=IM&gender=M`.
