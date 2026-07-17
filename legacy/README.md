# Legacy (deprecated)

The original Swimtrends pipeline: a Scrapy spider writing into a local
PostgreSQL database, plus assorted scripts. **Superseded** by the AWS platform
in [`../st-scrape`](../st-scrape) (scraper + curate + analytics + ingestion) and
[`../swimtrends-app`](../swimtrends-app) (CDK infrastructure). Kept for reference
and history; not maintained.

## Contents
- `swimtrends/` — Scrapy project (`spiders/meetresults.py` reads `urls.txt`;
  `pipelines.py` writes to PostgreSQL). Run from this folder so `scrapy.cfg` and
  `urls.txt` resolve.
- `scrapy.cfg` — Scrapy config (`default = swimtrends.settings`).
- `urls/`, `urls.txt` — meet-result URL lists fed to the spider.
- `pgdckr/` — PostgreSQL + pgAdmin docker-compose, schema, SQL snippets, and the
  World-Aquatics base-times CSV (`data/Points_Table_Base_Times.csv`).
- `ag-rank.py`, `post-process.py` — one-off PostgreSQL post-processing scripts.
- `calc_points.py` — original WA-points calculator, ported to
  `../st-scrape/curate/points.py`.

## Still referenced by the new code
`data/Points_Table_Base_Times.csv` is read by
[`../st-scrape/gen_base_times.py`](../st-scrape/gen_base_times.py) to fill the
older seasons (2008-2021) of the points base-time table. Don't delete it without
updating that script.
