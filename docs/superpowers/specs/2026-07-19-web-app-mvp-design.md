# Swimtrends Web App — MVP Design (Public Standard Tier)

_Date: 2026-07-19 · Status: draft for review_

## Sentiment (agreed)

Swimtrends is a **modern data-app for the people steering Danish competitive
swimming** — coaches, clubs, and the federation — not for individual swimmers
tracking personal times. Its job is **exploration and trend-monitoring, always
scoped within a category** (DM-L, DM-K, DO, …), never across categories. Users
drill **Category → Meet → Race**, see **standardized key facts that make meets
and races comparable**, and stack them against the **previous 3–5 seasons** to
read the direction of travel — spotting momentum and decline early.

Register: **modern data-app** — crisp, interactive, dark-mode-first, snappy
filters, charts you enjoy using (Linear/Vercel-era), not clinical tables.

Guiding feeling: _the instrument the sport's decision-makers reach for to
understand where Danish swimming is heading._

## Scope

**In scope (this MVP = sub-project #1, public standard tier):**
- Public, read-only, no login.
- Category → Meet → Race navigation with standardized key facts.
- Season comparison (user picks 3–5 seasons) at meet and race level.
- Beautiful interactive visuals.

**Out of scope (later sub-projects, their own spec→plan→build):**
- #2 Auth / registration.
- #3 Advanced/costly ad-hoc queries + Bedrock/AgentCore LLM chat over a
  user-selected slice.

The MVP is built **"A now, C later"**: static delivery now, with the JSON
schema and frontend shaped so a query API bolts on for the advanced tier
without a rewrite.

## Architecture — Static precompute + SPA

```
curated Parquet (S3)  ──►  build job (Python + DuckDB, reuses analytics views)
                              └─ emits static JSON  ──►  s3://<site>/data/…
static SPA (Svelte)  ──build──►  s3://<site>/  ──►  CloudFront (OAC)  ──►  users
                                    (SPA fetches /data/*.json client-side)
```

The public view universe (categories × meets × races + season bundles) is
**finite and slow-changing** (new data only when a meet is curated, hourly
ceiling). So we precompute JSON instead of querying live — cheapest, fastest,
near-zero ops, infinite scale.

### Data build job
- Python script (new, under `st-scrape/webbuild/`) that loads the curated
  Parquet via `analytics.loader.create_views` and the existing SQL views, then
  writes JSON files. **Reuses the views verbatim** — no new analytics math.
- **Trigger: hourly EventBridge-scheduled full rebuild.** The dataset is small
  (tens of meets), a full rebuild is cheap, and this avoids per-object S3-event
  debounce complexity. `# ponytail: full rebuild hourly; switch to event-driven
  incremental if the meet count ever makes a full rebuild slow.`
- Runs as a Lambda (DuckDB via pip/layer) or a small Fargate task reusing the
  curate image — decided in the plan by whichever the CDK app already makes
  cheapest to add.

### JSON layout (the seam for the future API)
Mirror the eventual API's resource shape so the frontend's data-access layer
never has to change when #3 adds live endpoints:
```
/data/index.json                         # categories + latest seasons
/data/<category>/meets.json              # meet list for a category
/data/<category>/<meet_id>/meet.json     # meet key facts + season comparison
/data/<category>/<meet_id>/races.json    # race list
/data/<category>/<meet_id>/<race_id>.json# race key facts + season comparison
```
Frontend reads through a single `dataClient` module; swapping static-fetch for
`fetch('/api/…')` later is a one-module change.

### Frontend
- **Svelte + Vite** app shell (small bundle, snappy, first-class stores for
  filter state). Dark-mode-first.
- **Observable Plot** for charts (declarative, beautiful defaults, small);
  hand-rolled SVG/CSS for stat tiles and podium. Follow the `dataviz` skill for
  palette/marks/accessibility.
- Client-side routing for Category → Meet → Race. No SSR (static host).
- Discreet, persistent attribution in the footer: **"Data fra
  svømmetider.dk"** (Danish, linked). Public tier shows athlete data as-is.

## Language & locale
**All user-facing frontend copy is in Danish** — labels, headings, tooltips,
empty states, the attribution line, everything the audience reads. Code,
identifiers, comments, tests, and these docs stay English. Domain values are
already Danish (`Fri/Ryg/Bryst/Fly`, `DM-L`, …) and render as-is. Single
locale → **no i18n framework** (`# ponytail: Danish strings inline; add i18n
only if a second language is ever required`). Use `da-DK` formatting for dates
and any localized numbers; swim times keep standard `m:ss.cc` notation.

## Visual identity (starting point — refine in build)
Modern data-app, **dark-mode-first** with a light toggle, themed via CSS custom
properties (`prefers-color-scheme` default + a manual override).
- **Palette:** dataviz brand-neutral neutrals (slate/zinc) + a single **aqua/
  cyan accent** (water) for interactive elements and the primary series.
  Semantic trend colors: green = improvement, amber/red = regression — applied
  consistently to season deltas.
- **Typography:** one clean grotesque/geometric sans for UI (e.g. Inter); use
  **tabular figures** (`font-variant-numeric: tabular-nums`) everywhere times,
  points, and counts appear so columns align — non-negotiable for a data-app.
- **Density:** comfortable-but-information-rich; stat tiles + charts over walls
  of tables. Follow the `dataviz` skill for chart palette, marks, and
  light/dark contrast validation.

### Deploy target
New CDK stack `SwimtrendsWebStack` in `swimtrends-app/`, consistent with
existing stacks: private S3 site bucket + CloudFront distribution with Origin
Access Control, plus the build job + its hourly schedule.
- **Domain:** `swimtrends.dk` — Route53 hosted zone `Z05943842L8KIUA914B4J`
  already exists. Add an ACM cert **in us-east-1** (CloudFront requires it
  there; DNS-validated against the zone), attach to the distribution, and add a
  Route53 A/AAAA alias to CloudFront.
- **Environments:** prod-only. Account 179537025528 / eu-west-1 (reuse the
  existing `ENV` in `app.py`).
- Deploy via the existing runbook (node 22, `-c alert_email`, Docker).

**Migrating off the existing sample landing page.** Today `swimtrends.dk` is a
single sample `landing-page.html` in an S3 **website-hosting** bucket named
`swimtrends.dk`, with a Route53 A-alias to the HTTP-only S3 website endpoint —
no CloudFront, no HTTPS. This MVP replaces it:
- Scrap the sample: the old `swimtrends.dk` website bucket + its `landing-page.
  html` are no longer needed. Our CloudFront+OAC setup uses a fresh CDK-managed
  **private** bucket (OAC doesn't require the bucket name to match the domain),
  so the old bucket can simply be deleted.
- **Repoint DNS:** delete the existing manual `swimtrends.dk` A record first, so
  the CDK-managed alias-to-CloudFront can be created without a collision. Net
  result is an HTTPS upgrade for the domain.

**Cross-region cert gotcha:** the WebStack runs in eu-west-1 but CloudFront
needs the cert in us-east-1. Handle in the plan via `crossRegionReferences` (or
a small dedicated us-east-1 cert stack). `# ponytail: whichever the CDK version
here supports with least ceremony.`

### Local development (test before deploy)
Fully native to Vite — no extra tooling:
1. **Build data locally:** run the JSON build (same script as prod) with a
   local output target → writes into the SPA's `public/data/`. Data source is
   either the curated Parquet read from S3 via DuckDB, or the in-repo test
   fixtures for offline work.
2. **Serve:** `npm run dev` — Vite serves the SPA + local `/data/*.json` with
   hot reload. `dataClient` uses the same relative `/data/…` paths as prod, so
   there is **no dev/prod code branching**.
3. **Prod-bundle smoke test:** `npm run build && npm run preview` to verify the
   built artifact locally before deploying.

A `make dev` (or documented npm scripts) wires build-data → dev in one step.
This local run is the pre-deploy verification step in the acceptance loop.

### CI/CD
No pipeline for the MVP. Ship via the manual CDK runbook plus one script
(`swimtrends-app/` or `st-scrape/webbuild/`) that does: Vite build → `aws s3
sync` to the site bucket → CloudFront invalidation. `# ponytail: manual
build+sync script; add GitHub Actions when deploys get frequent enough to
annoy.`

## Feature detail — key facts

**Meet level** (comparable across 3–5 chosen seasons; season deltas shown):
- Total entrants / swims, # events, # clubs, # juniors.
- Field quality: median & top WA points across the meet.

**Race level** (per race in the meet):

| Fact | Source |
|---|---|
| Number of contestants (+ DNS/DSQ counts) | `results` counts |
| Podium — gold/silver/bronze, time + WA points | `rank IN (1,2,3)`, finals |
| Winning time & winner's WA points | `arg_min` time / `points` |
| A-final cutline (8th-fastest heat time) | `cutline_time` (exists) |
| Field depth/spread — 1st↔8th and 1st↔last gaps | time spread |
| Median time & median WA points | field aggregate |
| Heats→final drop (qualifying vs final time) | `phase` + splits |
| Junior presence & junior champion | `is_junior`, `junior_championship` |
| Fastest split / negative-split count | `cur_fact_split` |
| Season comparison — winning time, cutline, field size, median points (3–5 seasons) | `event_standard_by_season` |

## Testing (TDD)
- **Data build:** `st-scrape/tests/` — build against the in-memory curated
  fixture (`tests/analytics_fixtures.build_curated` + `create_views`), assert
  the emitted JSON has the expected facts and season bundles. No S3.
- **Frontend:** component tests for the key-facts/comparison views + one smoke
  e2e that loads a meet and a race from fixture JSON and asserts the charts and
  numbers render. Keep it minimal (ponytail).
- **CDK:** assertion tests in `swimtrends-app/tests/unit` for the new stack
  (bucket private, CloudFront OAC, schedule present).

## Acceptance gates ("satisfactory deployed result")
1. **Tests pass** — pytest (app + build) + CDK unit tests green.
2. **Deployed & reachable** — `cdk deploy SwimtrendsWebStack` succeeds; live
   smoke test: `https://swimtrends.dk` returns 2xx and a known `/data/*.json`
   loads.
3. **Code review clean** — pr-review-toolkit review, no unaddressed
   blockers/majors.
4. **Human approval** — you sign off before it's called done.

## Privacy / data
Public tier shows athlete data (names, birth years, ages incl. minors) **as-is**;
the source (svømmetider.dk) is already public. Requirement: a discreet,
persistent "Data from svømmetider.dk" attribution on the page. No takedown/
opt-out flow in the MVP (revisit if requested).

## Open questions / risks
- **Race identity:** confirm a stable `race_id` in the curated data for the
  race-level JSON keys (else derive from event + phase).
- **Season comparison base:** use `event_standard_by_season` for race trends;
  confirm it keys cleanly to a single race across seasons within a category.
- **Build runtime:** Lambda-with-DuckDB vs small Fargate — decide in the plan.
