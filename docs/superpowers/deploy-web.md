# Deploying the Swimtrends web app (swimtrends.dk)

Prerequisites: node 22 (`nvm use 22`), Docker running, AWS profile `swimtrends`,
the swimtrends-app venv, the st-scrape venv.

## The app deploy is automated

`.github/workflows/ci.yml` runs on every push to `master`: it runs the
`st-scrape` pytest suite and the `web` vitest suite, then builds the SPA and runs
`make web-deploy AWS_PROFILE_FLAG=` (S3 sync of `web/dist`, CloudFront
invalidation of `/*`). It authenticates with GitHub OIDC by assuming the deploy
role from `SwimtrendsWebStack`; the role ARN lives in the GitHub repo variable
`AWS_DEPLOY_ROLE_ARN` (not in the tree — it contains the account id). Only
`master`-branch runs can assume it, so PR runs never touch AWS.

CI does **not** touch `/data/*.json`. The manual commands below remain the
fallback for the app, and the only way to refresh data.

## One-time: bootstrap us-east-1 (the cert stack lives there)
Only eu-west-1 was bootstrapped originally; the ACM cert stack is us-east-1
(CloudFront requirement), so bootstrap that region once. Pass `--app` with the
venv python — `cdk bootstrap` otherwise uses cdk.json's `python3 app.py`
(system python, no aws_cdk) and fails:

    cd swimtrends-app
    export AWS_PROFILE=swimtrends
    npx aws-cdk@2.1133.0 bootstrap aws://179537025528/us-east-1 \
      --app ".venv/bin/python3 app.py"

## One-time migration off the sample landing page
1. Confirm the current record: `aws route53 list-resource-record-sets --hosted-zone-id Z05943842L8KIUA914B4J --profile swimtrends` — expect an A alias for swimtrends.dk → s3-website-eu-west-1.amazonaws.com.
2. **Delete that A record** (so CDK can create the CloudFront alias without collision) — via the Route53 console or a change-batch DELETE.
3. (Optional) delete the old website bucket: `aws s3 rb s3://swimtrends.dk --force --profile swimtrends`.

## Deploy the infrastructure
    export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
    cd swimtrends-app
    export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
    # cert stack first (us-east-1), then web stack; -c alert_email always
    npx aws-cdk@2.1133.0 deploy SwimtrendsCertStack SwimtrendsWebStack \
      --app ".venv/bin/python3 app.py" -c alert_email=mortench.privat@gmail.com \
      --require-approval never
- ACM DNS validation auto-creates a CNAME in the zone and may take a few minutes.

## Publish the app + data
    make web-deploy    # build SPA -> S3 -> invalidate
    make web-refresh   # generate data -> S3 /data/ -> invalidate

## Verify (acceptance)
- `curl -I https://swimtrends.dk` → 200, HTTPS.
- Browser: swimtrends.dk loads; pick a category → meet → race; charts + Danish render.

## Refresh cadence
Run `make web-refresh` after new meets are curated (manual for the MVP; automation deferred).
