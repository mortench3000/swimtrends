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
