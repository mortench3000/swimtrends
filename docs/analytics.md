# Analytics (Spec 3): local DuckDB over the curated zone

Read-only ad-hoc analysis of the curated Parquet, straight from S3. For the
operational side — registering meets, triggering scrapes/curation, class
overrides, `pending` — see [ingestion.md](ingestion.md).

## Prerequisites
- `pip install -r st-scrape/requirements.txt` (provides `duckdb`).
- AWS credentials for the `swimtrends` profile (eu-west-1). `loader.connect()`
  defaults `AWS_PROFILE` to `swimtrends`, so the credential-chain secret resolves
  your `~/.aws/credentials` automatically (override by exporting `AWS_PROFILE`).
  First run downloads the `httpfs`/`aws` extensions.

## Interactive REPL
```bash
cd st-scrape
swimtrends query
```
`con` is the DuckDB connection; `sql("…")` prints a result. All views are loaded.

One-shot (how fast you had to swim to make the 200 breaststroke final at DM-L,
per season):
```bash
swimtrends query --sql "SELECT season, gender, cutline_time FROM final_cutline_by_season \
  WHERE category='DM-L' AND distance=200 AND stroke='Bryst' ORDER BY season, gender"
```

### More example queries
```bash
# Junior championship top 5 — 100m Fly women, 2026 (ranked on the qualifying swim)
swimtrends query --sql "SELECT junior_rank, name, completed_time FROM junior_championship \
  WHERE season=2026 AND distance=100 AND stroke='Fly' AND gender='F' ORDER BY junior_rank LIMIT 5"

# One swimmer's medals across every championship
swimtrends query --sql "SELECT category, gold, silver, bronze FROM medal_count \
  WHERE swimmer_id='26884' ORDER BY gold DESC"

# Which DM-L meets a swimmer has competed in
swimtrends query --sql "SELECT season, meet_name, swims FROM swimmer_meets \
  WHERE swimmer_id='26884' AND category='DM-L' ORDER BY season"

# All-time 100m Freestyle (SCM) top 10 by best time, with WA points
swimtrends query --sql "SELECT name, best_time, points FROM personal_best \
  WHERE stroke='Fri' AND distance=100 AND course='SCM' ORDER BY best_centiseconds LIMIT 10"

# How an event standard moved across seasons (best + top-3-avg + top-8-avg, centiseconds)
swimtrends query --sql "SELECT season, gender, best_cs, top3_avg_cs, top8_avg_cs \
  FROM event_standard_by_season WHERE category='DM-L' AND distance=100 AND stroke='Fly' ORDER BY season, gender"
```
Column values are Danish: stroke `Fri`/`Ryg`/`Bryst`/`Fly`/`IM`, course `LCM`/`SCM`,
gender `M`/`F` (see Vocabulary below). SCM seasons are the *next* year — a
December 2025 meet is season 2026.

## Data overview (what's in the zone)
Top-level, read-only catalog queries — no SQL needed:
```bash
swimtrends summary                       # totals: meets, results, swimmers, seasons, categories
swimtrends categories                    # per-category coverage: meets, season span, results
swimtrends meets                         # every meet, sorted by season, with race/result/DSQ counts
swimtrends meets --category DM-K         # filter by category
swimtrends meets --season 2026           # filter by season (filters compose)
```
`races` = distinct races, `results` = result rows, `dsq` = disqualifications
(rank -1). Like `query`, these need only AWS credentials for S3.

## From a notebook / Python
```python
from analytics import loader
con = loader.connect()
con.sql("SELECT * FROM event_standard_by_season WHERE category='DM-L'")
```

### Jupyter in VS Code
A ready-to-run starter notebook lives at `st-scrape/notebooks/explore.ipynb`
(coverage overview, best times, the final cut-line trend, and event-standard
plots — all using the real view columns).

One-time setup:
1. Install the analyst tooling into the venv:
   `cd st-scrape && .venv/bin/pip install -r requirements-notebook.txt`
   (adds `ipykernel`, `pandas`, `matplotlib`).
2. Register the venv as a Jupyter kernel (so VS Code lists it by name):
   `.venv/bin/python -m ipykernel install --user --name swimtrends --display-name "Swimtrends (st-scrape)"`
3. Install the VS Code **Python** + **Jupyter** extensions if you haven't.

Then open `explore.ipynb` and pick the **Swimtrends (st-scrape)** kernel
(top-right). The workspace `.vscode/settings.json` points the default
interpreter at `st-scrape/.venv` and sets the notebook working dir to
`st-scrape/`. The notebook's first cell also self-locates the `analytics`
package, so it runs even if launched from elsewhere. `con.sql(...)` returns a
DuckDB result; the `q(...)` helper returns a pandas DataFrame for tables/plots.

## Web JSON build
Generate the static JSON the web app serves (reads the curated zone from S3):

    cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data

Output mirrors the app's URL layout (index.json, <category>/meets.json,
<category>/<meet_id>/{meet,races}.json, <category>/<meet_id>/<race_key>.json).

## View catalog
- **Best times / ranking:** `personal_best`, `season_best`, `event_leaderboard`
- **Progression:** `swimmer_progression`, `biggest_improvers`, `cross_era_best`,
  `swimmer_meets` (which meets a `swimmer_id` competed in, per category),
  `medal_count` (gold/silver/bronze finals finishes per swimmer, per category)
- **Aggregates:** `club_leaderboard`, `age_group_ranking`, `meet_summary`
- **Pacing:** `pacing`
- **Juniors:** `junior_championship` (junior title standings per DMJ-L event).
  A swim is junior when competition-season age is 16-18 (`is_junior` on
  `results`, a floor *and* a ceiling — sub-16 qualifiers at a senior meet are
  too young for the title; the band slides by season, e.g. 2026 → born
  2008-2010). The title is decided from the **qualifying** swim, so
  `junior_championship` ranks juniors by their heats (or timed-final, for
  800/1500) time — never the senior final, which most juniors never reach.
  `junior_rank` 1/2/3 = gold/silver/bronze. e.g. `SELECT * FROM
  junior_championship WHERE season=2026 AND distance=100 AND stroke='Fly'
  AND gender='M' ORDER BY junior_rank`.
- **Field evolution:** `event_standard_by_season`, `final_cutline_by_season`,
  `cutline_at(n)` (cut-line for an arbitrary final size), `results_by_category`,
  `prelim_ranked`. `final_cutline_by_season` / `cutline_at(n)` expose an
  `entrants` column (the prelim field size) so you can tell a well-defined
  cut-line (`entrants >= n`) from a thin field. An event swum as a *timed final*
  (no heats — common for small fields) has no prelim, so it is **absent** from
  these views entirely; use `event_standard_by_season` for an unbroken trend.

Base views: `results` (1 row per result, with
`age`/`is_junior`/`phase`/`is_relay`/`is_dq`) and `individual_results` (real
individual swims only).

## Vocabulary (curated column values)
- **stroke** is Danish: `Fri` (free), `Ryg` (back), `Bryst` (breast), `Fly`,
  `IM` / `HM` (individual/team medley).
- **course**: `LCM` (50 m) / `SCM` (25 m). **gender**: `M` / `F`.
- **phase** (derived from race `type`): `heats`, `final`, `timed_final`.
- **category**: meet qualifier — `DM-L`, `DMJ-L`, `DO`, … (the championship key).

## Notes
- New meets are queryable the moment they are curated — no refresh step.
- `category` (DM-L, DMJ-L, …) is meet-level; a meet in two categories pools into
  both in the field-evolution views.

## AI meet evaluations

Each meet page can carry a short Danish coach-style evaluation, generated
offline and cached. `make web-eval` fills the cache and writes
`web/public/data/<cat>/<meet>/evaluation.json`; `make web-refresh` runs it
between `webbuild` and the S3 sync.

Config (all three required; the guardrail values come from the
`SwimtrendsEvaluationStack` outputs):

```bash
export EVAL_MODEL_ID=<bedrock model id>
export EVAL_GUARDRAIL_ID=<guardrail id>
export EVAL_GUARDRAIL_VERSION=<numbered version, never DRAFT>
```

Useful flags:

- `--dry-run` — report cache hits and misses without calling the model.
- `--meets DM-L/12486` — one meet (or a comma-separated list).
- `--force` — regenerate and overwrite the cached text. This is the revoke
  switch; the bucket is versioned, so the prior text is retained.

The cache key is `sha256(digest + prompt_version + schema_version + model_id)`.
Unchanged inputs reuse the stored text verbatim — bumping `PROMPT_VERSION` or
`SCHEMA_VERSION` in `evaluation/agent.py`, or switching models, regenerates
every meet on the next run.

Every number in a published evaluation is checked against the digest
(`evaluation/check.py`); a report that fails twice is dropped and the page
renders without the section.

A meet that fails during `web-eval` (digest error, a bad AI report, a
transient S3 error) gets no `evaluation.json`; the `--delete` sync that
follows then removes that meet's section from the live site until a later
run succeeds — the page falls back to rendering without it, same as any
other skip. If **every** meet fails — wrong `EVAL_MODEL_ID`, a revoked
guardrail, expired credentials — `web-eval` exits non-zero on purpose, so
`make` stops before the sync runs and no already-published evaluation is
deleted.
