# web-dev: generate data from the curated zone, then serve the SPA locally
web-dev:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	cd web && npm run dev
