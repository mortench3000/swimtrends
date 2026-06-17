FROM python:3.12-slim

# Stream stdout/stderr unbuffered so CloudWatch shows scrape progress live
# (otherwise Python block-buffers output and logs only appear in bursts).
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Scraper (single source of truth) + ingestion package.
COPY scrape_races.py .
COPY ingestion/ ./ingestion/

# The entrypoint reads MEET_ID / CATEGORIES / RAW_BUCKET / REGISTRY_TABLE /
# SNS_TOPIC_ARN from the environment (set by the task def + RunTask overrides).
ENTRYPOINT ["python", "-m", "ingestion.scrape_task"]
