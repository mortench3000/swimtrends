# App-deploy CI — design

**Date:** 2026-07-27
**Status:** Approved design, not yet implemented.
**Scope:** Piece 1 of [`2026-07-25-ci-deploy-evaluation.md`](../2026-07-25-ci-deploy-evaluation.md)
— GitHub Actions runs the test suites on every PR and deploys the SPA on merge
to `master`. Data refresh stays manual.

## Problem

There is no CI. Tests are run by hand, and after each merge the SPA is deployed
by hand with `make web-deploy` from a dev machine holding the `swimtrends` AWS
profile. Two costs: a broken PR is only discovered when someone remembers to run
the tests, and a merged PR is only live when someone remembers to deploy.

The 50-minute data build (`make web-refresh`) is deliberately **out of scope** —
it tracks the hourly ingestion cycle, not merges. See the evaluation doc for why,
and for the two follow-on pieces (incremental webbuild, automated data refresh).

## Non-goals

- Automating the data refresh, on any trigger.
- Making `webbuild` incremental.
- A `workflow_dispatch` button. Add it when an app-only redeploy is actually
  wanted without a commit.
- Deploying the CDK stacks from CI. Infra deploys stay manual and confirmed.
- Deploying the other four stacks to land the `aws-cdk-lib` upgrade. They pick it
  up whenever they are next deployed; `cdk diff` is reviewed for all five, but
  only `SwimtrendsWebStack` is deployed here.
- Removing the local deploy path. `make web-deploy` remains the escape hatch.

## Architecture

Three changed surfaces:

| Surface | Change |
| --- | --- |
| `swimtrends-app/requirements.txt` | `aws-cdk-lib` 2.257.0 → 2.262.1 |
| `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` | GitHub OIDC provider + scoped deploy role, role-ARN output |
| `.github/workflows/ci.yml` | new; tests on PR, tests + deploy on push to `master` |
| `Makefile` | `AWS_PROFILE_FLAG` variable so CI can run `web-deploy` credential-free |

```
PR opened ──> ci.yml (test job)              ── no AWS credentials
merge     ──> ci.yml (test job, then deploy) ── OIDC ──> assume GitHubDeployRole
                                                          └─ make web-deploy
                                                               ├─ npm ci && npm run build
                                                               ├─ aws s3 sync web/dist  (--exclude "data/*")
                                                               └─ aws cloudfront create-invalidation "/*"
```

### 0. Upgrade aws-cdk-lib first

Pinned **2.257.0**, latest **2.262.1**. Do the upgrade as the first commit on the
branch, before writing any new CDK code, so an upgrade-induced template change
can never be confused with a change the deploy role caused.

Release notes for 2.258.0 → 2.262.1 reviewed (2026-07-27). The breaking changes
in that range are all in constructs this repo does not use: classic
ElasticLoadBalancing (`Id` → `LoadBalancerName`), CloudWatch `LogAlarm`
(`QueryLanguage` removed), Lambda `Runtime.NODEJS_LATEST` (now Node 24 — every
Lambda here pins `PYTHON_3_12`), EKS AL2023, and PCA connector L1s. Two changes
*will* show up when synthesizing:

- **2.261.0** adds git source metadata to synthesized templates. Expect a
  `Metadata` diff on **every** stack, unrelated to any code change.
- **2.262.0** validates templates against a default rule set at synth time, and
  2.262.1 fixed `CDK_VALIDATION=false` not disabling it. New warnings or errors
  may surface on stacks that synthesized cleanly before.

Also relevant but not required: `aws-cdk` **CLI** latest is 2.1133.0 (CLAUDE.md
and `docs/superpowers/deploy-web.md` document 2.1125.0). Bump those two
references in the same commit — documentation only, nothing executes it.

Verification for this step, before writing any new code:

1. `pip install -r requirements.txt` in `swimtrends-app/.venv`.
2. `.venv/bin/python -m pytest tests/unit` — the existing CDK assertion suite
   must stay green.
3. `cdk diff` (node 22, `--app ".venv/bin/python3 app.py"`, `-c alert_email=…`)
   on **all five stacks** and read the output. Metadata-only churn is expected
   and fine. Anything touching a resource property is a stop-and-look — report
   it rather than deploying through it.

No stack is deployed in this step. The upgrade rides along with the web-stack
deploy in Sequencing below; the other four stacks pick up the new library
version whenever they are next deployed for their own reasons.

### 1. AWS identity (CDK)

Defined in `SwimtrendsWebStack`, where the `bucket` and `distribution`
constructs already exist — scoping needs no cross-stack references.

- `iam.CfnOIDCProvider` for `https://token.actions.githubusercontent.com`,
  client id `sts.amazonaws.com`. Use the L1 construct, not `OpenIdConnectProvider`
  — the L2 synths a custom resource with its own Lambda, while the L1 is the
  native `AWS::IAM::OIDCProvider` (verified present in 2.257.0, so it is also in
  2.262.1). The account currently has **no** OIDC provider (verified
  2026-07-27), so creating one will not collide.
- `iam.Role` (`GitHubDeployRole`) with a `FederatedPrincipal` on that provider's
  ARN, conditioned on:
  - `StringEquals` — `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com`
  - `StringLike` — `token.actions.githubusercontent.com:sub` =
    `repo:mortench3000/swimtrends:ref:refs/heads/master`

  The `sub` condition is the security boundary: only workflow runs on the
  `master` branch of this repo can assume the role. A fork's PR cannot, and
  neither can a PR run on this repo — the test job never requests credentials.
- Permissions:
  - `bucket.grant_read_write(role)` — `s3 sync --delete` needs list, put and
    delete on the site bucket.
  - `cloudfront:CreateInvalidation` on the distribution ARN only.
  - `cloudformation:DescribeStacks` on this stack's ARN, so the Makefile's
    output lookup for bucket name and distribution id works unchanged in CI.
- The repo slug is a module constant beside `DOMAIN` and `HOSTED_ZONE_ID`. It is
  public information; no account id is added (this repo is public).
- New `CfnOutput`: `GitHubDeployRoleArn`.

### 2. Workflow

`.github/workflows/ci.yml` — a single file with a single job.

- Triggers: `pull_request` and `push` to `master`.
- `permissions: { id-token: write, contents: read }` — `id-token` is what lets
  the runner mint the OIDC token.
- `concurrency: { group: ci-${{ github.ref }}, cancel-in-progress: false }` —
  two master pushes in quick succession must not run overlapping `s3 sync`
  operations. Not cancel-in-progress: a half-finished sync is worse than a
  queued one.
- Steps, in order:
  1. `actions/checkout`
  2. `actions/setup-python` 3.12, pip cache → `pip install -r st-scrape/requirements-dev.txt`
  3. `pytest -q` in `st-scrape`. The suite is `moto`-backed and needs neither
     network nor AWS credentials.
  4. `actions/setup-node` 22, npm cache → `npm ci` in `web`
  5. `npm test` (vitest) in `web`
  6. **master only** (`if: github.ref == 'refs/heads/master'`):
     `aws-actions/configure-aws-credentials@v4` with
     `role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}` and region `eu-west-1`,
     then `make web-deploy AWS_PROFILE_FLAG=`.
- One job, not parallel test jobs: the deploy needs `npm ci` anyway, so
  splitting buys a minute at the cost of artifact passing between jobs.
- The CDK assertion suite (`swimtrends-app/tests/unit`) is **not** run — it
  needs a second virtualenv and CDK's Node toolchain in the runner for little
  gain on a repo where infra deploys are manual. Revisit if a CDK regression
  ever reaches master.

### 3. Makefile

`AWS_PROFILE_FLAG ?= --profile swimtrends`, substituted into the two
`describe-stacks` lookups and `web-deploy`'s `s3 sync` and `create-invalidation`
calls. CI overrides it to empty (`make web-deploy AWS_PROFILE_FLAG=`) and the
assumed-role credentials come from the environment. Local behaviour is
unchanged.

`web-refresh` is left alone. Its `AWS_PROFILE=swimtrends` environment variable
for `webbuild` is a different shape of problem (an empty `AWS_PROFILE` is not
equivalent to an absent one) and belongs to the data-refresh piece.

## Error handling

- Any test failure fails the job before the deploy steps run: master is then
  merged but undeployed, which is the correct failure mode — the site keeps
  serving the last good bundle. Fix forward with another PR, or deploy locally.
- A failure mid-`s3 sync` leaves the bucket partially updated. Acceptable: the
  bundle is small, CloudFront still serves cached objects for the invalidation
  window, and re-running the workflow (or `make web-deploy` locally) is
  idempotent.
- If the role or OIDC provider is missing, `configure-aws-credentials` fails
  with a clear assume-role error — no silent skip.

## Testing

- **CDK assertion test** in `swimtrends-app/tests/unit/test_web_stack.py`
  (TDD — written first, watched fail):
  - an `AWS::IAM::OIDCProvider` for the GitHub issuer exists,
  - the role's trust policy `sub` condition is exactly
    `repo:mortench3000/swimtrends:ref:refs/heads/master`,
  - the role's policy allows `cloudfront:CreateInvalidation` scoped to the
    distribution (not `*`),
  - `GitHubDeployRoleArn` is an output.
- **The workflow YAML has no unit test.** Its test path is exercised by the
  implementing PR's own check run; its deploy path is verified once, on merge,
  by confirming the workflow is green and the site serves the new bundle.
  Fallback if the deploy step is wrong: `make web-deploy` locally.

## Sequencing

The role must exist before the first master run of the workflow:

1. Upgrade `aws-cdk-lib` and verify per section 0 (CDK suite green, `cdk diff`
   reviewed on all five stacks). Separate commit.
2. Implement the other three surfaces on the same branch; CDK test green, both
   test suites green.
3. **Deploy `SwimtrendsWebStack`** with `-c alert_email=<address>` (manual, and
   confirmed first — it is an infra deploy that touches the live distribution,
   and it carries the library upgrade). Note the role ARN from the output.
4. Store the role ARN as the GitHub **repo variable** `AWS_DEPLOY_ROLE_ARN` and
   reference it as `${{ vars.AWS_DEPLOY_ROLE_ARN }}`. Not inline: the ARN
   contains the account id, and CLAUDE.md forbids hardcoding it in new files
   because this repo is public. A variable (not a secret) — it needs no masking,
   only to stay out of the tree.
5. Open the PR. Its check run proves the test path.
6. Merge. Watch the run; confirm the deploy path.

## Documentation

- `CLAUDE.md` guardrail: the app now deploys itself on merge to master. The
  post-merge manual step becomes `make web-refresh` only when the curated zone
  moved; `make web-release` is no longer the default.
- `docs/superpowers/deploy-web.md`: same, plus how to re-run or fall back.
- Both files' pinned `npx aws-cdk@2.1125.0` → `2.1133.0` (part of the upgrade
  commit).
