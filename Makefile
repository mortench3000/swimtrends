# web-dev: generate data from the curated zone, then serve the SPA locally
web-dev:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	cd web && npm run dev

# Resolve stack outputs (needs AWS creds; stack must be deployed)
WEB_BUCKET = $(shell aws cloudformation describe-stacks --stack-name SwimtrendsWebStack \
	--query "Stacks[0].Outputs[?OutputKey=='SiteBucketName'].OutputValue" --output text \
	--profile swimtrends --region eu-west-1)
WEB_DIST = $(shell aws cloudformation describe-stacks --stack-name SwimtrendsWebStack \
	--query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text \
	--profile swimtrends --region eu-west-1)

# Build the SPA and push it (keeps /data/ intact via --exclude)
web-deploy:
	cd web && npm ci && npm run build
	aws s3 sync web/dist s3://$(WEB_BUCKET)/ --delete --exclude "data/*" --profile swimtrends
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/*" --profile swimtrends

# Regenerate the data JSON from the curated zone and push it
web-refresh:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	aws s3 sync web/public/data s3://$(WEB_BUCKET)/data/ --delete --profile swimtrends
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/data/*" --profile swimtrends

# Full web release: run the SPA unit tests, then build+deploy the app, then
# refresh the data. Stops at the first failure. (webbuild breakage surfaces in
# web-refresh; st-scrape's pytest suite is not run here — use `make test`.)
web-release:
	cd web && npm test
	$(MAKE) web-deploy
	$(MAKE) web-refresh

.PHONY: web-dev web-deploy web-refresh web-release
