# Swimtrends Web App

A modern, data-driven SPA for exploring Danish competitive swimming results and trends.

## Prerequisites

- **Node.js 22** — managed via nvm:
  ```bash
  nvm use 22
  ```
- **Python 3.12 venv** (`st-scrape/.venv`) — for the `webbuild` data generator

## Installation

```bash
cd web
npm install
```

## Local Development

Generate data from the curated zone and run the dev server:

```bash
make web-dev
```

This command:
1. Runs `python -m webbuild --out web/public/data` from `st-scrape` to build JSON from S3 curated data.
2. Starts the Vite dev server at `http://localhost:5173`.

Navigate to a category (e.g., `DM-L`), pick a meet, then a race to explore meet facts, podium, and seasonal trends.

### Offline Mode (Fixtures)

To develop without AWS credentials, build data from test fixtures instead:

```bash
cd st-scrape
AWS_PROFILE=swimtrends .venv/bin/python -c "
from tests.analytics_fixtures import build_curated
from analytics.loader import create_views
from webbuild.build import build_all
from pathlib import Path
import duckdb

con = duckdb.connect()
build_curated(con)
create_views(con)
build_all(con, Path('../web/public/data'))
"
cd ../web && npm run dev
```

Fixture data is shaped like production but carries a small test dataset (2 meets, 2 seasons). See `tests/fixtures/` for the schema.

## Production Build

Build and preview the static bundle:

```bash
npm run build && npm run preview
```

Outputs to `dist/`. Production deploy to swimtrends.dk is Plan 3 (not this task).

## Testing

Run the test suite (12 tests on components and data layers):

```bash
npm run test
```

## Tech Stack

- **Svelte 5** — reactive components
- **Vite** — build tool + dev server
- **Observable Plot** — charting for seasonal trends
- **DuckDB** (Python) — curated zone querying for data generation
- **Vitest** — testing
- **Inter font** — modern UI typography

## Attribution

Data from [svømmetider.dk](https://xn--svmmetider-1cb.dk/).
