# web-dev: generate data from the curated zone, then serve the SPA locally
web-dev:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	cd web && npm run dev

# Local runs use the named profile; CI assumes a role and passes this empty
# (`make web-deploy AWS_PROFILE_FLAG=`), so the CLI uses env credentials.
AWS_PROFILE_FLAG ?= --profile swimtrends

# Resolve stack outputs (needs AWS creds; stack must be deployed)
WEB_BUCKET = $(shell aws cloudformation describe-stacks --stack-name SwimtrendsWebStack \
	--query "Stacks[0].Outputs[?OutputKey=='SiteBucketName'].OutputValue" --output text \
	$(AWS_PROFILE_FLAG) --region eu-west-1)
WEB_DIST = $(shell aws cloudformation describe-stacks --stack-name SwimtrendsWebStack \
	--query "Stacks[0].Outputs[?OutputKey=='DistributionId'].OutputValue" --output text \
	$(AWS_PROFILE_FLAG) --region eu-west-1)

# Build the SPA and push it (keeps /data/ intact via --exclude)
web-deploy:
	cd web && npm ci && npm run build
	aws s3 sync web/dist s3://$(WEB_BUCKET)/ --delete --exclude "data/*" $(AWS_PROFILE_FLAG)
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/*" $(AWS_PROFILE_FLAG)

# Regenerate the data JSON from the curated zone, add AI evaluations, and push.
# The EVAL_* preconditions are checked up front: webbuild takes ~50 minutes and
# web-eval would otherwise be the first thing to notice an un-exported shell,
# losing the whole rebuild. web-eval must stay immediately before the
# `--delete` sync so its non-zero exit still stops the publish.
web-refresh:
	@: $${EVAL_MODEL_ID:?set EVAL_MODEL_ID (see docs/analytics.md)}
	@: $${EVAL_GUARDRAIL_ID:?set EVAL_GUARDRAIL_ID (SwimtrendsEvaluationStack output)}
	@: $${EVAL_GUARDRAIL_VERSION:?set EVAL_GUARDRAIL_VERSION (numbered, never DRAFT)}
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m webbuild --out ../web/public/data
	$(MAKE) web-eval
	aws s3 sync web/public/data s3://$(WEB_BUCKET)/data/ --delete --profile swimtrends
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/data/*" --profile swimtrends

# Fill the evaluation cache and emit evaluation.json (seconds on a cache hit).
# Needs EVAL_MODEL_ID, EVAL_GUARDRAIL_ID, EVAL_GUARDRAIL_VERSION in the
# environment — see docs/analytics.md. Does NOT sync; web-refresh does that.
web-eval:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation --out ../web/public/data

# Full web release: run the SPA unit tests, then build+deploy the app, then
# refresh the data. Stops at the first failure. (webbuild breakage surfaces in
# web-refresh; st-scrape's pytest suite is not run here — run it directly with
# `cd st-scrape && .venv/bin/python -m pytest -q`.)
web-release:
	cd web && npm test
	$(MAKE) web-deploy
	$(MAKE) web-refresh


# Compare candidate models on the same meets. Hand-run; reaches Bedrock.
# e.g. make eval-models MEETS=DM-L/12486,DM-L/11902 MODELS=id1,id2
eval-models:
	cd st-scrape && AWS_PROFILE=swimtrends .venv/bin/python -m evaluation.compare \
		--meets $(MEETS) --models $(MODELS)

.PHONY: web-dev web-deploy web-refresh web-eval web-release eval-models
