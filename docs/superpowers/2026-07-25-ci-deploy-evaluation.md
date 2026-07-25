# CI / GitHub Actions for deploys — evaluation & recommendation

**Date:** 2026-07-25
**Status:** Evaluation only — no code. Pick this up in a fresh session to
brainstorm → spec → plan → build.
**Context:** Asked whether the manual web deploy (`make web-release`) should move
to CI (GitHub Actions) instead of being run by hand after each merge.

## Current state (2026-07-25)

- **No CI exists** — `.github/workflows/` is absent.
- Deploy is manual, from a dev machine with AWS profile `swimtrends`:
  - `make web-deploy` — `npm ci && npm run build`, `aws s3 sync web/dist … --exclude "data/*"`, CloudFront invalidate `/*`.
  - `make web-refresh` — `python -m webbuild --out web/public/data`, `aws s3 sync web/public/data … /data/`, CloudFront invalidate `/data/*`.
  - `make web-release` — `npm test` → `web-deploy` → `web-refresh`.
- Stack outputs resolved at runtime from `SwimtrendsWebStack` (bucket + distribution id) via `aws cloudformation describe-stacks`.
- Convention (now in CLAUDE.md): push + PR when implementation is done; web deploys are low-stakes, done after merge without asking. swimtrends.dk is production but not critical.

## The key insight: two deploys with different cadences

`web-release` bundles two things that should be thought about separately:

| | **App bundle** (`web/dist`) | **Data JSON** (`web/public/data`) |
| --- | --- | --- |
| Changes when | frontend code changes | curated zone changes (**hourly ingestion**) OR JSON-generation code changes |
| Build time | ~2–3 min | **~50 min** (full rebuild, S3-bound, serial per race) |
| Natural cadence | per merge | per ingestion cycle — **not** per merge |
| Files | small dist (JS/CSS/fonts) | ~1698 JSON files |

Most merges change only the app (or neither). Coupling a 50-minute full data
rebuild to every merge would waste Actions minutes for no benefit.

## Recommendation

**Adopt CI, but split it — and do not run the 50-min data build on every merge.**

### 1. App-deploy-on-merge → strong yes (do first)
A workflow on push to `master`:
- run `st-scrape` pytest + `web` vitest (gate),
- `npm ci && npm run build`,
- `aws s3 sync web/dist … --exclude "data/*"`,
- CloudFront invalidate `/*`.

Fast (~3–5 min), tested, no local creds, removes the manual step. This is the
clear, low-risk win.

### 2. Data refresh → decouple from merges
Options (pick during brainstorm):
- **Event-driven** from ingestion: when the curate pipeline updates the curated
  zone, trigger a refresh (EventBridge → `repository_dispatch`, or run webbuild
  in the existing AWS pipeline rather than GitHub at all).
- **Scheduled** nightly cron.
- **Manual** `workflow_dispatch` button for the occasional code change that
  alters JSON output (e.g. the junior-scoping PR #32).

This overlaps directly with the parked **auto-refresh Plan 4** (see the
`web-app-deferred-tiers` memory) — treat them as the same initiative.

### 3. The real bottleneck: webbuild is full-rebuild + ~50 min
CI doesn't fix slowness; it moves it off the laptop. The higher-leverage change
is making **webbuild incremental** (only rebuild changed meets/categories). Once
incremental, event-driven per-ingestion data refresh becomes cheap and the whole
"data in CI" question resolves cleanly. Consider this a prerequisite for a good
data-refresh automation, and a separable piece from the app-deploy workflow.

### 4. AWS auth in CI
Use **GitHub OIDC → assume an IAM role** (no long-lived access keys in GitHub
secrets). Add the OIDC provider + a scoped deploy role via the existing CDK app
(`swimtrends-app`). Scope the role to: the site S3 bucket, the CloudFront
distribution (create-invalidation), and read on the curated zone bucket for
webbuild.

## Separable pieces (suggested order)

1. **App deploy CI** — workflow + OIDC role. ~1 day. Low risk. High value.
2. **Incremental webbuild** — only rebuild changed meets. Enables cheap data CI.
3. **Event-driven / scheduled data refresh** — merge with auto-refresh Plan 4.

Each is its own spec → plan → build cycle.

## Open decisions for the brainstorm
- Do app and data deploy live in GitHub Actions, or does data refresh belong in
  the AWS ingestion pipeline (closer to where the curated zone changes)?
- How fresh must meet results be on the site? (Drives scheduled vs event-driven.)
- Is incremental webbuild worth building before automating data refresh, or ship
  a nightly full rebuild first and optimize later?
- OIDC role scoping and where it's defined in the CDK app.

## Pointers
- Make targets: `Makefile` (`web-deploy`, `web-refresh`, `web-release`).
- Web build: `st-scrape/webbuild/` (`build.py` serial loop over categories→meets→races).
- CDK web stack: `swimtrends-app/` (`SwimtrendsWebStack` — bucket + distribution).
- Related memory: `web-app-deferred-tiers` (auto-refresh Plan 4), `web-deploy-when-needed` (deploy-when-needed convention), `web-app-mvp-deployed`.
