# Run a python entry point as the swimtrends profile. The `env -u` is load-bearing:
# exported AWS_ACCESS_KEY_ID/SECRET/SESSION_TOKEN outrank AWS_PROFILE in both the
# boto and DuckDB credential chains, so a shell holding another account's creds
# gets 403 on the curated zone no matter what AWS_PROFILE says.
ST_PYTHON = env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
	AWS_PROFILE=swimtrends .venv/bin/python

# web-dev: generate data from the curated zone, then serve the SPA locally
web-dev:
	cd st-scrape && $(ST_PYTHON) -m webbuild --out ../web/public/data
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

# Evaluation config. Read live from the deployed stack rather than a shell export
# that goes stale: every policy change publishes a NEW numbered guardrail version,
# and the version is in the cache key. `?=` so a deliberate export still wins
# (comparing an old version, say). See docs/analytics.md.
EVAL_MODEL_ID ?= eu.anthropic.claude-haiku-4-5-20251001-v1:0
EVAL_GUARDRAIL_ID ?= $(shell aws cloudformation describe-stacks \
	--stack-name SwimtrendsEvaluationStack $(AWS_PROFILE_FLAG) --region eu-west-1 \
	--query "Stacks[0].Outputs[?OutputKey=='GuardrailId'].OutputValue" --output text)
EVAL_GUARDRAIL_VERSION ?= $(shell aws cloudformation describe-stacks \
	--stack-name SwimtrendsEvaluationStack $(AWS_PROFILE_FLAG) --region eu-west-1 \
	--query "Stacks[0].Outputs[?OutputKey=='GuardrailVersion'].OutputValue" --output text)
EVAL_ENV = EVAL_MODEL_ID=$(EVAL_MODEL_ID) EVAL_GUARDRAIL_ID=$(EVAL_GUARDRAIL_ID) \
	EVAL_GUARDRAIL_VERSION=$(EVAL_GUARDRAIL_VERSION)

# Preconditions for anything that calls the evaluation batch. Checked up front
# in web-refresh too: webbuild takes ~50 minutes and web-eval would otherwise be
# the first thing to notice a bad config, losing the whole rebuild.
eval-preflight:
	@: $(if $(EVAL_GUARDRAIL_ID),,$(error EVAL_GUARDRAIL_ID empty — is SwimtrendsEvaluationStack deployed and are AWS creds valid?))
	@: $(if $(filter DRAFT,$(EVAL_GUARDRAIL_VERSION)),$(error EVAL_GUARDRAIL_VERSION is DRAFT — needs a numbered version),)
	@st-scrape/.venv/bin/python -c "import strands, pydantic" 2>/dev/null || { \
	  echo "st-scrape/.venv lacks the eval deps — run:"; \
	  echo "  cd st-scrape && .venv/bin/pip install -r requirements-dev.txt"; exit 1; }

# Regenerate the data JSON from the curated zone, add AI evaluations, and push.
# web-eval must stay immediately before the `--delete` sync so its non-zero exit
# still stops the publish.
web-refresh: eval-preflight
	cd st-scrape && $(ST_PYTHON) -m webbuild --out ../web/public/data
	$(MAKE) web-eval
	aws s3 sync web/public/data s3://$(WEB_BUCKET)/data/ --delete --profile swimtrends
	aws cloudfront create-invalidation --distribution-id $(WEB_DIST) --paths "/data/*" --profile swimtrends

# Fill the evaluation cache and emit evaluation.json (seconds on a cache hit).
# Needs no exports — EVAL_* above resolve the model + live guardrail version.
# Does NOT sync; web-refresh does that.
web-eval: eval-preflight
	cd st-scrape && $(EVAL_ENV) $(ST_PYTHON) -m evaluation --out ../web/public/data

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
eval-models: eval-preflight
	cd st-scrape && $(EVAL_ENV) $(ST_PYTHON) -m evaluation.compare \
		--meets $(MEETS) --models $(MODELS)

.PHONY: web-dev web-deploy web-refresh eval-preflight web-eval web-release eval-models
