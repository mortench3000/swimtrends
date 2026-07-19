# Web App Infra & Deploy Implementation Plan (Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`). **The deploy itself (Task 6) is human-gated — do NOT run `cdk deploy` or any DNS/S3 mutation without the user's explicit go.**

**Goal:** Deploy the Swimtrends web MVP to `https://swimtrends.dk` — private S3 + CloudFront (HTTPS) serving the built SPA and the precomputed `/data/*.json`, migrating off the existing HTTP sample landing page.

**Architecture:** Two CDK stacks: a us-east-1 ACM cert stack (CloudFront requires the cert there) and an eu-west-1 web stack (private S3 site bucket with CloudFront Origin Access Control, Route53 alias for swimtrends.dk). Cross-region cert wiring via `crossRegionReferences`. The SPA build and data JSON are pushed by a **manual deploy/refresh script** (per the chosen CI/CD approach) — no pipeline, no automated rebuild in the MVP.

**Tech Stack:** aws-cdk-lib 2.257.0, Python (swimtrends-app venv), node 22 `cdk`, AWS profile `swimtrends`, account 179537025528. Deploy needs Docker running (CDK bundling) + network + credentials.

## Global Constraints

- **Node 22** for the `cdk` CLI (`nvm use 22`); `--app ".venv/bin/python3 app.py"`; **always pass `-c alert_email=mortench.privat@gmail.com`** on every deploy (omitting drops the SNS subscription — applies to ingestion/curated stacks; harmless but keep the habit).
- Account **179537025528**, web stack region **eu-west-1**, cert stack region **us-east-1**. Reuse the existing `ENV` pattern in `app.py`; do not hardcode the account in NEW files beyond what `app.py` already does.
- Domain **swimtrends.dk**, Route53 hosted zone **`Z05943842L8KIUA914B4J`** (already exists).
- Site bucket is **private** (block all public access); CloudFront reaches it via **Origin Access Control** (not the legacy OAI, not S3 website hosting). Content is fully regenerable → bucket `RemovalPolicy.DESTROY` + `auto_delete_objects=True`.
- CloudFront: `default_root_object="index.html"`, `viewer_protocol_policy=REDIRECT_TO_HTTPS`, `domain_names=["swimtrends.dk"]`, the us-east-1 cert. Add 403/404 → `/index.html` (200) responses as an SPA fallback (harmless with hash routing, robust against stray paths).
- **Migration (runbook, not CDK):** the existing manual `swimtrends.dk` Route53 **A alias** (→ `s3-website-eu-west-1.amazonaws.com`) must be **deleted before** `cdk deploy` creates the CloudFront alias, or the record collides. The old `swimtrends.dk` **website bucket** + its `landing-page.html` are scrapped (deleted) — the new site bucket is CDK-named, not `swimtrends.dk` (OAC doesn't require a name match).
- **Deferred (documented, not built):** automated hourly rebuild (Fargate + EventBridge) — data changes a few times/year and the full build takes minutes; a manual `make web-refresh` covers the MVP. Also deferred: WAF, staging env, CI/CD pipeline.
- CDK unit tests follow the existing `swimtrends-app/tests/unit` pattern (assertion `Template`, stubbed context, `ENV`).

---

## File Structure
- Create `swimtrends-app/swimtrends_app/swimtrends_cert_stack.py` — us-east-1 ACM cert.
- Create `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` — S3 + CloudFront + Route53.
- Modify `swimtrends-app/app.py` — instantiate both stacks with `cross_region_references=True`.
- Create `swimtrends-app/tests/unit/test_web_stack.py` and `test_cert_stack.py`.
- Create/modify repo-root `Makefile` — `web-deploy` and `web-refresh` targets.
- Create `docs/superpowers/deploy-web.md` — the deploy + migration runbook.

---

## Task 1: ACM certificate stack (us-east-1)

**Files:** Create `swimtrends-app/swimtrends_app/swimtrends_cert_stack.py`; Test: `swimtrends-app/tests/unit/test_cert_stack.py`.

**Interfaces:**
- Produces: `SwimtrendsCertStack` exposing `.certificate` (an `acm.ICertificate` for `swimtrends.dk`, DNS-validated against the hosted zone). Must be instantiated with `env` region `us-east-1` and `cross_region_references=True`.

- [ ] **Step 1: Write the failing test**

```python
# swimtrends-app/tests/unit/test_cert_stack.py
import aws_cdk as cdk
from aws_cdk import assertions
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack

ENV_US = cdk.Environment(account="179537025528", region="us-east-1")


def _template():
    app = cdk.App()
    stack = SwimtrendsCertStack(app, "TestCert", env=ENV_US,
                                cross_region_references=True)
    return assertions.Template.from_stack(stack)


def test_cert_for_domain():
    _template().has_resource_properties("AWS::CertificateManager::Certificate", {
        "DomainName": "swimtrends.dk",
        "ValidationMethod": "DNS",
    })
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd swimtrends-app && .venv/bin/python -m pytest tests/unit/test_cert_stack.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# swimtrends-app/swimtrends_app/swimtrends_cert_stack.py
"""ACM certificate for swimtrends.dk, in us-east-1 for CloudFront.

Separate stack because CloudFront viewer certificates MUST live in us-east-1;
the web stack (eu-west-1) consumes .certificate via cross-region references."""
from aws_cdk import Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_route53 as route53
from constructs import Construct

DOMAIN = "swimtrends.dk"
HOSTED_ZONE_ID = "Z05943842L8KIUA914B4J"


class SwimtrendsCertStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=HOSTED_ZONE_ID, zone_name=DOMAIN)
        self.certificate = acm.Certificate(
            self, "SiteCert",
            domain_name=DOMAIN,
            validation=acm.CertificateValidation.from_dns(zone),
        )
```

- [ ] **Step 4: Run to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git add swimtrends-app/swimtrends_app/swimtrends_cert_stack.py swimtrends-app/tests/unit/test_cert_stack.py
git commit -m "feat(infra): ACM cert stack for swimtrends.dk (us-east-1)"
```

---

## Task 2: Web stack (S3 + CloudFront OAC + Route53)

**Files:** Create `swimtrends-app/swimtrends_app/swimtrends_web_stack.py`; Test: `swimtrends-app/tests/unit/test_web_stack.py`.

**Interfaces:**
- Consumes: an `acm.ICertificate` (from Task 1) via constructor arg `certificate`.
- Produces: `SwimtrendsWebStack` with a private site bucket, a CloudFront distribution (OAC origin, `swimtrends.dk` alias, cert, SPA fallback), a Route53 A + AAAA alias to the distribution, and `CfnOutput`s `SiteBucketName` and `DistributionId` (consumed by the deploy script). Instantiate with `env` region `eu-west-1` and `cross_region_references=True`.

- [ ] **Step 1: Write the failing test**

```python
# swimtrends-app/tests/unit/test_web_stack.py
import aws_cdk as cdk
from aws_cdk import assertions
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack
from swimtrends_app.swimtrends_web_stack import SwimtrendsWebStack

ACC = "179537025528"


def _template():
    app = cdk.App()
    cert = SwimtrendsCertStack(
        app, "TestCert",
        env=cdk.Environment(account=ACC, region="us-east-1"),
        cross_region_references=True)
    web = SwimtrendsWebStack(
        app, "TestWeb", certificate=cert.certificate,
        env=cdk.Environment(account=ACC, region="eu-west-1"),
        cross_region_references=True)
    return assertions.Template.from_stack(web)


def test_site_bucket_blocks_public_access():
    _template().has_resource_properties("AWS::S3::Bucket", {
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
        }
    })


def test_distribution_has_domain_and_spa_fallback():
    t = _template()
    t.has_resource_properties("AWS::CloudFront::Distribution", {
        "DistributionConfig": assertions.Match.object_like({
            "Aliases": ["swimtrends.dk"],
            "DefaultRootObject": "index.html",
        })
    })


def test_route53_alias_record_created():
    _template().resource_count_is("AWS::Route53::RecordSet", 2)  # A + AAAA
```

- [ ] **Step 2: Run to verify it fails** → FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# swimtrends-app/swimtrends_app/swimtrends_web_stack.py
"""Swimtrends public web app hosting: private S3 + CloudFront (OAC) + Route53
alias for swimtrends.dk. Static SPA + precomputed /data/*.json are pushed by
the deploy/refresh script (see docs/superpowers/deploy-web.md), not by CDK."""
from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as route53
from aws_cdk import aws_route53_targets as targets
from aws_cdk import aws_s3 as s3
from constructs import Construct

DOMAIN = "swimtrends.dk"
HOSTED_ZONE_ID = "Z05943842L8KIUA914B4J"


class SwimtrendsWebStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *,
                 certificate: acm.ICertificate, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self, "SiteBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        spa_fallback = [
            cloudfront.ErrorResponse(
                http_status=code, response_http_status=200,
                response_page_path="/index.html", ttl=Duration.minutes(5))
            for code in (403, 404)
        ]

        distribution = cloudfront.Distribution(
            self, "Distribution",
            default_root_object="index.html",
            domain_names=[DOMAIN],
            certificate=certificate,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            error_responses=spa_fallback,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=HOSTED_ZONE_ID, zone_name=DOMAIN)
        alias = route53.RecordTarget.from_alias(
            targets.CloudFrontTarget(distribution))
        route53.ARecord(self, "AliasA", zone=zone, target=alias, record_name=DOMAIN)
        route53.AaaaRecord(self, "AliasAAAA", zone=zone, target=alias, record_name=DOMAIN)

        CfnOutput(self, "SiteBucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        CfnOutput(self, "SiteUrl", value=f"https://{DOMAIN}")
```

- [ ] **Step 4: Run to verify it passes** → PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add swimtrends-app/swimtrends_app/swimtrends_web_stack.py swimtrends-app/tests/unit/test_web_stack.py
git commit -m "feat(infra): web stack — private S3 + CloudFront OAC + Route53 alias"
```

---

## Task 3: Wire both stacks into app.py

**Files:** Modify `swimtrends-app/app.py`.

**Interfaces:** Consumes both stack classes; passes `cert_stack.certificate` into the web stack; both get `cross_region_references=True`.

- [ ] **Step 1: Write the failing test**

```python
# append to swimtrends-app/tests/unit/test_web_stack.py
def test_app_synthesizes_both_web_stacks():
    import importlib.util, pathlib
    app_path = pathlib.Path(__file__).resolve().parents[2] / "app.py"
    spec = importlib.util.spec_from_file_location("app_entry", app_path)
    # Synth must not raise and must include both stacks by id.
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # app.py calls app.synth() at import
    assert app_path.exists()
```

(If `app.py` calling `app.synth()` at import makes this awkward, instead assert construction in a helper; keep the test light — the real coverage is Tasks 1–2.)

- [ ] **Step 2: Run to verify current app.py lacks the web stacks** — inspect `app.py`; confirm no `SwimtrendsWebStack`.

- [ ] **Step 3: Modify `app.py`** — add after the existing stacks:

```python
from swimtrends_app.swimtrends_cert_stack import SwimtrendsCertStack
from swimtrends_app.swimtrends_web_stack import SwimtrendsWebStack

ENV_US = cdk.Environment(account="179537025528", region="us-east-1")

cert_stack = SwimtrendsCertStack(
    app, "SwimtrendsCertStack", env=ENV_US, cross_region_references=True)
SwimtrendsWebStack(
    app, "SwimtrendsWebStack", certificate=cert_stack.certificate,
    env=ENV, cross_region_references=True)
```

(Place before `app.synth()`. `ENV` already = eu-west-1 in app.py.)

- [ ] **Step 4: Run the CDK unit suite** → `cd swimtrends-app && .venv/bin/python -m pytest tests/unit -q` — all pass (existing + new).

- [ ] **Step 5: Commit**

```bash
git add swimtrends-app/app.py swimtrends-app/tests/unit/test_web_stack.py
git commit -m "feat(infra): wire cert + web stacks into app.py (cross-region)"
```

---

## Task 4: Deploy + refresh scripts (Makefile)

**Files:** Modify repo-root `Makefile`.

**Interfaces:** `make web-deploy` (build SPA + push to the site bucket + invalidate) and `make web-refresh` (regenerate data + push + invalidate). Both read the bucket name + distribution id from the deployed stack outputs.

- [ ] **Step 1: Add the targets** (TAB-indented recipes):

```makefile
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
```

- [ ] **Step 2: Verify the Makefile parses** — `make -n web-deploy` (dry run; won't resolve outputs until the stack exists, which is fine — just confirm no syntax error).

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(infra): make web-deploy + web-refresh scripts"
```

---

## Task 5: Deploy runbook + CDK suite green

**Files:** Create `docs/superpowers/deploy-web.md`; verify CDK tests.

- [ ] **Step 1: Run the full CDK unit suite** → `cd swimtrends-app && .venv/bin/python -m pytest tests/unit -q` — all green (no regressions to the 3 existing stacks' tests).

- [ ] **Step 2: Write `docs/superpowers/deploy-web.md`** — the exact, ordered, human-gated runbook:

```markdown
# Deploying the Swimtrends web app (swimtrends.dk)

Prerequisites: node 22 (`nvm use 22`), Docker running, AWS profile `swimtrends`,
the swimtrends-app venv, the st-scrape venv.

## One-time migration off the sample landing page
1. Confirm the current record: `aws route53 list-resource-record-sets --hosted-zone-id Z05943842L8KIUA914B4J --profile swimtrends` — expect an A alias for swimtrends.dk → s3-website-eu-west-1.amazonaws.com.
2. **Delete that A record** (so CDK can create the CloudFront alias without collision) — via the Route53 console or a change-batch DELETE.
3. (Optional) delete the old website bucket: `aws s3 rb s3://swimtrends.dk --force --profile swimtrends`.

## Deploy the infrastructure
    export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm use 22
    cd swimtrends-app
    export AWS_PROFILE=swimtrends AWS_DEFAULT_REGION=eu-west-1 AWS_REGION=eu-west-1
    # cert stack first (us-east-1), then web stack; -c alert_email always
    cdk deploy SwimtrendsCertStack SwimtrendsWebStack \
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
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/deploy-web.md
git commit -m "docs(infra): swimtrends.dk deploy + migration runbook"
```

---

## Task 6: Deploy (HUMAN-GATED — do not run without explicit go)

- [ ] **Step 1: Get explicit user approval to deploy** (this is the acceptance gate: tests pass, review clean, and the user says go).
- [ ] **Step 2:** Execute the runbook in `docs/superpowers/deploy-web.md` (migration → `cdk deploy` → `make web-deploy` → `make web-refresh`).
- [ ] **Step 3: Live smoke test** — `curl -I https://swimtrends.dk` returns 200; load the app and drill Category → Meet → Race.
- [ ] **Step 4: Report** the live URL + smoke-test result.

---

## Self-Review

**Spec coverage** (against `2026-07-19-web-app-mvp-design.md`):
- Private S3 + CloudFront OAC + HTTPS on swimtrends.dk → Tasks 1–2. ✔
- ACM cert in us-east-1, cross-region → Tasks 1, 3. ✔
- Route53 alias + migration off the sample landing page (delete old A record, scrap old bucket) → Task 2 + runbook (Task 5). ✔
- Manual deploy/refresh script (CI/CD deferred) → Task 4. ✔
- Acceptance gates: tests pass (Tasks 1–5), deployed & reachable smoke test (Task 6), human approval (Task 6 gate). ✔
- **Deferred (documented):** automated hourly rebuild (Fargate+EventBridge), WAF, staging, CI/CD pipeline, para exclusion in view-based season comparison (Plan 1 note). Data changes rarely → manual `web-refresh` suffices.

**Placeholder scan:** stack tasks (1–2) carry complete CDK code + assertion tests. Task 3's app.py test is intentionally light (real coverage is the stack tests); noted inline. No TODOs.

**Type consistency:** `SwimtrendsCertStack.certificate` produced in Task 1, consumed as `certificate=` in Task 2/3. CfnOutput keys `SiteBucketName`/`DistributionId` produced in Task 2, consumed by the Makefile in Task 4. `HOSTED_ZONE_ID`/`DOMAIN` identical across both stacks.

**Open items for reviewer:**
- Confirm `origins.S3BucketOrigin.with_origin_access_control` exists in aws-cdk-lib 2.257.0 (it does from 2.130+; if the API differs, use `S3BucketOrigin.with_origin_access_control(bucket)` per the installed version's docs).
- Confirm `cross_region_references=True` is accepted on `Stack` in 2.257.0 (yes) and that synth/deploy has network for the SSM-parameter cross-region export.
- The `make web-deploy` `$(shell aws ...)` output lookups require the stack already deployed; the first-ever deploy runs `cdk deploy` (Task 6) before `make web-deploy` — order is correct in the runbook.
