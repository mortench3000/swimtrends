# Analytics (Spec 3): local DuckDB over the curated zone

Read-only ad-hoc analysis of the curated Parquet, straight from S3.

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

## View catalog
- **Best times / ranking:** `personal_best`, `season_best`, `event_leaderboard`
- **Progression:** `swimmer_progression`, `biggest_improvers`, `cross_era_best`,
  `swimmer_meets` (which meets a `swimmer_id` competed in, per category),
  `medal_count` (gold/silver/bronze finals finishes per swimmer, per category)
- **Aggregates:** `club_leaderboard`, `age_group_ranking`, `meet_summary`
- **Pacing:** `pacing`
- **Field evolution:** `event_standard_by_season`, `final_cutline_by_season`,
  `cutline_at(n)` (cut-line for an arbitrary final size), `results_by_category`,
  `prelim_ranked`. `final_cutline_by_season` / `cutline_at(n)` expose an
  `entrants` column (the prelim field size) so you can tell a well-defined
  cut-line (`entrants >= n`) from a thin field. An event swum as a *timed final*
  (no heats — common for small fields) has no prelim, so it is **absent** from
  these views entirely; use `event_standard_by_season` for an unbroken trend.

Base views: `results` (1 row per result, with `age`/`phase`/`is_relay`/`is_dq`)
and `individual_results` (real individual swims only).

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
