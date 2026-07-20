# Web App Auto-Refresh Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`). Deploy (Task 6) is **human-gated**.

**Goal:** Automatically rebuild and publish the web app's `/data/*.json` when new meets are curated — event-driven, on Fargate, dispatched the way the rest of the pipeline already is (`ecs run-task`), with a CLI command for manual/backfill runs and a single-flight guard so bursts don't spawn overlapping rebuilds.

**Architecture:** A new Fargate task (reusing the curate image — it already carries `st-scrape` + DuckDB + boto3) runs a `webbuild.refresh` entrypoint: build JSON → publish to the site bucket's `data/` prefix (put changed, delete stale) → CloudFront invalidation. It is triggered by the S3 write of the **last** curated dataset per meet (`curated/obt_result/…`) via a small dispatcher Lambda, exactly mirroring the existing `CurateTrigger`. A single-flight guard (one running refresh at a time + a "pending" marker) coalesces the 5-writes-per-meet and backfill bursts. `python -m ingestion.cli web-refresh` dispatches the same task manually.

**Tech Stack:** aws-cdk-lib 2.257.0, Python (st-scrape venv + swimtrends-app venv), the existing `swimtrends-ingestion` ECS cluster, `swimtrends-meet-data` bucket, boto3. Reuses `Dockerfile.curate`.

## Why this shape (design rationale, agreed)
- **Event-driven, not hourly.** Data changes a few times/year; a timer would rebuild the whole site 24×/day for nothing. Trigger off curate-completion so it runs exactly when data changed.
- **Reuse the dispatch pattern.** The pipeline already does S3-event → Lambda → `ecs run-task` (CurateTrigger) and has a CLI. This is the same play, not new machinery.
- **Fargate, not Lambda.** The build is minutes-long (and grew with the elite query); Lambda's 15-min cap is a real risk. Fargate has no timeout.
- **YAGNI note:** `make web-refresh` already covers manual publishing. Build this only if manual runs are proving annoying. If built, the single-flight guard (Task 3) is the part that must not be skipped.

## Global Constraints
- Reuse the `swimtrends-ingestion` ECS cluster and `swimtrends-meet-data` bucket **by name** (as `SwimtrendsCuratedStack` does). Site bucket + distribution come from `SwimtrendsWebStack` (this construct lives there).
- The refresh must be **idempotent** and publish the **full** current curated state (it rebuilds everything, then reconciles the `data/` prefix: put all built files, delete keys no longer produced).
- **Single-flight:** at most one refresh task running; a curated write during a running refresh sets a pending marker, and the finishing task re-dispatches once. No overlapping writers on the `data/` prefix.
- Node 22 for CDK; `-c alert_email=mortench.privat@gmail.com` on deploy; Docker running (image asset build).
- CLI/entrypoint code English; no user-facing copy here.

## File Structure
- Create `st-scrape/webbuild/refresh.py` — the Fargate entrypoint (build → publish → invalidate → single-flight re-dispatch) + a pure `reconcile()` helper.
- Modify `st-scrape/ingestion/cli.py` — add the `web-refresh` subcommand.
- Modify `swimtrends-app/swimtrends_app/swimtrends_web_stack.py` — web-refresh task def, dispatcher Lambda, curated-write trigger, IAM, single-flight marker.
- Create `swimtrends-app/lambda_web_refresh_trigger/web_refresh_trigger.py` — dispatcher Lambda.
- Tests: `st-scrape/tests/test_webbuild_refresh.py`, `st-scrape/tests/test_cli_web_refresh.py`, `swimtrends-app/tests/unit/test_web_refresh.py`.
- Modify `docs/superpowers/deploy-web.md` — document the automated refresh + `cli web-refresh`.

---

## Task 1: `reconcile()` — the pure publish-diff helper

**Files:** Create `st-scrape/webbuild/refresh.py`; Test: `st-scrape/tests/test_webbuild_refresh.py`.

**Interfaces:**
- Produces: `refresh.reconcile(local_files: set[str], remote_keys: set[str]) -> tuple[list[str], list[str]]` returning `(to_put, to_delete)` — relative paths to upload (all local) and remote keys under `data/` no longer produced. Pure; no S3.

- [ ] **Step 1: failing test**

```python
# st-scrape/tests/test_webbuild_refresh.py
from webbuild.refresh import reconcile


def test_reconcile_puts_all_local_and_deletes_orphans():
    local = {"index.json", "DM-L/meets.json", "DM-L/M1/meet.json"}
    remote = {"index.json", "DM-L/OLD/meet.json"}  # OLD no longer produced
    to_put, to_delete = reconcile(local, remote)
    assert set(to_put) == local                    # always republish all built files
    assert to_delete == ["DM-L/OLD/meet.json"]     # orphan pruned
```

- [ ] **Step 2: run → FAIL** (`cd st-scrape && .venv/bin/python -m pytest tests/test_webbuild_refresh.py -q`)

- [ ] **Step 3: implement**

```python
# st-scrape/webbuild/refresh.py  (helper portion)
"""Fargate entrypoint: rebuild the web JSON, publish it to the site bucket's
data/ prefix, invalidate CloudFront, and re-dispatch once if a curated write
arrived while this refresh was running (single-flight)."""


def reconcile(local_files, remote_keys):
    """(to_put, to_delete): upload every built file; delete remote data/ keys
    no longer produced. Simplest-correct — full republish is fine at this scale."""
    to_put = sorted(local_files)
    to_delete = sorted(k for k in remote_keys if k not in local_files)
    return to_put, to_delete
```

- [ ] **Step 4: run → PASS**
- [ ] **Step 5: commit** `feat(webbuild): reconcile() publish-diff helper`

---

## Task 2: `refresh.py` entrypoint (build → publish → invalidate → single-flight)

**Files:** Modify `st-scrape/webbuild/refresh.py`; Test: append to `test_webbuild_refresh.py`.

**Interfaces:**
- Consumes: `analytics.loader.connect`, `webbuild.build.build_all`, `reconcile`, boto3 (`s3`, `cloudfront`).
- Produces: `refresh.publish(con, s3, cloudfront, *, site_bucket, distribution_id, workdir) -> dict` (builds, reconciles, puts/deletes, invalidates; returns counts) and `main()` reading env `SITE_BUCKET`, `DISTRIBUTION_ID`, `PENDING_MARKER_KEY`, plus the single-flight re-dispatch via env `RESELF_*`. Content-type set per extension (`.json`→`application/json`).

- [ ] **Step 1: failing test** — inject fake `s3`/`cloudfront` (simple stubs recording calls) + a tiny `curated_con()`-style build; assert `publish()` puts `index.json` with `ContentType application/json`, deletes a pre-seeded orphan key, and creates one invalidation for `/data/*`.

```python
# append — uses stub clients, no network
class _S3Stub:
    def __init__(self, existing): self.existing=set(existing); self.put=[]; self.deleted=[]
    def get_paginator(self, _): 
        keys=self.existing
        class P: 
            def paginate(self,**k): yield {"Contents":[{"Key":f"data/{x}"} for x in keys]}
        return P()
    def upload_file(self,f,b,k,ExtraArgs=None): self.put.append((k,(ExtraArgs or {}).get("ContentType")))
    def delete_objects(self,Bucket,Delete): self.deleted+=[o["Key"] for o in Delete["Objects"]]

class _CFStub:
    def __init__(self): self.invalidations=[]
    def create_invalidation(self,**kw): self.invalidations.append(kw); return {"Invalidation":{"Id":"I1"}}
```

(Full test body: build into a tmp dir via the fixture connection, run `publish`, assert `("data/index.json","application/json") in s3.put`, orphan in `s3.deleted`, one CF invalidation with `Paths.Items == ["/data/*"]`.)

- [ ] **Step 2: run → FAIL**
- [ ] **Step 3: implement** — full code:

```python
# st-scrape/webbuild/refresh.py  (append)
import os
import tempfile
from pathlib import Path


def publish(con, s3, cloudfront, *, site_bucket, distribution_id, workdir):
    from webbuild.build import build_all
    written = build_all(con, workdir)                       # local JSON tree
    local = {str(p.relative_to(workdir)) for p in written}
    # existing data/ keys
    remote = set()
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=site_bucket, Prefix="data/"):
        for o in page.get("Contents", []):
            remote.add(o["Key"][len("data/"):])
    to_put, to_delete = reconcile(local, remote)
    for rel in to_put:
        s3.upload_file(str(Path(workdir) / rel), site_bucket, f"data/{rel}",
                       ExtraArgs={"ContentType": "application/json"})
    for batch in (to_delete[i:i+1000] for i in range(0, len(to_delete), 1000)):
        s3.delete_objects(Bucket=site_bucket,
                          Delete={"Objects": [{"Key": f"data/{k}"} for k in batch]})
    cloudfront.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/data/*"]},
                           "CallerReference": f"web-refresh-{len(local)}-{len(to_delete)}"})
    return {"put": len(to_put), "deleted": len(to_delete)}


def main():
    import boto3
    from analytics.loader import connect
    site_bucket = os.environ["SITE_BUCKET"]
    distribution_id = os.environ["DISTRIBUTION_ID"]
    marker_bucket = os.environ["MARKER_BUCKET"]
    marker_key = os.environ.get("PENDING_MARKER_KEY", "_web_refresh_pending")
    s3 = boto3.client("s3")
    con = connect()
    with tempfile.TemporaryDirectory() as tmp:
        result = publish(con, s3, boto3.client("cloudfront"),
                         site_bucket=site_bucket, distribution_id=distribution_id,
                         workdir=Path(tmp))
    print(f"published {result}")
    # single-flight: if a curated write landed during this run, clear the marker
    # and re-dispatch one more refresh so the final state is always published.
    try:
        s3.head_object(Bucket=marker_bucket, Key=marker_key)
    except s3.exceptions.ClientError:
        return
    s3.delete_object(Bucket=marker_bucket, Key=marker_key)
    boto3.client("ecs").run_task(**_run_task_kwargs_from_env())


if __name__ == "__main__":
    main()
```

`_run_task_kwargs_from_env()` reads `ECS_CLUSTER`, `TASK_DEFINITION`, `SUBNET_IDS`, `SECURITY_GROUP_ID` (same env the dispatcher uses) and returns the `run_task` kwargs (FARGATE, awsvpc networkConfiguration, `startedBy="web-refresh-reself"`). Factor it into a shared helper reused by the CLI and dispatcher.

- [ ] **Step 4: run → PASS**  •  **Step 5: commit** `feat(webbuild): refresh entrypoint (publish + invalidate + single-flight)`

---

## Task 3: dispatcher Lambda + single-flight

**Files:** Create `swimtrends-app/lambda_web_refresh_trigger/web_refresh_trigger.py`; Test: covered by CDK synth (Task 5) + a unit test of the handler with stubbed boto3.

**Interfaces:** `lambda_handler(event, ctx)` — on a curated `obt_result` write: if a web-refresh task is already RUNNING (`ecs.list_tasks(cluster, family=..., desiredStatus="RUNNING")`), write the pending marker to the bucket and return; else `ecs.run_task(...)` (startedBy `web-refresh-auto`). Env mirrors CurateTrigger (`ECS_CLUSTER`, `TASK_DEFINITION`, `CONTAINER_NAME`, `SUBNET_IDS`, `SECURITY_GROUP_ID`) plus `MARKER_BUCKET`, `PENDING_MARKER_KEY`, `TASK_FAMILY`.

- [ ] **Step 1: failing test** (`test_web_refresh` unit or a small handler test): with a boto3 stub reporting a running task, assert the handler PUTs the marker and does **not** run_task; with none running, asserts run_task called once.
- [ ] **Step 2–4:** implement the handler (single-flight logic above), run tests → PASS.
- [ ] **Step 5: commit** `feat(infra): web-refresh dispatcher lambda + single-flight`

---

## Task 4: CLI `web-refresh` subcommand (manual/backfill)

**Files:** Modify `st-scrape/ingestion/cli.py`; Test: `st-scrape/tests/test_cli_web_refresh.py`.

**Interfaces:** `python -m ingestion.cli web-refresh` → `ecs run-task` the web-refresh task def and print the task ARN. Cluster/task-def/network from env (`WEB_REFRESH_CLUSTER`, `WEB_REFRESH_TASKDEF`, `WEB_REFRESH_SUBNETS`, `WEB_REFRESH_SG`) — documented in the runbook; the deploy prints them as stack outputs.

- [ ] **Step 1: failing test** — parse `web-refresh` args; patch `boto3.client("ecs").run_task` to return a fake ARN; assert it's called with the env-derived cluster/taskdef and prints the ARN.
- [ ] **Step 2–4:** add the subparser + `cmd_web_refresh` mirroring the existing `dispatch` command's boto3 usage; run → PASS.
- [ ] **Step 5: commit** `feat(cli): web-refresh subcommand (dispatch Fargate rebuild)`

---

## Task 5: CDK — web-refresh task def, trigger, IAM

**Files:** Modify `swimtrends-app/swimtrends_app/swimtrends_web_stack.py`; Test: `swimtrends-app/tests/unit/test_web_refresh.py`.

**Interfaces:** Adds to `SwimtrendsWebStack`: a `FargateTaskDefinition` (family `swimtrends-web-refresh`, reuse `Dockerfile.curate`, container command `["python","-m","webbuild.refresh"]`, env `SITE_BUCKET`/`DISTRIBUTION_ID`/`MARKER_BUCKET`/ECS-run-task env); IAM (read `swimtrends-meet-data` `curated/*`+`reference/*`, read/write site bucket, `cloudfront:CreateInvalidation` on the distribution, `ecs:RunTask`+`iam:PassRole` for the self re-dispatch); the `WebRefreshDispatcher` Lambda; and an S3 `OBJECT_CREATED` notification on `swimtrends-meet-data` prefix `curated/obt_result/` → dispatcher. Outputs: `WebRefreshTaskDefArn`, `WebRefreshClusterName`, subnets/SG (for the CLI env).

- [ ] **Step 1: failing CDK assertion test** — synth the web stack; assert: a task def with a container whose `Command` is `["python","-m","webbuild.refresh"]`; a Lambda with handler `web_refresh_trigger.lambda_handler`; a `cloudfront:CreateInvalidation` policy statement; an S3 notification config for prefix `curated/obt_result/`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement the constructs. **Gotchas to handle:** (a) the shared bucket is imported `from_bucket_name` in both curated + web stacks — adding a second `add_event_notification` uses the bucket-notifications custom resource; confirm it merges rather than clobbers the curate notification (they filter different prefixes: `raw/…results.jsonl` vs `curated/obt_result/`). If CDK's managed notifications conflict across stacks, fall back to a single notifications owner or an EventBridge rule on the bucket. (b) `iam:PassRole` for both the task role and execution role (as CurateTrigger does). (c) reuse the VPC/SG lookup pattern from the curated stack.
- [ ] **Step 4:** run the full CDK unit suite → PASS (no regressions to the existing 20).
- [ ] **Step 5: commit** `feat(infra): web-refresh Fargate task + curated-write trigger`

---

## Task 6: Tests green, docs, deploy (HUMAN-GATED)

- [ ] **Step 1:** full suites — `st-scrape` pytest + `swimtrends-app` CDK unit — all green.
- [ ] **Step 2:** update `docs/superpowers/deploy-web.md`: the automated refresh (trigger + single-flight), the `cli web-refresh` command and its env, and that `make web-refresh` remains the local fallback. Commit.
- [ ] **Step 3 (gated):** with user approval, `cdk deploy SwimtrendsWebStack …` (Docker running, node 22, `-c alert_email`). Then **verify end-to-end:** dispatch `cli web-refresh` (or re-curate a meet), confirm the Fargate task runs, `/data/*.json` updates, and CloudFront serves the new content.

---

## Self-Review
- **Coverage:** entrypoint (Tasks 1–2), automated trigger + single-flight (Task 3), manual CLI (Task 4), infra (Task 5), deploy (Task 6). ✔
- **Single-flight** is explicit (running-task check + pending marker + finishing-task re-dispatch) — the one piece the evaluation flagged as must-not-skip. ✔
- **Placeholders:** pure helper (Task 1) and entrypoint (Task 2) carry full code; the CDK/Lambda tasks describe constructs + the exact assertions and name the real cross-stack gotchas rather than hand-waving.
- **Open items for the implementer:**
  1. Verify `curated/obt_result/` is the **last** dataset the curate task writes (sentinel correctness) — check `curate/parquet.py` write order; if not, pick the actual last one.
  2. Confirm two managed S3 notifications on the same imported bucket coexist across stacks (CDK custom resource); if not, switch the bucket to EventBridge notifications and use EventBridge rules for both curate + refresh triggers.
  3. Full-rebuild cost grows with the dataset (every trigger rebuilds ~1450 files, and the elite query is the slow part). Fine now; **incremental rebuild** (only the changed meet + its season-comparison neighbors) is the future upgrade — note it, don't build it yet.
