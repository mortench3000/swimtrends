# Analytics (Spec 3): local DuckDB over the curated zone

Read-only ad-hoc analysis of the curated Parquet, straight from S3.

## Prerequisites
- `pip install -r st-scrape/requirements.txt` (provides `duckdb`).
- AWS credentials for the `swimtrends` profile (eu-west-1); DuckDB reads S3 via a
  credential-chain secret. First run downloads the `httpfs`/`aws` extensions.

## Interactive REPL
```bash
cd st-scrape
swimtrends query
```
`con` is the DuckDB connection; `sql("…")` prints a result. All views are loaded.

One-shot:
```bash
swimtrends query --sql "SELECT * FROM final_cutline_by_season \
  WHERE category='DM-L' AND distance=200 AND stroke='Breast' ORDER BY season"
```

## From a notebook / Python
```python
from analytics import loader
con = loader.connect()
con.sql("SELECT * FROM event_standard_by_season WHERE category='DM-L'")
```

## View catalog
- **Best times / ranking:** `personal_best`, `season_best`, `event_leaderboard`
- **Progression:** `swimmer_progression`, `biggest_improvers`, `cross_era_best`
- **Aggregates:** `club_leaderboard`, `age_group_ranking`, `meet_summary`
- **Pacing:** `pacing`
- **Field evolution:** `event_standard_by_season`, `final_cutline_by_season`,
  `cutline_at(n)` (cut-line for an arbitrary final size), `results_by_category`,
  `prelim_ranked`

Base views: `results` (1 row per result, with `age`/`phase`/`is_relay`/`is_dq`)
and `individual_results` (real individual swims only).

## Notes
- New meets are queryable the moment they are curated — no refresh step.
- `category` (DM-L, DMJ-L, …) is meet-level; a meet in two categories pools into
  both in the field-evolution views.
