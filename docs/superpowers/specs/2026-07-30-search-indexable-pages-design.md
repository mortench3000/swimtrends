# Search-Indexable Pages — Design Spec

- **Date:** 2026-07-30
- **Status:** Approved (design)

## Context & goal

swimtrends.dk has been live for weeks and `site:swimtrends.dk` on Google returns
**nothing**. The site is not ranked badly — it is not indexed at all.

Measured on the live site (2026-07-30):

| Probe | Result |
| --- | --- |
| `GET /` | 200, `text/html`, **394 bytes** |
| `GET /` as Googlebot UA | 200 — nothing is blocking the crawler |
| response headers | no `x-robots-tag`, no redirect, valid TLS, `x-cache: Hit from cloudfront` |
| `GET /robots.txt` | 200 but serves **`index.html`** (the SPA 404 fallback) |
| `GET /sitemap.xml` | 200 but serves **`index.html`** |
| `GET /meet/12486` | 200, serves `index.html` — the SPA fallback already works for paths |
| `www.swimtrends.dk` | **does not resolve** (no DNS record) |

Root cause, in order of severity:

1. **Hash routing collapses the whole site to one URL.** `web/src/router.js`
   emits `#/c/DM-L/m/12486`. Everything after `#` is a fragment: never sent to
   the server, never a separate URL to any crawler (Google's `#!` AJAX-crawling
   scheme was deprecated in 2015, support removed 2018). There are 46 meet pages
   and ~1700 race pages in `web/public/data/`, and **zero** are addressable.
2. **The one addressable URL has no content without JS.** `<title>Swimtrends</title>`,
   no meta description, no `<h1>`, empty `<div id="app">`. Google renders JS, but
   there is one URL with a generic title and nothing to match a query against.
   (Content counts, measured: 41 meets and ~1700 races across 5 categories.)
3. **No `robots.txt`, no `sitemap.xml`.** Both are swallowed by the
   403/404 → `/index.html` error responses in `swimtrends_web_stack.py:36-41`.
4. **Nothing links to the domain and it was never submitted** to Search Console.

The goal: make every meet page a real, crawlable URL that serves unique Danish
text without JavaScript, and tell Google those URLs exist.

Out of scope: ranking. Indexing is a precondition, not a guarantee — backlinks
and query-matching content are a months-long, non-technical effort.

## Decisions

**URL shape — clean, no marker segments.** Chosen over mirroring today's
`c/…/m/…` structure. URLs are permanent, so this is decided once.

```
/                                    home, no category
/DM-L                                category
/DM-L/12486                          meet
/DM-L/12486/M-100-Fri-LCM            race
```

Parsing is unambiguous by segment count (1 = category, 2 = meet, 3 = race);
category codes are non-numeric (`DM-L`, `DM-K`, `DMJ-L`, `DMJ-K`, `DO`) and meet
ids are numeric, so there is no collision. Real files (`/assets/*`, `/data/*`,
`/robots.txt`, `/sitemap.xml`) all carry an extension and never look like routes.

**Prerender scope — home + 5 category pages + 41 meet pages = 47 URLs.** Meet
pages carry the AI evaluation prose (`data/<cat>/<meet>/evaluation.json`), which
is genuinely unique Danish text worth indexing. Race pages are near-duplicate
result tables with no prose; ~1700 thin pages risk being read as low quality, and
they stay SPA-reachable but out of the sitemap.

Category pages were added to the original home-plus-meets scope because they cost
~15 lines and their data was already being fetched, and they turn the sitemap into
a real **crawl graph**: home links to all 5 categories, each category links to its
meets, all in static HTML. Static internal links are a stronger discovery signal
than a sitemap alone. Meet pages deliberately do *not* link to their ~42 races —
that would put 1700 out-of-scope URLs back into the crawl.

**Prerender input — fetched from the live `/data` zone at build time.**
`web/public/data/` is **gitignored**, so CI has no data when it runs
`npm run build`. Three options were considered:

| Option | Verdict |
| --- | --- |
| Commit an SEO manifest to git | Rejected: goes stale silently on every new meet |
| Read the curated zone from S3 in CI | Rejected: needs new IAM on the deploy role |
| Fetch `https://swimtrends.dk/data/*.json` at build time | **Chosen** |

The data zone is already public via CloudFront, so this needs no credentials and
never goes stale. A fetch failure **fails the build** — deliberately, because
`make web-deploy` syncs `--delete`, so silently prerendering nothing would delete
the good pages from the bucket. Failing early means no sync runs at all.
Overridable with `SEO_DATA_BASE` for local runs.

## The CloudFront gotcha (why this needs an infra change)

`default_root_object="index.html"` applies **only to `/`**. The origin is an S3
REST endpoint via OAC, which — unlike an S3 *website* endpoint — has no concept
of a directory index document. So a request for `/DM-L/12486` looks for the key
`DM-L/12486`, misses, and falls through to the 404 → `/index.html` error
response, serving the **generic** shell rather than the prerendered one.

Fix: a **CloudFront Function** on viewer-request that appends `/index.html` to
any path with no file extension. ~10 lines, the standard pattern for this
topology.

```
/DM-L/12486        → /DM-L/12486/index.html   → prerendered page (200)
/DM-L/99999        → /DM-L/99999/index.html   → 404 → /index.html (SPA renders)
/DM-L/12486/M-100-Fri-LCM → …/index.html      → 404 → /index.html (SPA renders)
/data/index.json   → untouched (has an extension)
/assets/index-x.js → untouched
/                  → default_root_object
```

The existing 403/404 fallback stays: it is what makes non-prerendered routes
(categories, races, unknown paths) work.

**No hard ordering dependency.** Path routing works *today* without the function
(the 404 fallback serves the SPA, which reads `location.pathname`), so this PR is
safe to merge before the CDK deploy. Only the prerendered HTML needs the
function, so the SEO benefit lands when the stack is deployed.

## Affected files, exhaustively

### Routing (step 1)
| File | Change |
| --- | --- |
| `web/src/router.js` | `parseHash` → `parsePath(pathname)`; `href()` emits paths; add `navigate()` (pushState), `popstate` listener, delegated click interceptor, `legacyPath()` hash→path redirect |
| `web/src/routes/Home.svelte:50` | `location.hash = href(…)` → `navigate(href(…))` |
| `web/src/routes/Meet.svelte:86,92,95,188` | no change — all go through `href()` |
| `web/src/routes/Race.svelte:52,53,61,62,70,71` | no change — all go through `href()` |
| `web/src/components/Breadcrumbs.svelte` | no change — renders whatever `href` it is given |
| `web/src/components/SwimmerLink.svelte` | no change — external origin, click interceptor must skip it |
| `web/src/App.svelte` | no change — reads `$route.name`/`params` |
| `web/tests/router.test.js` | rewrite for paths; add legacy-hash and click-interception cases |

The click interceptor must not hijack: external origins (SwimmerLink →
`svømmetider.dk`, the footer's `svømmetider.dk` link), `target="_blank"`,
`download`, modified clicks (ctrl/meta/shift/alt), non-left buttons, and
already-`defaultPrevented` events.

**Old links keep working.** `legacyPath('#/c/DM-L/m/12486')` → `/DM-L/12486` via
`replaceState` on load, so anything already shared resolves to the new URL.

### Metadata (step 3)
| File | Change |
| --- | --- |
| `web/src/lib/seo.js` | **new** — pure title/description builders, imported by *both* the SPA and the prerender script |
| `web/src/lib/meta.js` | **new** — `setMeta()`, the DOM side-effect (title, `meta[name=description]`, `link[rel=canonical]`) |
| `web/src/routes/Home.svelte` | call `setMeta` once data loads |
| `web/src/routes/Meet.svelte` | call `setMeta` once `meet` loads |
| `web/src/routes/Race.svelte` | call `setMeta` once `race` loads |
| `web/index.html` | add a default `<meta name="description">` + `<link rel="canonical">` for the prerenderer to overwrite |

### Crawl directives + prerender (steps 2 & 4)
| File | Change |
| --- | --- |
| `web/public/robots.txt` | **new** — `Allow: /` + `Sitemap:` line. Deliberately does **not** disallow `/data/`: Google needs to fetch it to render the SPA |
| `web/prerender.mjs` | **new** — fetch data, write 47 `index.html` shells (home, 5 categories, 41 meets) + `dist/sitemap.xml`; exports pure `renderShell`/`buildSitemap` for tests |
| `web/package.json` | `"build": "vite build && node prerender.mjs"` |
| `web/src/main.js` | clear `#app` before `mount()` — Svelte 5 `mount()` **appends**, so the prerendered fallback body would otherwise stay on screen under the hydrated app |
| `web/tests/seo.test.js` | **new** — `renderShell`, `buildSitemap`, title/description builders |

`prerender.mjs` injects into vite's `dist/index.html` by string replacement, so
it **asserts its markers exist** and throws otherwise — a silent no-op here would
publish 46 pages with the wrong `<title>`.

### Infra
| File | Change |
| --- | --- |
| `swimtrends-app/cloudfront/append_index.js` | **new** — the viewer-request function body (ES5; the Functions runtime is not a full JS engine) |
| `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` | load it with `FunctionCode.from_file`, associate on the default behavior |
| `swimtrends-app/tests/unit/test_web_stack.py` | assertion test (function exists + associated) **plus** a table-driven test that runs the real function body through `node` over 11 URIs |

The rewrite is tested by execution rather than inspection because its failure mode
is silent: a wrong condition serves the generic shell on all 47 pages, which looks
exactly like the bug being fixed.

`make web-deploy` needs no change: it already syncs `web/dist → s3://…/` with
`--delete --exclude "data/*"`, and the prerendered files land *inside* `dist`.
`aws s3 sync` infers `text/html` / `text/plain` / `application/xml` from the
extensions, which is why prerendered pages are `…/index.html` keys rather than
extensionless ones.

## Deferred, with reasons

- **`www.swimtrends.dk`** — still dead, and it is a plausible way early
  word-of-mouth links died silently. Not folded into this PR after all: the ACM
  cert in `swimtrends_cert_stack.py` has **no SAN for `www`**, so adding it
  *replaces* the certificate and swaps it on the distribution — a two-stack
  cross-region deploy with a DNS-validation wait. That is unrelated risk on an
  SEO PR. Follow-up PR, small and self-contained.
- **JSON-LD structured data** (`SportsEvent`) — gravy; worthless until pages are
  indexed at all.
- **Soft 404s** — an unknown category (`/XX-Y`) renders home rather than a 404
  page. The sitemap only lists real URLs so crawlers will not find these, and a
  real 404 view needs a status code the SPA cannot set.
- **Race-page prerendering** — see the scope decision above. Revisit if meet
  pages get indexed and race-page queries show up in Search Console.

## Verification

1. `cd web && npm test` — router, seo, existing suites.
2. `npm run build` then confirm `dist/sitemap.xml`, `dist/robots.txt`, and
   `dist/DM-L/12486/index.html` exist and that the last contains the meet name in
   `<title>` and evaluation prose in the body.
3. `curl` the built shell with JS disabled semantics (`grep` for the prose) —
   content must be present in the raw bytes.
4. `/run-web` screenshot: navigation works, no flash of duplicated content,
   breadcrumbs and back/forward behave.
5. `cd swimtrends-app && .venv/bin/python -m pytest tests/unit`.
6. Post-deploy: `curl -sI https://swimtrends.dk/DM-L/12486` → 200 with the meet
   title in the body; `curl https://swimtrends.dk/sitemap.xml` → XML, not HTML.
7. Search Console: verify the domain (DNS TXT in the existing Route53 zone),
   submit `sitemap.xml`, request indexing of the homepage.
