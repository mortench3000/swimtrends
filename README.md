# Swimtrends

Analytics of data and trends in Danish competitive swimming.

Meet results are scraped from svømmetider.dk into a raw zone on S3, transformed
into a curated Parquet zone (with World Aquatics points and open/para/junior
classification), and queried locally with DuckDB.

## Repository layout

| Path | What |
| --- | --- |
| [`st-scrape/`](st-scrape) | The application: the scraper (`scrape_races.py`), the curated transform (`curate/`), the analytics views + CLI (`analytics/`, `ingestion/cli.py`), and the ingestion control plane (`ingestion/`). Tests in `st-scrape/tests`. |
| [`swimtrends-app/`](swimtrends-app) | AWS CDK infrastructure (S3, DynamoDB registry, dispatcher/curate Lambdas, Fargate tasks, SNS, Glue). CDK assertion tests in `swimtrends-app/tests`. |
| [`docs/`](docs) | [`analytics.md`](docs/analytics.md) (querying the curated zone) and [`ingestion.md`](docs/ingestion.md) (operational CLI). Design specs/plans under `docs/superpowers/`. |
| [`legacy/`](legacy) | The original Scrapy → PostgreSQL pipeline and Docker setup. Deprecated; kept for reference — see [`legacy/README.md`](legacy/README.md). |

## Getting started
- **Analyse the data:** see [`docs/analytics.md`](docs/analytics.md).
- **Operate the pipeline** (register meets, dispatch scrapes, curate): see
  [`docs/ingestion.md`](docs/ingestion.md) and
  [`st-scrape/README-ingestion.md`](st-scrape/README-ingestion.md).
