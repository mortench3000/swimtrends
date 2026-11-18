# www → apex redirect keeps the query string

## Why
`cloudfront/viewer_request.js` 301s any non-apex host (www) to
`https://swimtrends.dk` + path, dropping the query. Since meet pages carry their
filters in the URL (`?discipline=IM&gender=M`, see
`2026-11-18-meet-filters-in-url.md`), a shared `www.` link loses them, and so do
inbound `utm_*` tags.

## Change
- The redirect's `Location` appends the original query **verbatim**, from
  `request.rawQueryString()` (JS runtime 2.0, which this function already uses):
  the query exactly as the visitor sent it, without the leading `?`.
  - Copied as-is: no decoding or re-encoding, so `+`, `%20` and a stray `%` are
    never reinterpreted, and nothing new (CR/LF, `&`, `#`) can be introduced.
  - `undefined` (no `?`) or `""` (a bare `?`) → no `?` in the Location.
  - Considered first and dropped after review: rebuilding from the parsed
    `request.querystring` object with decode-then-encode. It turned `+` into
    `%2B` and needed an unsafe fallback for malformed escapes, and its result
    depended on whether CloudFront decodes values (undocumented).
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
- Unit (a stand-in `rawQueryString()` in the node harness): www + filters keeps
  `?discipline=IM&gender=M`; repeated parameter, `+`, `%20` and a stray `%` are
  copied verbatim; bare `?` and no query → no `?`; apex with a query is only
  rewritten.
- `cdk diff` shows only the function code changing.
- Live: `curl -sI 'https://www.swimtrends.dk/DM-L/10334?discipline=IM&gender=M'`
  → 301 to `https://swimtrends.dk/DM-L/10334?discipline=IM&gender=M`; also a
  query with `+` and `%20`, copied unchanged.
