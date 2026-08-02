# CLAUDE.md — Swimtrends

Guidance for AI agents (and humans) working in this repo. Read this first.

## What this is
Analytics of Danish competitive swimming. Meet results are scraped from
svømmetider.dk into a raw zone on S3, transformed into a curated Parquet zone
(World Aquatics points + open/para/junior classification), catalogued in Glue,
and queried locally with DuckDB. Ingestion is automated on AWS (DynamoDB
registry + dispatcher Lambda + Fargate scraper, hourly EventBridge cycle).

## Repository layout
| Path | What |
| --- | --- |
| `st-scrape/` | **The application.** `scrape_races.py` (scraper), `curate/` (raw→Parquet transform), `analytics/` (DuckDB views + loader), `ingestion/` (registry, dispatcher, `cli.py`), `webbuild/` (curated→SPA JSON + `digest.py`), `evaluation/` (AI meet reports: agent, S3 cache, number check), `gen_base_times.py`, `tests/`, `notebooks/`. |
| `web/` | The **SPA** (Svelte 5 + Vite). Real path routes (`/<cat>/<meetId>/<raceKey>`), `prerender.mjs` post-build step, `src/lib/seo.js` shared with it. |
| `swimtrends-app/` | AWS **CDK infrastructure** (Python): S3, DynamoDB, dispatcher/curate Lambdas, Fargate task defs, SNS, Glue. Stacks in `swimtrends_app/*_stack.py`; tests in `tests/unit`; `cloudfront/viewer_request.js` viewer function. |
| `docs/` | [`analytics.md`](docs/analytics.md) (querying), [`ingestion.md`](docs/ingestion.md) (operational CLI), design specs/plans under `superpowers/`. |
| `legacy/` | Deprecated original Scrapy → PostgreSQL pipeline + Docker. Not maintained. See [`legacy/README.md`](legacy/README.md). Don't build on it. |

## Data flow
```
scrape_races.py <meet_id> <categories…>
  └─ db/<id>_{meet_info,races,results}.jsonl
       └─ upload to s3://swimtrends-meet-data/raw/meet=<id>/  (results.jsonl LAST)
            └─ CurateTrigger Lambda (S3 ObjectCreated on results.jsonl)
                 └─ curate Fargate task  →  curated/{dim_meet,dim_race,fact_result,
                        fact_split,obt_result}/season=<Y>/course=<C>/meet=<id>.parquet
                      └─ Glue catalog + local DuckDB (analytics/loader.py)
```
- Bucket `swimtrends-meet-data` is **versioned** (overwrites keep prior versions).
- Registry table `swimtrends-meet-registry`. Base times at `reference/point_base_times.jsonl`.
- The curate trigger URL-decodes the S3 key (`meet%3D…`) — keep that if you touch it.

## Workflow
Default flow: **brainstorm → spec → plan → build → verify → PR → merge → deploy.**
Write the spec to `docs/specs/` and commit it *before* implementation starts. Once
the plan is approved, spawn subagents for the implementation/review waves.

When implementation is complete and tests pass, push the branch and open a PR
(squash-merge to master, matching history — don't commit to master directly).
Merging deploys the SPA automatically; afterwards run `make web-refresh` only if
the data needs it (see Guardrails).

**All GitHub operations go through the `gh` CLI** — never the web UI, never raw
`curl` to the API. The `test-and-deploy` job in `.github/workflows/ci.yml` runs on
every PR, so wait for it to be green before merging.
```bash
git push -u origin <branch>
gh pr create --base master --title "<type>: <summary>" --body "<what + why>"
gh pr checks --watch          # CI status for the current branch's PR
gh pr merge --squash --delete-branch
```

### Specs and plans
- Enumerate **every** affected page / view / data path in the spec, explicitly —
  a list, not a hand-wave.
- Re-read the plan for self-contradictions before starting tasks; helper-function
  signatures that drift between steps are the usual offender.

### Browser verification
UI changes get a real browser screenshot before the PR (`/run-web`). Run
`npx playwright install chromium` first and check that the installed browser
matches the Playwright package version. No Chrome extensions.

## Environment & setup
Two independent virtualenvs:
- **App/tests:** `st-scrape/.venv` ← `requirements.txt` (+ `requirements-dev.txt`, `requirements-notebook.txt`). Python 3.12. `requirements.txt` is what both Fargate images install, so the AI-evaluation deps (`strands-agents`, `pydantic`) live in `requirements-eval.txt`, pulled in by `requirements-dev.txt`.
- **CDK:** `swimtrends-app/.venv` ← its `requirements.txt`.

AWS: profile **`swimtrends`**, region **`eu-west-1`** (account is selected by the
profile — do not hardcode the account id in new files; this is a public repo).
Scraping and AWS commands need network + credentials.

## Common commands (run from the dir shown)
```bash
# Tests — always run before claiming done
cd st-scrape       && .venv/bin/python -m pytest -q        # app + analytics + ingestion + evaluation (316)
cd swimtrends-app  && .venv/bin/python -m pytest tests/unit # CDK assertions (64)
cd web             && npm test                              # SPA unit tests (52)

# Scrape one meet (writes db/<id>_*.jsonl locally)
cd st-scrape && .venv/bin/python scrape_races.py 12486 DM-L DMJ-L

# Regenerate the points base-times table (reads legacy CSV + wa-points/*.md)
cd st-scrape && .venv/bin/python gen_base_times.py   # -> db/point_base_times.jsonl

# CLI — operational (need REGISTRY_TABLE etc.; see docs/ingestion.md)
cd st-scrape && .venv/bin/python -m ingestion.cli register|dispatch|curate|class|pending …

# CLI — read-only analytics (need only AWS creds for S3)
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m ingestion.cli \
    query [--sql "…"] | meets [--category X] [--season Y] [--asc] | categories | summary

# AI meet evaluations. `make web-eval` (from the repo root) needs no exports —
# it resolves the model id + live guardrail version itself, unsets any inherited
# AWS_* keys, and checks the eval deps first. Run the module directly only for
# flags make doesn't pass, e.g. --dry-run (cache hits/misses, calls no model) —
# and then EVAL_MODEL_ID + EVAL_GUARDRAIL_ID/_VERSION are required in *every*
# mode: the guardrail is in the cache key, so without them a dry run reports
# every meet as a miss. See docs/analytics.md for the exports.
make web-eval
cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation \
    --out ../web/public/data --dry-run
```

## Deploying the CDK stacks (there are real gotchas)
```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22        # node 22, NOT the default
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
npx aws-cdk@2.1133.0 deploy SwimtrendsIngestionStack \
  --app ".venv/bin/python3 app.py" \
  -c alert_email=<your-address> \
  --require-approval never
```
- **Use `npx aws-cdk@2.1133.0`, not a bare `cdk`.** Node 22 is still required
  (`nvm use 22`) to run it, but node 22's global `cdk` is also stuck on
  2.1125.0, which can't read the cloud-assembly schema (54.0.0) that
  aws-cdk-lib 2.262.1+ emits.
- **`--app ".venv/bin/python3 app.py"`** — only the venv python has the CDK libs.
- **ALWAYS pass `-c alert_email=<address>`.** It is read from CDK context, not
  stored anywhere. Omitting it deletes the existing SNS email subscription, so
  alerts silently stop (applies to both `SwimtrendsIngestionStack` and
  `SwimtrendsCuratedStack`). A new SNS confirmation email is sent each time.
- **Docker must be running** (CDK builds the scraper image + Lambda bundle assets).
- **`SwimtrendsEvaluationStack`** (the AI-evaluation guardrail) takes **no**
  `alert_email` — it has no SNS topic, so there is nothing to drop. What it does
  have is the opposite trap: any policy change publishes a **new numbered
  guardrail version**, and the batch job pins a version from the environment. So
  after deploying it, re-read `EVAL_GUARDRAIL_ID`/`EVAL_GUARDRAIL_VERSION` from
  the stack outputs and re-export them (commands in
  [`docs/analytics.md`](docs/analytics.md)) — a stale export keeps serving the
  old policy. The version is also in the cache key, so the first run afterwards
  regenerates every meet.

## Domain conventions (curated column values)
- **stroke** is Danish: `Fri` free, `Ryg` back, `Bryst` breast, `Fly`,
  `IM` individual medley, `HM` team medley. (Mapped to WA `FREE/BACK/BREAST/FLY/MEDLEY`.)
- **course**: `LCM` (50 m) / `SCM` (25 m). **gender**: `M`/`F`/`X` (mixed relay).
- **season** = Danish season year. LCM meets → the year held; **SCM meets (held
  in December) map to the *next* year** (a Dec-2025 meet is season 2026).
- **points** = `trunc(1000 · (basetime/swimtime)³)`. `points` uses the meet's own
  season base times; `points_fixed` uses a frozen reference season (2026) for
  cross-era comparison. Para / DQ / timeless swims are not scored.
- **phase** (from race type): `Heats→heats`, `Final→final`, else `timed_final`.
- **para**: a `Timed final` ('Direkte finale') that duplicates an event also run
  as Heats/Final in the same meet → `class='para'`; else `open`. Override with
  `swimtrends class set`.
- **junior**: competition-season age 16-18 (`is_junior` on the `results` view).
  The junior title is decided from the *qualifying* swim (heats, or the timed
  final for 800/1500) — see `junior_championship`, never the senior final.
- **DSQ**: renders as a **7-column** row (rank cell `-`, `DSQ` in the time cell).
  The parser accepts `len(cells) >= 6` and maps a non-numeric rank to `-1`;
  curate excludes `rank == -1` from scoring. Don't reintroduce a `== 6` check.
- **Search indexing**: the SPA uses **real paths**, not hash routes (`/DM-L/12486`);
  old `#/c/…/m/…` links are redirected by `legacyPath()` in `web/src/router.js`.
  `npm run build` runs `prerender.mjs` after vite, writing 47 static shells (home,
  5 categories, 41 meets — meet prose comes from the AI evaluations) plus
  `sitemap.xml`. Three things are load-bearing:
  * It fetches the **live** `https://swimtrends.dk/data` because `web/public/data`
    is gitignored and CI has no local copy. A fetch failure **must** fail the
    build — `web-deploy` syncs `--delete`, so prerendering nothing would delete
    the good pages. Override the source with `SEO_DATA_BASE`.
  * `cloudfront/viewer_request.js` (viewer-request) is what makes those shells
    reachable: the S3 REST/OAC origin has no directory index, so without it every
    prerendered page 404s into the SPA fallback and silently serves the generic
    shell. It also 301s `www` to the apex — **`swimtrends.dk` is the one canonical
    host**, and the ACM cert's `www` SAN is what allows that alias, so removing
    the SAN breaks www. Its table tests run the real function body through `node`.
  * `main.js` clears `#app` before `mount()` — Svelte 5 `mount()` appends, so the
    static shell would otherwise remain under the hydrated app.
- **AI evaluations**: meet pages can carry a batch-generated Danish coach report
  (`evaluation/`). The model sees only the **digest** (`webbuild/digest.py`) and
  every number in the published text must exist in it (`evaluation/check.py`).
  Prose about a named swimmer is limited to results facts; juniors are minors.
  Four things are load-bearing and were each measured — **read
  [`docs/analytics.md`](docs/analytics.md) before touching `evaluation/`**:
  the explicit `ApplyGuardrail` call (`OutputGuard`) is the enforcement, not the
  guardrail on the Converse call; grounding runs **per section at 0.5**, not
  whole-report; `limits=LIMITS` must be passed on **every** `agent(...)` call
  (per-invocation, and an uncapped meet once cost ~$31); the cache key includes
  the prompt/schema version and guardrail version.

## Development conventions
- **TDD.** Write the failing test first, watch it fail, then implement. App tests
  live in `st-scrape/tests/`; analytics-view tests build an in-memory DuckDB via
  `tests/analytics_fixtures.build_curated` + `analytics.loader.create_views` (no
  S3). CDK tests are assertion tests in `swimtrends-app/tests/unit`.
- **Analytics views** are plain SQL in `st-scrape/analytics/views/*.sql`, loaded
  in filename order; they bind to `cur_obt`/`cur_dim_meet`/`cur_fact_split`.
  Prefer a view over baking derived policy into curate (junior status, etc.).
- Match surrounding style; keep changes minimal and focused. See
  [Workflow](#workflow) for the branch → PR → deploy loop.
- **CI covers infra too:** a new CDK stack or infrastructure change ships with a
  CI test in the *same* PR. Data-zone resources need an IAM **Deny** on delete
  actions.
- **Shell scripts:** when killing processes use a pattern that can't match the
  killing command itself (`pkill -f '[d]ev-server'`). In Playwright, prefer
  unambiguous locators (`getByRole` with exact names) over text substrings.

## Guardrails
- **Be polite to svømmetider.dk** (host `xn--svmmetider-1cb.dk`): single,
  **sequential** requests only — never parallelize scrapes. The scraper already
  paces itself (0.25 s delay, backoff on 415/429/5xx). Backfill one meet at a time.
- **Never deploy the CDK stacks without `-c alert_email`** (see above).
- **Web deploys are low-stakes — just do them when needed, no need to ask.** The
  live site (swimtrends.dk) is production but not critical. The **SPA deploys
  itself**: `.github/workflows/ci.yml` builds and publishes it on every merge to
  `master`, so app-only changes need no manual step. `make web-deploy` is the
  local fallback (Actions down, or an unmerged build must go live). **Data is
  never deployed by CI** — run `make web-refresh` when the curated zone moved or
  a change alters the generated JSON. Note: `web-refresh` is **slow (~50 min)** —
  `webbuild` reads the whole curated zone from S3 one race at a time and is
  **silent until the final `wrote N files`** (gauge progress by output-file
  mtimes, not the file count, which is stable across rebuilds). When only the
  AI reports changed, use **`make web-eval-deploy`** instead (seconds: it syncs
  just `*/evaluation.json`), and confirm with `make web-eval-verify`.
- Still confirm before other hard-to-reverse or outward-facing actions: **CDK
  stack deploys** (infra), raw-zone S3 overwrites, and force-dispatch of the
  whole registry.
