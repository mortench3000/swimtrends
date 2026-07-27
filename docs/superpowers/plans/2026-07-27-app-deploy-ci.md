# App-Deploy CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Actions runs both test suites on every PR and deploys the SPA to
S3 + CloudFront on every merge to `master`, using OIDC instead of stored keys.

**Architecture:** A GitHub OIDC provider and a deploy role scoped to
`repo:mortench3000/swimtrends:ref:refs/heads/master` are added to the existing
`SwimtrendsWebStack`, where the site bucket and distribution constructs already
live (no cross-stack references needed). One workflow file runs tests on
`pull_request` and, on `push` to `master`, assumes that role and runs the
existing `make web-deploy` target. The Makefile gains an `AWS_PROFILE_FLAG`
variable so the same recipe works with a local named profile and with
environment credentials in CI.

**Tech Stack:** aws-cdk-lib 2.262.1 (upgraded from 2.257.0) with Python in
`swimtrends-app/.venv`; GNU make; GitHub Actions (`actions/checkout@v4`,
`actions/setup-python@v5`, `actions/setup-node@v4`,
`aws-actions/configure-aws-credentials@v4`); pytest + moto in
`st-scrape/.venv`; vitest in `web/`.

## Global Constraints

- Spec: [`docs/superpowers/specs/2026-07-27-app-deploy-ci-design.md`](../specs/2026-07-27-app-deploy-ci-design.md).
- **Never hardcode the AWS account id in a new file** — this repo is public. The
  deploy role ARN therefore lives in the GitHub repo variable
  `AWS_DEPLOY_ROLE_ARN`, referenced as `${{ vars.AWS_DEPLOY_ROLE_ARN }}`.
- Region is `eu-west-1`; local AWS profile is `swimtrends`.
- CDK commands need node 22 and the venv python:
  `export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22` then
  `--app ".venv/bin/python3 app.py"`. Docker must be running (asset bundling).
- **Any `cdk deploy` or `cdk diff` must pass `-c alert_email=<address>`** —
  omitting it drops the SNS email subscription and the cost-budget notification.
- **No CDK stack is deployed by an implementation task.** Task 5 gates the one
  required deploy on explicit human approval.
- Data refresh (`make web-refresh`, ~50 min) is out of scope and stays manual.
- TDD: write the failing test, watch it fail, then implement.
- Work on branch `app-deploy-ci` (already created; the spec commits are on it).

---

## File Structure

| File | Responsibility |
| --- | --- |
| `swimtrends-app/requirements.txt` | Modify — bump `aws-cdk-lib` pin |
| `CLAUDE.md` | Modify — CDK CLI pin; post-merge deploy guardrail |
| `docs/superpowers/deploy-web.md` | Modify — CDK CLI pin; CI is now the deploy path |
| `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` | Modify — OIDC provider, deploy role, role-ARN output |
| `swimtrends-app/tests/unit/test_web_stack.py` | Modify — assertions for the above |
| `Makefile` | Modify — `AWS_PROFILE_FLAG` variable |
| `.github/workflows/ci.yml` | Create — the only workflow |

---

### Task 1: Upgrade aws-cdk-lib to 2.262.1

Do this first and alone, so library-induced template churn can never be confused
with a change the new deploy role caused.

**Files:**
- Modify: `swimtrends-app/requirements.txt:1`
- Modify: `CLAUDE.md:73`
- Modify: `docs/superpowers/deploy-web.md:14`

**Interfaces:**
- Consumes: nothing.
- Produces: `aws-cdk-lib==2.262.1` installed in `swimtrends-app/.venv`. Task 2
  relies on `aws_cdk.aws_iam.CfnOIDCProvider` (native `AWS::IAM::OIDCProvider`)
  being available there — it is, having shipped well before 2.257.0.

**Context the implementer needs:** the breaking changes between 2.258.0 and
2.262.1 are in classic ElasticLoadBalancing, CloudWatch `LogAlarm`, Lambda
`Runtime.NODEJS_LATEST` (→ Node 24), EKS AL2023 and PCA connector L1s. None are
used by this repo — every Lambda here pins `lambda_.Runtime.PYTHON_3_12`. Two
non-breaking changes *will* show up in `cdk diff`: 2.261.0 adds git source
metadata to every synthesized template, and 2.262.0 turned on default synth-time
template validation (2.262.1 fixed `CDK_VALIDATION=false` not disabling it).

- [ ] **Step 1: Bump the pin**

In `swimtrends-app/requirements.txt` change the first line:

```
aws-cdk-lib==2.262.1
```

- [ ] **Step 2: Install it**

```bash
cd swimtrends-app && .venv/bin/pip install -r requirements.txt
```

Then confirm what landed:

```bash
cd swimtrends-app && .venv/bin/pip show aws-cdk-lib | head -2
```

Expected: `Version: 2.262.1`.

- [ ] **Step 3: Run the existing CDK assertion suite**

```bash
cd swimtrends-app && .venv/bin/python -m pytest tests/unit
```

Expected: PASS, same count as before the bump. This suite is the regression
gate for the upgrade — there is no new behaviour to test-drive here.

If anything fails, **stop and report it**. Do not edit stack code to make an
upgrade failure go away without saying so; that is a finding, not a chore.

- [ ] **Step 4: Run the st-scrape suite too**

```bash
cd st-scrape && .venv/bin/python -m pytest -q
```

Expected: PASS (134). It shares no dependency with CDK; this is a cheap baseline
so later tasks know a failure is theirs.

- [ ] **Step 5: Review `cdk diff` on all five stacks**

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk diff --app ".venv/bin/python3 app.py" -c alert_email=<your-address> 2>&1 | tee /tmp/cdk-diff-upgrade.txt
```

(No stack name diffs all of them. Docker must be running.)

Expected: `Metadata` / `CDKMetadata` churn only. **Any diff that touches a
resource property is a stop-and-report** — write down which stack and which
property rather than deploying through it.

- [ ] **Step 6: Bump the documented CLI pin**

Latest `aws-cdk` CLI is 2.1133.0. In `CLAUDE.md` line 73 and
`docs/superpowers/deploy-web.md` line 14, change `npx aws-cdk@2.1125.0` to
`npx aws-cdk@2.1133.0`. Documentation only — nothing executes these strings.

- [ ] **Step 7: Commit**

```bash
git add swimtrends-app/requirements.txt CLAUDE.md docs/superpowers/deploy-web.md
git commit -m "chore(cdk): upgrade aws-cdk-lib to 2.262.1, document CLI 2.1133.0"
```

---

### Task 2: OIDC provider + scoped deploy role in the web stack

**Files:**
- Modify: `swimtrends-app/swimtrends_app/swimtrends_web_stack.py`
- Test: `swimtrends-app/tests/unit/test_web_stack.py`

**Interfaces:**
- Consumes: `aws-cdk-lib==2.262.1` from Task 1.
- Produces: a CloudFormation output named exactly **`GitHubDeployRoleArn`** on
  `SwimtrendsWebStack`. Task 5 reads that output's value into the GitHub repo
  variable `AWS_DEPLOY_ROLE_ARN`. No Python symbol is exported.

**Context the implementer needs:** `swimtrends_web_stack.py` already builds
`bucket` (the site bucket) and `distribution` (the CloudFront distribution) as
local variables in `SwimtrendsWebStack.__init__`, and ends with three
`CfnOutput`s. `aws_iam` is **not** yet imported there. Use the L1
`iam.CfnOIDCProvider`, not the L2 `iam.OpenIdConnectProvider` — the L2 synths a
custom resource with its own Lambda, while the L1 is the native
`AWS::IAM::OIDCProvider` and needs no thumbprint list (verified by synthesizing
it, 2026-07-27).

The `sub` condition is the security boundary: only workflow runs on `master` of
this repo can assume the role. PR runs never request credentials at all.

- [ ] **Step 1: Write the failing tests**

Append to `swimtrends-app/tests/unit/test_web_stack.py` (the module already
imports `assertions` and defines the `_template()` helper):

```python
def test_github_oidc_provider_created():
    _template().has_resource_properties("AWS::IAM::OIDCProvider", {
        "Url": "https://token.actions.githubusercontent.com",
        "ClientIdList": ["sts.amazonaws.com"],
    })


def test_deploy_role_trusts_only_master_of_this_repo():
    _template().has_resource_properties("AWS::IAM::Role", {
        "AssumeRolePolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "sts:AssumeRoleWithWebIdentity",
                    "Condition": {
                        "StringEquals": {
                            "token.actions.githubusercontent.com:aud":
                                "sts.amazonaws.com",
                        },
                        "StringLike": {
                            "token.actions.githubusercontent.com:sub":
                                "repo:mortench3000/swimtrends:ref:refs/heads/master",
                        },
                    },
                }),
            ]),
        }),
    })


def test_deploy_role_invalidation_is_scoped_to_the_distribution():
    _template().has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "cloudfront:CreateInvalidation",
                    "Resource": assertions.Match.not_("*"),
                }),
            ]),
        }),
    })


def test_deploy_role_can_read_this_stacks_outputs():
    _template().has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": assertions.Match.object_like({
            "Statement": assertions.Match.array_with([
                assertions.Match.object_like({
                    "Action": "cloudformation:DescribeStacks",
                    "Resource": {"Ref": "AWS::StackId"},
                }),
            ]),
        }),
    })


def test_deploy_role_arn_is_an_output():
    assert "GitHubDeployRoleArn" in _template().find_outputs("*")
```

- [ ] **Step 2: Run them to verify they fail**

```bash
cd swimtrends-app && .venv/bin/python -m pytest tests/unit/test_web_stack.py -v
```

Expected: the five new tests FAIL (no `AWS::IAM::OIDCProvider` in the template,
no matching role/policy, no such output). The pre-existing tests in the file
still PASS.

- [ ] **Step 3: Implement it**

In `swimtrends_web_stack.py`, add to the imports:

```python
from aws_cdk import aws_iam as iam
```

Add beside the existing module constants:

```python
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_REPO = "mortench3000/swimtrends"
```

Insert after the `distribution` is created and before the `CfnOutput`s (it needs
both `bucket` and `distribution`):

```python
        # GitHub Actions deploys the SPA on merge to master. OIDC, so no
        # long-lived access keys live in GitHub. The sub condition is the
        # security boundary: only master-branch runs of this repo can assume
        # the role — a fork's PR cannot, and PR runs never ask for credentials.
        oidc = iam.CfnOIDCProvider(
            self, "GitHubOidcProvider",
            url=GITHUB_OIDC_URL,
            client_id_list=["sts.amazonaws.com"],
        )
        issuer = GITHUB_OIDC_URL.removeprefix("https://")
        deploy_role = iam.Role(
            self, "GitHubDeployRole",
            assumed_by=iam.FederatedPrincipal(
                oidc.attr_arn,
                conditions={
                    "StringEquals": {f"{issuer}:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        f"{issuer}:sub": f"repo:{GITHUB_REPO}:ref:refs/heads/master"},
                },
                assume_role_action="sts:AssumeRoleWithWebIdentity",
            ),
            description="GitHub Actions: build + publish the SPA to the site bucket",
        )
        # `aws s3 sync --delete` needs list, put and delete on the bucket.
        bucket.grant_read_write(deploy_role)
        deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudfront:CreateInvalidation"],
            resources=[distribution.distribution_arn],
        ))
        # The Makefile resolves the bucket name and distribution id from this
        # stack's outputs at deploy time, so CI needs to read them.
        deploy_role.add_to_policy(iam.PolicyStatement(
            actions=["cloudformation:DescribeStacks"],
            resources=[self.stack_id],
        ))
```

Add alongside the existing outputs at the end of `__init__`:

```python
        CfnOutput(self, "GitHubDeployRoleArn", value=deploy_role.role_arn)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd swimtrends-app && .venv/bin/python -m pytest tests/unit -v
```

Expected: PASS, including the five new tests and every pre-existing one
(`test_app_synthesizes_both_web_stacks` synthesizes the real `app.py`, so it
catches a construct-level mistake too).

- [ ] **Step 5: Commit**

```bash
git add swimtrends-app/swimtrends_app/swimtrends_web_stack.py \
        swimtrends-app/tests/unit/test_web_stack.py
git commit -m "feat(infra): GitHub OIDC provider + scoped SPA deploy role"
```

---

### Task 3: Make the AWS profile flag overridable

**Files:**
- Modify: `Makefile` (the `WEB_BUCKET` and `WEB_DIST` definitions and the
  `web-deploy` recipe)

**Interfaces:**
- Consumes: nothing.
- Produces: the make variable **`AWS_PROFILE_FLAG`**, default
  `--profile swimtrends`. Task 4's workflow overrides it with
  `make web-deploy AWS_PROFILE_FLAG=`; a command-line assignment overrides a
  `?=` default in GNU make, so the flag disappears entirely and the AWS CLI
  falls back to environment credentials.

**Context the implementer needs:** `web-refresh` is deliberately **left
untouched**. Its `AWS_PROFILE=swimtrends` environment variable for `webbuild` is
a different problem (an empty `AWS_PROFILE` is not equivalent to an absent one)
and belongs to the separate data-refresh piece.

- [ ] **Step 1: Write the failing check**

There is no test framework for the Makefile; `make -n` prints the recipe without
running it, which is enough. Run the check first and watch it fail:

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
make -n web-deploy AWS_PROFILE_FLAG= 2>/dev/null | grep -c -- --profile
```

Expected now: `2` (the `s3 sync` and `create-invalidation` lines both carry a
hardcoded `--profile swimtrends`). The target state is `0`.

Note: `make -n` still executes the `$(shell aws cloudformation describe-stacks…)`
lookups, so this needs AWS credentials and prints stderr noise — `2>/dev/null`
handles the noise.

- [ ] **Step 2: Add the variable and substitute it**

In `Makefile`, add above the `WEB_BUCKET` definition:

```make
# Local runs use the named profile; CI assumes a role and passes this empty
# (`make web-deploy AWS_PROFILE_FLAG=`), so the CLI uses env credentials.
AWS_PROFILE_FLAG ?= --profile swimtrends
```

Then replace `--profile swimtrends` with `$(AWS_PROFILE_FLAG)` in exactly four
places — both `describe-stacks` lookups and both `web-deploy` commands:

```make
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
```

Leave `web-dev`, `web-refresh` and `web-release` exactly as they are.

- [ ] **Step 3: Run the check both ways**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
make -n web-deploy AWS_PROFILE_FLAG= 2>/dev/null | grep -c -- --profile   # expect 0
make -n web-deploy 2>/dev/null | grep -c -- "--profile swimtrends"        # expect 2
make -n web-refresh 2>/dev/null | grep -c -- "--profile swimtrends"       # expect 2
```

Expected: `0`, `2`, `2`. The first proves CI gets a profile-free recipe; the
second and third prove local behaviour is unchanged for both targets.

- [ ] **Step 4: Commit**

```bash
git add Makefile
git commit -m "chore(make): allow overriding the AWS profile flag for CI"
```

---

### Task 4: The CI workflow, plus the docs that describe it

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `CLAUDE.md` (the Guardrails bullet about web deploys)
- Modify: `docs/superpowers/deploy-web.md`

**Interfaces:**
- Consumes: `AWS_PROFILE_FLAG` from Task 3; the repo variable
  `AWS_DEPLOY_ROLE_ARN`, which does not exist yet — Task 5 creates it from the
  output added in Task 2. Until then the deploy step cannot succeed, which is
  fine: it only runs on `master`.
- Produces: the workflow. Nothing consumes it.

**Context the implementer needs:** `st-scrape`'s suite is moto-backed and needs
neither network nor AWS credentials, so it runs unauthenticated in CI. The CDK
assertion suite is deliberately **not** run in CI — it would need a second
virtualenv plus CDK's Node toolchain in the runner, for little gain on a repo
where infra deploys are manual. `make web-deploy` runs `npm ci` again after the
test step already did; that costs ~20 s and keeps the Makefile the single source
of truth for the deploy commands, so leave it.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [master]

permissions:
  id-token: write   # mint the OIDC token
  contents: read

# Two master pushes must not run overlapping s3 syncs. Not cancel-in-progress:
# a half-finished sync is worse than a queued one.
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: false

jobs:
  test-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: pip
          cache-dependency-path: st-scrape/requirements-dev.txt

      - name: Install Python deps
        run: pip install -r requirements-dev.txt
        working-directory: st-scrape

      # moto-backed: no network, no AWS credentials needed.
      - name: st-scrape tests
        run: python -m pytest -q
        working-directory: st-scrape

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: web/package-lock.json

      - name: Install web deps
        run: npm ci
        working-directory: web

      - name: web tests
        run: npm test
        working-directory: web

      - name: Assume the deploy role
        if: github.ref == 'refs/heads/master'
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_DEPLOY_ROLE_ARN }}
          aws-region: eu-west-1

      # Data (/data/*.json) is NOT touched here — see the spec.
      - name: Deploy the SPA
        if: github.ref == 'refs/heads/master'
        run: make web-deploy AWS_PROFILE_FLAG=
```

- [ ] **Step 2: Check it parses**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
st-scrape/.venv/bin/python -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); \
print(sorted(d['jobs']['test-and-deploy']['steps'][-1].keys())); \
print(len(d['jobs']['test-and-deploy']['steps']), 'steps')"
```

Expected: `['if', 'name', 'run']` and `9 steps`. This only catches YAML
mistakes; the workflow's real test path is exercised by its own PR check run in
Task 5.

Note the YAML gotcha if you edited the file: `on:` parses as the boolean key
`True` in YAML 1.1, so index by `d[True]` if you need to inspect triggers.

- [ ] **Step 3: Update the CLAUDE.md guardrail**

Replace the Guardrails bullet at `CLAUDE.md:121-128` (currently "**Web deploys
are low-stakes …**", telling the reader to run `make web-release` after a merge)
with:

```markdown
- **Web deploys are low-stakes — just do them when needed, no need to ask.** The
  live site (swimtrends.dk) is production but not critical. The **SPA deploys
  itself**: `.github/workflows/ci.yml` builds and publishes it on every merge to
  `master`, so app-only changes need no manual step. `make web-deploy` is the
  local fallback (Actions down, or an unmerged build must go live). **Data is
  never deployed by CI** — run `make web-refresh` when the curated zone moved or
  a change alters the generated JSON. Note: `web-refresh` is **slow (~50 min)** —
  `webbuild` reads the whole curated zone from S3 one race at a time and is
  **silent until the final `wrote N files`** (gauge progress by output-file
  mtimes, not the file count, which is stable across rebuilds).
```

Then replace the Development-conventions "Workflow" bullet at `CLAUDE.md:111-114`
with:

```markdown
- **Workflow:** when implementation is complete and tests pass, push the branch
  and open a PR (squash-merge to master, matching history — don't commit to
  master directly). Merging deploys the SPA automatically; afterwards run
  `make web-refresh` only if the data needs it (see Guardrails).
```

- [ ] **Step 4: Update `docs/superpowers/deploy-web.md`**

Insert this immediately after the document's title/intro, before the existing
manual instructions:

```markdown
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
```

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml CLAUDE.md docs/superpowers/deploy-web.md
git commit -m "ci: test on PR, deploy the SPA on merge to master"
```

---

### Task 5: Deploy the role, wire up the variable, verify end to end

This task contains the only irreversible actions in the plan. **Each gate below
requires explicit human approval before proceeding** — do not run the deploy or
open the PR on your own initiative.

**Files:** none changed (unless verification finds a bug).

**Interfaces:**
- Consumes: the `GitHubDeployRoleArn` output from Task 2, the workflow from
  Task 4.
- Produces: a working automated deploy.

- [ ] **Step 1: Confirm everything is green locally**

```bash
cd swimtrends-app && .venv/bin/python -m pytest tests/unit
cd ../st-scrape && .venv/bin/python -m pytest -q
cd ../web && npm test
```

Expected: all PASS. Report the actual counts.

- [ ] **Step 2: Show the deploy diff, then STOP and ask**

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk diff SwimtrendsWebStack --app ".venv/bin/python3 app.py" -c alert_email=<your-address>
```

Expected: an added `AWS::IAM::OIDCProvider`, an added `AWS::IAM::Role` + policy,
one added output, plus the metadata churn from Task 1. Paste it and **ask for
approval to deploy** — this is an infra deploy touching the live distribution's
stack.

- [ ] **Step 3: Deploy `SwimtrendsWebStack` (after approval)**

```bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
cd swimtrends-app
export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
cdk deploy SwimtrendsWebStack --app ".venv/bin/python3 app.py" \
  -c alert_email=<your-address> --require-approval never
```

Docker must be running. A new SNS confirmation email will be sent — expected.

- [ ] **Step 4: Read the role ARN and set the repo variable**

```bash
aws cloudformation describe-stacks --stack-name SwimtrendsWebStack \
  --query "Stacks[0].Outputs[?OutputKey=='GitHubDeployRoleArn'].OutputValue" \
  --output text --profile swimtrends --region eu-west-1
```

Then, with that value:

```bash
gh variable set AWS_DEPLOY_ROLE_ARN --body "<the-arn>"
gh variable list
```

A variable, not a secret: it needs no masking, only to stay out of a public
tree. **Do not paste the ARN into any file** — it contains the account id.

- [ ] **Step 5: Push the branch and open the PR (after approval)**

```bash
git push -u origin app-deploy-ci
gh pr create --title "ci: deploy the SPA on merge to master" --body "<summary>"
```

The PR's own check run is the verification of the workflow's test path. Confirm
it goes green **and** that it did not attempt to assume the role (the two deploy
steps must show as skipped):

```bash
gh pr checks
gh run view --log | grep -iE "Assume the deploy role|Deploy the SPA"
```

- [ ] **Step 6: Merge, then verify the deploy path**

Squash-merge (matching history), then:

```bash
gh run watch
```

Expected: green, with the deploy steps executed this time. Then confirm the site
actually serves the new bundle:

```bash
curl -sI https://swimtrends.dk | head -3
curl -s https://swimtrends.dk | grep -o 'assets/[^"]*\.js'
```

Expected: `HTTP/2 200`, and the asset filename matches the hash in the local
`web/dist/index.html` from the CI build. If the deploy step failed, fall back to
`make web-deploy` locally and report what went wrong — master is merged and the
site keeps serving the previous bundle until then.

- [ ] **Step 7: Report**

State plainly: test counts, what the `cdk diff` showed, whether the PR run and
the master run were green, and whether the live site serves the new bundle. If
any step was skipped, say which and why.

---

## Notes

- If Task 1's `cdk diff` shows resource-property churn in any stack, that is a
  finding to report, not something to fix inside this plan.
- `workflow_dispatch` was deliberately left out (YAGNI). Add it the first time an
  app-only redeploy is wanted without a commit.
- The two follow-on pieces — incremental `webbuild`, then automated data refresh
  — each get their own spec and plan. See
  [`docs/superpowers/2026-07-25-ci-deploy-evaluation.md`](../2026-07-25-ci-deploy-evaluation.md).
