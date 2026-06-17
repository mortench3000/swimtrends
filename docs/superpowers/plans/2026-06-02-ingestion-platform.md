# Swimtrends Ingestion Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the `st-scrape` scraper to AWS so registered meets are scraped automatically shortly after they finish, landing raw JSONL in S3, scaling to zero when idle.

**Architecture:** A DynamoDB registry holds the configured meets. An hourly EventBridge schedule (and an on-demand CLI) invokes a dispatcher Lambda that finds due meets (time-gate + completeness check), then launches one Fargate task per meet. The Fargate task runs the unchanged `scrape_races.py`, uploads the three JSONL files to S3, and updates the registry. Decision logic and AWS access are split into pure, dependency-injected modules so they unit-test without touching AWS.

**Tech Stack:** Python 3.12, boto3, requests + BeautifulSoup (existing scraper), AWS CDK v2 (2.189.0, Python), ECS Fargate, Lambda, DynamoDB, EventBridge Scheduler, SNS, S3, ECR. Tests: pytest + moto.

---

## File Structure

New code lives in a new `st-scrape/ingestion/` package plus one shared helper added to the existing scraper. CDK lives in the existing `swimtrends-app/` project as a second stack.

| File | Responsibility |
|------|----------------|
| `st-scrape/scrape_races.py` (modify) | Add `meet_has_results(meet_id)` shared completeness helper. |
| `st-scrape/ingestion/__init__.py` | Package marker. |
| `st-scrape/ingestion/completion.py` | Pure time-gate logic: scrape/deadline windows + per-meet decision. No I/O. |
| `st-scrape/ingestion/registry.py` | DynamoDB access layer (`MeetRegistry`): scan/claim/mark/put/reset. |
| `st-scrape/ingestion/dispatcher.py` | `run_cycle(...)` orchestration (injected deps) + `lambda_handler` wiring. |
| `st-scrape/ingestion/scrape_task.py` | Fargate entrypoint: run scraper → upload to S3 → update registry → SNS. |
| `st-scrape/ingestion/cli.py` | `swimtrends` operational CLI: register / dispatch. |
| `st-scrape/Dockerfile` | Scraper container image for Fargate. |
| `st-scrape/.dockerignore` | Keep `db/`, `logs/`, pdfs out of the image. |
| `st-scrape/requirements.txt` | Runtime deps (requests, beautifulsoup4, boto3). |
| `st-scrape/requirements-dev.txt` | Test deps (pytest, moto). |
| `st-scrape/tests/conftest.py` | Pytest fixtures: AWS env vars + region. |
| `st-scrape/tests/test_*.py` | Unit tests per module. |
| `swimtrends-app/swimtrends_app/swimtrends_ingestion_stack.py` | New CDK stack for all ingestion resources. |
| `swimtrends-app/app.py` (modify) | Instantiate the new stack. |
| `swimtrends-app/tests/unit/test_ingestion_stack.py` | CDK assertion tests. |
| `st-scrape/README-ingestion.md` | Deployment + operations runbook. |

**Shared-code rule:** the dispatcher Lambda and the Fargate task both import from `st-scrape` (`scrape_races.py` is the single source of truth). The Lambda only needs `meet_has_results`; the Fargate task runs the scraper as a subprocess.

---

## Task 1: Test scaffolding and dependencies

**Files:**
- Create: `st-scrape/requirements.txt`
- Create: `st-scrape/requirements-dev.txt`
- Create: `st-scrape/ingestion/__init__.py`
- Create: `st-scrape/tests/__init__.py`
- Create: `st-scrape/tests/conftest.py`

- [ ] **Step 1: Create runtime requirements**

`st-scrape/requirements.txt`:

```
requests>=2.31
beautifulsoup4>=4.12
boto3>=1.34
```

- [ ] **Step 2: Create dev requirements**

`st-scrape/requirements-dev.txt`:

```
-r requirements.txt
pytest>=7.4
moto[dynamodb,s3]>=5.0
```

- [ ] **Step 3: Create package marker**

`st-scrape/ingestion/__init__.py`:

```python
"""Swimtrends ingestion platform: registry, dispatcher, Fargate task, CLI."""
```

- [ ] **Step 4: Create tests package marker**

`st-scrape/tests/__init__.py`:

```python
```

- [ ] **Step 5: Create pytest fixtures**

`st-scrape/tests/conftest.py`:

```python
"""Shared test fixtures: fake AWS credentials and region so moto/boto3 never
touch real AWS, and a DynamoDB registry table created in moto."""
import os

import boto3
import pytest

REGION = "eu-west-1"
TABLE_NAME = "swimtrends-meet-registry-test"


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    """Force fake credentials + region for every test."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def dynamodb_table():
    """Create the registry table in moto and yield the boto3 Table resource."""
    from moto import mock_aws

    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "meet_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "meet_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield ddb.Table(TABLE_NAME)
```

- [ ] **Step 6: Install dev dependencies**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pip install -r requirements-dev.txt`
Expected: installs requests, beautifulsoup4, boto3, pytest, moto without error.

- [ ] **Step 7: Verify pytest collects nothing yet (no tests)**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest -q`
Expected: `no tests ran` (exit code 5 is fine) — confirms pytest + imports work.

- [ ] **Step 8: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/requirements.txt st-scrape/requirements-dev.txt st-scrape/ingestion/__init__.py st-scrape/tests/__init__.py st-scrape/tests/conftest.py
git commit -m "chore: ingestion package scaffolding and test deps"
```

---

## Task 2: Shared `meet_has_results()` completeness helper

The dispatcher's completeness check must use the same parsing as the scraper. Add a helper to `scrape_races.py` that fetches the meet page and reports whether any races are present. It reuses the existing `fetch()` and `scrape_race_list()` functions.

**Files:**
- Modify: `st-scrape/scrape_races.py` (add function after `scrape_race_list`, around line 449)
- Test: `st-scrape/tests/test_meet_has_results.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_meet_has_results.py`:

```python
"""meet_has_results() returns True only when the meet page lists races."""
import scrape_races


def test_returns_true_when_races_present(monkeypatch):
    monkeypatch.setattr(scrape_races, "scrape_race_list", lambda html, mid: [{"race_id": 1}])

    class FakeResp:
        text = "<html>has races</html>"

    monkeypatch.setattr(scrape_races, "fetch", lambda url, timeout=30: FakeResp())
    assert scrape_races.meet_has_results("10970") is True


def test_returns_false_when_no_races(monkeypatch):
    monkeypatch.setattr(scrape_races, "scrape_race_list", lambda html, mid: [])

    class FakeResp:
        text = "<html>nothing yet</html>"

    monkeypatch.setattr(scrape_races, "fetch", lambda url, timeout=30: FakeResp())
    assert scrape_races.meet_has_results("10970") is False


def test_returns_false_on_fetch_error(monkeypatch):
    def boom(url, timeout=30):
        raise RuntimeError("network down")

    monkeypatch.setattr(scrape_races, "fetch", boom)
    assert scrape_races.meet_has_results("10970") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_meet_has_results.py -v`
Expected: FAIL with `AttributeError: module 'scrape_races' has no attribute 'meet_has_results'`.

- [ ] **Step 3: Add the helper to `scrape_races.py`**

Insert immediately after the `scrape_race_list` function ends (before `def scrape_split_times`, around line 450):

```python
def meet_has_results(meet_id):
    """Return True if the meet page currently lists any races (results are
    published as races complete, so 'any races present' is our completeness
    signal). Returns False on any fetch/parse error so the dispatcher simply
    re-checks next hour rather than crashing the cycle."""
    url = f"https://xn--svmmetider-1cb.dk/staevne/?{meet_id}#resultater"
    try:
        response = fetch(url, timeout=30)
        races = scrape_race_list(response.text, meet_id)
        return bool(races)
    except Exception as e:  # network, parse, anything — treat as "not ready yet"
        print(f"meet_has_results({meet_id}) check failed: {e}", file=sys.stderr)
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_meet_has_results.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/scrape_races.py st-scrape/tests/test_meet_has_results.py
git commit -m "feat: add meet_has_results completeness helper to scraper"
```

---

## Task 3: Pure time-gate logic (`completion.py`)

Compute the scrape/deadline windows from a meet's `end_date` and decide what to do at a given `now`. Pure functions, no AWS, fully deterministic (caller passes `now`).

**Files:**
- Create: `st-scrape/ingestion/completion.py`
- Test: `st-scrape/tests/test_completion.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_completion.py`:

```python
"""Time-gate decision logic. now is always injected, so tests are deterministic."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ingestion import completion

CPH = ZoneInfo("Europe/Copenhagen")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=CPH)


def test_windows_default_grace_and_deadline():
    scrape_after, deadline = completion.windows("2024-07-11", 6, 72)
    # End of 2024-07-11 23:59 CPH + 6h -> 2024-07-12 05:59
    assert scrape_after == at(2024, 7, 12, 5, 59)
    # + 72h from 23:59 on the 11th -> 2024-07-14 23:59
    assert deadline == at(2024, 7, 14, 23, 59)


def test_skip_before_scrape_window():
    # Noon on the meet's last day, well before end+6h.
    assert completion.decide(at(2024, 7, 11, 12), "2024-07-11", 6, 72) == "skip"


def test_check_inside_window():
    # 08:00 the morning after — past +6h, before +72h.
    assert completion.decide(at(2024, 7, 12, 8), "2024-07-11", 6, 72) == "check"


def test_deadline_after_window():
    # Five days later — past the 72h deadline.
    assert completion.decide(at(2024, 7, 16, 8), "2024-07-11", 6, 72) == "deadline"


def test_custom_grace_hours_shift_window():
    # grace 0 -> window opens at 23:59 on the meet's last day.
    assert completion.decide(at(2024, 7, 11, 23, 30), "2024-07-11", 0, 72) == "skip"
    assert completion.decide(at(2024, 7, 12, 0, 30), "2024-07-11", 0, 72) == "check"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_completion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.completion'`.

- [ ] **Step 3: Implement `completion.py`**

`st-scrape/ingestion/completion.py`:

```python
"""Pure completion-window logic for the dispatcher.

A meet is scraped after end_date 23:59 (local) + grace_hours, and force-scraped
once past end_date 23:59 + deadline_hours even if the page never showed results.
All functions take `now` explicitly so callers/tests control the clock.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_GRACE_HOURS = 6
DEFAULT_DEADLINE_HOURS = 72
DEFAULT_TZ = "Europe/Copenhagen"

# Decisions returned by decide().
SKIP = "skip"          # too early — do nothing
CHECK = "check"        # in window — verify the page actually has results
DEADLINE = "deadline"  # past deadline — dispatch regardless (force fallback)


def windows(end_date, grace_hours, deadline_hours, tz=DEFAULT_TZ):
    """Return (scrape_after, deadline) as tz-aware datetimes.

    end_date is 'YYYY-MM-DD'. The anchor is 23:59 on that date in `tz`.
    """
    zone = ZoneInfo(tz)
    day = datetime.strptime(end_date, "%Y-%m-%d").date()
    anchor = datetime.combine(day, time(23, 59), tzinfo=zone)
    return anchor + timedelta(hours=grace_hours), anchor + timedelta(hours=deadline_hours)


def decide(now, end_date, grace_hours, deadline_hours, tz=DEFAULT_TZ):
    """Classify `now` against the meet's scrape/deadline windows."""
    scrape_after, deadline = windows(end_date, grace_hours, deadline_hours, tz)
    if now < scrape_after:
        return SKIP
    if now < deadline:
        return CHECK
    return DEADLINE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_completion.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/ingestion/completion.py st-scrape/tests/test_completion.py
git commit -m "feat: add pure completion-window decision logic"
```

---

## Task 4: DynamoDB registry layer (`registry.py`)

Encapsulate all DynamoDB access. The idempotent `claim()` is the concurrency guard: a conditional update from `scheduled`/`failed` to `scraping` that increments `attempts`.

**Files:**
- Create: `st-scrape/ingestion/registry.py`
- Test: `st-scrape/tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_registry.py`:

```python
"""MeetRegistry against a moto DynamoDB table."""
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def make_registry():
    return MeetRegistry(TABLE_NAME, region="eu-west-1")


def test_put_meet_creates_scheduled_row(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DM-L", "DMJ-L"], "2024-07-11")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scheduled"
    assert item["category"] == ["DM-L", "DMJ-L"]
    assert item["end_date"] == "2024-07-11"
    assert int(item["attempts"]) == 0


def test_put_meet_with_overrides(dynamodb_table):
    reg = make_registry()
    reg.put_meet("11712", ["DM-L"], "2025-04-05", grace_hours=12, deadline_hours=48)
    item = dynamodb_table.get_item(Key={"meet_id": "11712"})["Item"]
    assert int(item["grace_hours"]) == 12
    assert int(item["deadline_hours"]) == 48


def test_scheduled_meets_returns_scheduled_and_failed(dynamodb_table):
    reg = make_registry()
    reg.put_meet("1", ["DO"], "2024-01-01")
    reg.put_meet("2", ["DO"], "2024-01-02")
    reg.claim("2")
    reg.mark_scraped("2", "Meet 2", 10, 3)  # status -> scraped, excluded
    reg.put_meet("3", ["DO"], "2024-01-03")
    reg.claim("3")
    reg.mark_failed("3", "boom")  # status -> failed, included
    ids = {m["meet_id"] for m in reg.scheduled_meets()}
    assert ids == {"1", "3"}


def test_claim_succeeds_once_then_blocks(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    assert reg.claim("10970") is True   # scheduled -> scraping
    assert reg.claim("10970") is False  # already scraping
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scraping"
    assert int(item["attempts"]) == 1


def test_claim_allows_retry_from_failed(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    assert reg.claim("10970") is True  # failed -> scraping again
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert int(item["attempts"]) == 2


def test_mark_scraped_sets_fields_and_clears_error(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "old error")
    reg.claim("10970")
    reg.mark_scraped("10970", "Danish Open 2024", 1234, 74, when="2026-06-02T10:00:00Z")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scraped"
    assert item["meet_name"] == "Danish Open 2024"
    assert int(item["result_count"]) == 1234
    assert int(item["race_count"]) == 74
    assert item["last_scraped_at"] == "2026-06-02T10:00:00Z"
    assert "last_error" not in item


def test_reset_returns_to_scheduled(dynamodb_table):
    reg = make_registry()
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    reg.reset("10970")
    item = dynamodb_table.get_item(Key={"meet_id": "10970"})["Item"]
    assert item["status"] == "scheduled"
    assert int(item["attempts"]) == 0
    assert "last_error" not in item
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.registry'`.

- [ ] **Step 3: Implement `registry.py`**

`st-scrape/ingestion/registry.py`:

```python
"""DynamoDB access layer for the meet registry.

Status lifecycle: scheduled -> scraping -> (scraped | failed). A failed meet is
retried until max_attempts (enforced by the dispatcher, not here). claim() is the
idempotency guard: a conditional transition to 'scraping' that increments
attempts, so overlapping dispatcher runs cannot double-launch the same meet.
"""
import boto3
from boto3.dynamodb.conditions import Attr

# Statuses the dispatcher may pick up for a (re)scrape.
PICKABLE = ("scheduled", "failed")


class MeetRegistry:
    def __init__(self, table_name, region=None):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put_meet(self, meet_id, category, end_date, grace_hours=None, deadline_hours=None):
        """Insert/overwrite a meet as freshly scheduled."""
        item = {
            "meet_id": meet_id,
            "category": list(category),
            "end_date": end_date,
            "status": "scheduled",
            "attempts": 0,
        }
        if grace_hours is not None:
            item["grace_hours"] = grace_hours
        if deadline_hours is not None:
            item["deadline_hours"] = deadline_hours
        self._table.put_item(Item=item)

    def get(self, meet_id):
        return self._table.get_item(Key={"meet_id": meet_id}).get("Item")

    def scheduled_meets(self):
        """All meets eligible for (re)scraping: status in scheduled|failed."""
        items, kwargs = [], {"FilterExpression": Attr("status").is_in(list(PICKABLE))}
        while True:
            resp = self._table.scan(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def claim(self, meet_id):
        """Atomically move scheduled|failed -> scraping and bump attempts.
        Returns True if this caller won the claim, False if already taken."""
        try:
            self._table.update_item(
                Key={"meet_id": meet_id},
                UpdateExpression="SET #s = :scraping ADD attempts :one",
                ConditionExpression=Attr("status").is_in(list(PICKABLE)),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":scraping": "scraping", ":one": 1},
            )
            return True
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def mark_scraped(self, meet_id, meet_name, result_count, race_count, when=None):
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression=(
                "SET #s = :scraped, meet_name = :n, result_count = :rc, "
                "race_count = :rac, last_scraped_at = :t REMOVE last_error"
            ),
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":scraped": "scraped",
                ":n": meet_name,
                ":rc": result_count,
                ":rac": race_count,
                ":t": when or _now_iso(),
            },
        )

    def mark_failed(self, meet_id, error, when=None):
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression="SET #s = :failed, last_error = :e, last_scraped_at = :t",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":failed": "failed",
                ":e": str(error)[:1000],
                ":t": when or _now_iso(),
            },
        )

    def reset(self, meet_id):
        """Manual --rescrape: back to scheduled, attempts zeroed, error cleared."""
        self._table.update_item(
            Key={"meet_id": meet_id},
            UpdateExpression="SET #s = :scheduled, attempts = :zero REMOVE last_error",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":scheduled": "scheduled", ":zero": 0},
        )


def _now_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_registry.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/ingestion/registry.py st-scrape/tests/test_registry.py
git commit -m "feat: add DynamoDB meet registry access layer"
```

---

## Task 5: Dispatcher orchestration + Lambda handler (`dispatcher.py`)

`run_cycle` ties registry + completion + side-effect callbacks (`run_task`, `has_results`, `notify`) together with all dependencies injected, so it unit-tests with plain fakes. `lambda_handler` wires the real AWS implementations.

**Files:**
- Create: `st-scrape/ingestion/dispatcher.py`
- Test: `st-scrape/tests/test_dispatcher.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_dispatcher.py`:

```python
"""run_cycle orchestration with injected fakes (no AWS, deterministic clock)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from ingestion import dispatcher
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME

CPH = ZoneInfo("Europe/Copenhagen")


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=CPH)


class Recorder:
    """Captures run_task launches and notifications."""

    def __init__(self):
        self.launched = []
        self.notes = []

    def run_task(self, meet_id, category):
        self.launched.append((meet_id, category))

    def notify(self, subject, message):
        self.notes.append((subject, message))


def test_skips_meets_before_window(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 11, 12), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == []
    assert rec.launched == []


def test_dispatches_when_in_window_and_results_present(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DM-L", "DMJ-L"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == ["1"]
    assert rec.launched == [("1", ["DM-L", "DMJ-L"])]
    assert reg.get("1")["status"] == "scraping"


def test_in_window_but_no_results_yet_leaves_scheduled(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify)
    assert dispatched == []
    assert reg.get("1")["status"] == "scheduled"


def test_deadline_forces_dispatch_and_notifies(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 16, 8), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify)
    assert dispatched == ["1"]
    assert any("deadline" in s.lower() for s, _ in rec.notes)


def test_force_bypasses_gates(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()
    # now is before the window, results absent — force overrides both.
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 11, 1), run_task=rec.run_task,
        has_results=lambda mid: False, notify=rec.notify, force=True)
    assert dispatched == ["1"]


def test_meet_ids_filter_restricts_cycle(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    reg.put_meet("2", ["DO"], "2024-07-11")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify,
        meet_ids=["2"], force=True)
    assert dispatched == ["2"]


def test_exhausted_attempts_are_skipped(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    for _ in range(3):  # drive attempts to max_attempts=3, status failed
        reg.claim("1")
        reg.mark_failed("1", "boom")
    rec = Recorder()
    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=rec.run_task,
        has_results=lambda mid: True, notify=rec.notify, max_attempts=3)
    assert dispatched == []


def test_run_task_failure_marks_failed_and_notifies(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("1", ["DO"], "2024-07-11")
    rec = Recorder()

    def boom(meet_id, category):
        raise RuntimeError("ECS RunTask rejected")

    dispatched = dispatcher.run_cycle(
        reg, now=at(2024, 7, 12, 8), run_task=boom,
        has_results=lambda mid: True, notify=rec.notify)
    assert dispatched == []
    assert reg.get("1")["status"] == "failed"
    assert any("failed" in s.lower() for s, _ in rec.notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_dispatcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.dispatcher'`.

- [ ] **Step 3: Implement `dispatcher.py`**

`st-scrape/ingestion/dispatcher.py`:

```python
"""Dispatcher: find due meets and launch one Fargate scrape task per meet.

run_cycle() is pure-ish orchestration with all side effects injected
(run_task, has_results, notify), so it unit-tests without AWS. lambda_handler()
wires the real boto3 + scraper implementations and is the EventBridge/CLI entry.
"""
import os

from ingestion import completion
from ingestion.registry import MeetRegistry

DEFAULT_MAX_ATTEMPTS = 3


def run_cycle(registry, *, now, run_task, has_results, notify,
              meet_ids=None, force=False, max_attempts=DEFAULT_MAX_ATTEMPTS):
    """Evaluate every scheduled/failed meet and dispatch the due ones.

    Returns the list of meet_ids actually launched this cycle.
    """
    meets = registry.scheduled_meets()
    if meet_ids is not None:
        wanted = set(meet_ids)
        meets = [m for m in meets if m["meet_id"] in wanted]

    dispatched = []
    for meet in meets:
        meet_id = meet["meet_id"]

        # A failed meet that has used up its attempts needs a manual --rescrape.
        if meet.get("status") == "failed" and int(meet.get("attempts", 0)) >= max_attempts:
            continue

        forced_by_deadline = False
        if force:
            pass  # bypass time + completeness gates entirely
        else:
            grace = int(meet.get("grace_hours", completion.DEFAULT_GRACE_HOURS))
            deadline = int(meet.get("deadline_hours", completion.DEFAULT_DEADLINE_HOURS))
            verdict = completion.decide(now, meet["end_date"], grace, deadline)
            if verdict == completion.SKIP:
                continue
            if verdict == completion.CHECK:
                if not has_results(meet_id):
                    continue  # not ready — re-check next hour
            elif verdict == completion.DEADLINE:
                forced_by_deadline = True

        # Idempotent claim: lose the race -> another run already took it.
        if not registry.claim(meet_id):
            continue

        category = meet["category"]
        try:
            run_task(meet_id, category)
        except Exception as e:
            registry.mark_failed(meet_id, f"RunTask failed: {e}")
            notify("Swimtrends scrape dispatch FAILED",
                   f"Meet {meet_id}: could not launch scrape task: {e}")
            continue

        if forced_by_deadline:
            notify("Swimtrends deadline-forced scrape",
                   f"Meet {meet_id} dispatched at deadline without a confirmed "
                   f"results page. Verify the meet completed as expected.")
        dispatched.append(meet_id)

    return dispatched


# --------------------------------------------------------------------------
# Lambda wiring (real AWS implementations)
# --------------------------------------------------------------------------

def lambda_handler(event, context):
    """EventBridge (empty event) or CLI ({"meet_ids": [...], "force": bool})."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import boto3

    import scrape_races  # single source of truth for completeness parsing

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    tz = os.environ.get("REFERENCE_TZ", completion.DEFAULT_TZ)
    now = datetime.now(ZoneInfo(tz))

    ecs = boto3.client("ecs")
    sns = boto3.client("sns")
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    def run_task(meet_id, category):
        ecs.run_task(
            cluster=os.environ["ECS_CLUSTER"],
            taskDefinition=os.environ["TASK_DEFINITION"],
            launchType="FARGATE",
            count=1,
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": os.environ["SUBNET_IDS"].split(","),
                    "securityGroups": [os.environ["SECURITY_GROUP_ID"]],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{
                    "name": os.environ["CONTAINER_NAME"],
                    "environment": [
                        {"name": "MEET_ID", "value": str(meet_id)},
                        {"name": "CATEGORIES", "value": ",".join(category)},
                    ],
                }]
            },
        )

    def notify(subject, message):
        sns.publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)

    event = event or {}
    dispatched = run_cycle(
        registry,
        now=now,
        run_task=run_task,
        has_results=scrape_races.meet_has_results,
        notify=notify,
        meet_ids=event.get("meet_ids"),
        force=bool(event.get("force", False)),
        max_attempts=int(os.environ.get("MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)),
    )
    return {"dispatched": dispatched, "count": len(dispatched)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_dispatcher.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/ingestion/dispatcher.py st-scrape/tests/test_dispatcher.py
git commit -m "feat: add dispatcher orchestration and Lambda handler"
```

---

## Task 6: Fargate entrypoint (`scrape_task.py`)

The container's entrypoint. Runs the unchanged `scrape_races.py` as a subprocess, uploads the three JSONL files to S3, and updates the registry + SNS. The actual upload/scrape/notify steps are injected so the orchestration is testable; `main()` wires the real boto3/subprocess implementations.

**Files:**
- Create: `st-scrape/ingestion/scrape_task.py`
- Test: `st-scrape/tests/test_scrape_task.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_scrape_task.py`:

```python
"""run_scrape_task orchestration with injected scrape/upload/notify fakes."""
import json

from ingestion import scrape_task
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def write_db_files(tmp_path, meet_id, n_results, n_races, meet_name):
    (tmp_path / f"{meet_id}_meet_info.jsonl").write_text(
        json.dumps({"meet_id": int(meet_id), "meet": meet_name}) + "\n", encoding="utf-8")
    with open(tmp_path / f"{meet_id}_results.jsonl", "w", encoding="utf-8") as f:
        for i in range(n_results):
            f.write(json.dumps({"race_id": i}) + "\n")
    with open(tmp_path / f"{meet_id}_races.jsonl", "w", encoding="utf-8") as f:
        for i in range(n_races):
            f.write(json.dumps({"race_id": i}) + "\n")


def test_success_uploads_three_files_and_marks_scraped(dynamodb_table, tmp_path):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DM-L"], "2024-07-11")
    reg.claim("10970")
    write_db_files(tmp_path, "10970", n_results=5, n_races=2, meet_name="Danish Open")
    uploaded, notes = [], []

    scrape_task.run_scrape_task(
        meet_id="10970", categories=["DM-L"], db_dir=str(tmp_path),
        registry=reg,
        scrape=lambda mid, cats: None,  # pretend the scraper already wrote files
        upload=lambda local, key: uploaded.append(key),
        notify=lambda subject, msg: notes.append(subject),
        when="2026-06-02T10:00:00Z")

    assert sorted(uploaded) == [
        "raw/meet=10970/meet_info.jsonl",
        "raw/meet=10970/races.jsonl",
        "raw/meet=10970/results.jsonl",
    ]
    item = reg.get("10970")
    assert item["status"] == "scraped"
    assert item["meet_name"] == "Danish Open"
    assert int(item["result_count"]) == 5
    assert int(item["race_count"]) == 2
    assert any("succeeded" in s.lower() for s in notes)


def test_scrape_failure_marks_failed_and_raises(dynamodb_table, tmp_path):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DM-L"], "2024-07-11")
    reg.claim("10970")
    notes = []

    def boom(mid, cats):
        raise RuntimeError("scraper exited 1")

    try:
        scrape_task.run_scrape_task(
            meet_id="10970", categories=["DM-L"], db_dir=str(tmp_path),
            registry=reg, scrape=boom,
            upload=lambda local, key: None,
            notify=lambda subject, msg: notes.append(subject))
        raised = False
    except RuntimeError:
        raised = True

    assert raised is True  # non-zero exit so ECS records task failure
    assert reg.get("10970")["status"] == "failed"
    assert any("failed" in s.lower() for s in notes)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_scrape_task.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.scrape_task'`.

- [ ] **Step 3: Implement `scrape_task.py`**

`st-scrape/ingestion/scrape_task.py`:

```python
"""Fargate container entrypoint.

Runs scrape_races.py for one meet, uploads the three JSONL outputs to the S3 raw
zone, and records the outcome in the registry + SNS. Orchestration (run_scrape_task)
takes its side effects as callables so it is unit-testable; main() wires the real
subprocess/boto3 implementations from environment variables.
"""
import json
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # st-scrape/
SCRAPER = os.path.join(SCRIPT_DIR, "scrape_races.py")
DEFAULT_DB_DIR = os.path.join(SCRIPT_DIR, "db")

# Output filename -> S3 object basename within raw/meet=<id>/.
RAW_FILES = {
    "{meet_id}_meet_info.jsonl": "meet_info.jsonl",
    "{meet_id}_races.jsonl": "races.jsonl",
    "{meet_id}_results.jsonl": "results.jsonl",
}


def _count_lines(path):
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def run_scrape_task(*, meet_id, categories, db_dir, registry, scrape, upload,
                    notify, when=None):
    """Scrape one meet, upload raw files, update registry. Re-raises on failure
    (after marking failed) so the container exits non-zero."""
    try:
        scrape(meet_id, categories)

        meet_info_path = os.path.join(db_dir, f"{meet_id}_meet_info.jsonl")
        results_path = os.path.join(db_dir, f"{meet_id}_results.jsonl")
        races_path = os.path.join(db_dir, f"{meet_id}_races.jsonl")

        with open(meet_info_path, encoding="utf-8") as f:
            meet_name = json.loads(f.readline()).get("meet", "")
        result_count = _count_lines(results_path)
        race_count = _count_lines(races_path)

        for local_template, s3_basename in RAW_FILES.items():
            local = os.path.join(db_dir, local_template.format(meet_id=meet_id))
            upload(local, f"raw/meet={meet_id}/{s3_basename}")

        registry.mark_scraped(meet_id, meet_name, result_count, race_count, when=when)
        notify("Swimtrends scrape SUCCEEDED",
               f"Meet {meet_id} ({meet_name}): {result_count} results across "
               f"{race_count} races uploaded to raw/meet={meet_id}/.")
    except Exception as e:
        registry.mark_failed(meet_id, str(e), when=when)
        notify("Swimtrends scrape FAILED", f"Meet {meet_id}: {e}")
        raise


def _subprocess_scrape(meet_id, categories):
    """Run the real scraper as a child process (keeps scrape_races.py untouched)."""
    subprocess.run([sys.executable, SCRAPER, str(meet_id), *categories],
                   check=True, cwd=SCRIPT_DIR)


def main():
    import boto3

    from ingestion.registry import MeetRegistry

    meet_id = os.environ["MEET_ID"]
    categories = [c for c in os.environ.get("CATEGORIES", "").split(",") if c]
    bucket = os.environ["RAW_BUCKET"]
    topic_arn = os.environ["SNS_TOPIC_ARN"]

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    s3 = boto3.client("s3")
    sns = boto3.client("sns")

    run_scrape_task(
        meet_id=meet_id,
        categories=categories,
        db_dir=DEFAULT_DB_DIR,
        registry=registry,
        scrape=_subprocess_scrape,
        upload=lambda local, key: s3.upload_file(local, bucket, key),
        notify=lambda subject, msg: sns.publish(
            TopicArn=topic_arn, Subject=subject[:100], Message=msg),
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_scrape_task.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/ingestion/scrape_task.py st-scrape/tests/test_scrape_task.py
git commit -m "feat: add Fargate scrape-task entrypoint"
```

---

## Task 7: Operational CLI (`cli.py`)

`swimtrends register` writes to the registry; `swimtrends dispatch` invokes the dispatcher Lambda. Command parsing + payload building are injected with fakes for testing; `main()` wires real boto3.

**Files:**
- Create: `st-scrape/ingestion/cli.py`
- Test: `st-scrape/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`st-scrape/tests/test_cli.py`:

```python
"""CLI command handling: register hits the registry, dispatch builds the right
Lambda payload."""
from ingestion import cli
from ingestion.registry import MeetRegistry
from tests.conftest import TABLE_NAME


def test_register_creates_scheduled_meet(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    cli.run(["register", "10970", "--categories", "DM-L,DMJ-L",
             "--end-date", "2024-07-11"], registry=reg, invoke=None)
    item = reg.get("10970")
    assert item["status"] == "scheduled"
    assert item["category"] == ["DM-L", "DMJ-L"]
    assert item["end_date"] == "2024-07-11"


def test_register_with_overrides(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    cli.run(["register", "11712", "--categories", "DM-L", "--end-date",
             "2025-04-05", "--grace-hours", "12", "--deadline-hours", "48"],
            registry=reg, invoke=None)
    item = reg.get("11712")
    assert int(item["grace_hours"]) == 12
    assert int(item["deadline_hours"]) == 48


def test_rescrape_resets_existing_meet(dynamodb_table):
    reg = MeetRegistry(TABLE_NAME, region="eu-west-1")
    reg.put_meet("10970", ["DO"], "2024-07-11")
    reg.claim("10970")
    reg.mark_failed("10970", "err")
    cli.run(["register", "10970", "--categories", "DO", "--end-date",
             "2024-07-11", "--rescrape"], registry=reg, invoke=None)
    item = reg.get("10970")
    assert item["status"] == "scheduled"
    assert int(item["attempts"]) == 0


def test_dispatch_no_args_sends_empty_payload(dynamodb_table):
    calls = []
    cli.run(["dispatch"], registry=None, invoke=lambda payload: calls.append(payload))
    assert calls == [{}]


def test_dispatch_specific_meet_with_force(dynamodb_table):
    calls = []
    cli.run(["dispatch", "10970", "--force"], registry=None,
            invoke=lambda payload: calls.append(payload))
    assert calls == [{"meet_ids": ["10970"], "force": True}]


def test_dispatch_all_force_backfill(dynamodb_table):
    calls = []
    cli.run(["dispatch", "--all", "--force"], registry=None,
            invoke=lambda payload: calls.append(payload))
    assert calls == [{"force": True}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ingestion.cli'`.

- [ ] **Step 3: Implement `cli.py`**

`st-scrape/ingestion/cli.py`:

```python
"""swimtrends operational CLI.

  swimtrends register <meet_id> --categories DM-L,DMJ-L --end-date 2024-07-11
                                [--grace-hours N] [--deadline-hours N] [--rescrape]
  swimtrends dispatch                      # normal due-check cycle
  swimtrends dispatch <meet_id> [--force]  # one meet now (force skips gates)
  swimtrends dispatch --all --force        # backfill every scheduled meet now

register talks to DynamoDB directly; dispatch invokes the dispatcher Lambda.
"""
import argparse
import json
import os


def build_parser():
    parser = argparse.ArgumentParser(prog="swimtrends",
                                     description="Swimtrends ingestion control.")
    sub = parser.add_subparsers(dest="command", required=True)

    reg = sub.add_parser("register", help="Add or update a meet in the registry.")
    reg.add_argument("meet_id")
    reg.add_argument("--categories", required=True,
                     help="Comma-separated, e.g. DM-L,DMJ-L")
    reg.add_argument("--end-date", required=True, help="YYYY-MM-DD (meet's last day)")
    reg.add_argument("--grace-hours", type=int, default=None)
    reg.add_argument("--deadline-hours", type=int, default=None)
    reg.add_argument("--rescrape", action="store_true",
                     help="Reset an existing meet's status to scheduled.")

    disp = sub.add_parser("dispatch", help="Invoke the dispatcher Lambda now.")
    disp.add_argument("meet_id", nargs="?", default=None)
    disp.add_argument("--all", action="store_true",
                      help="Target every scheduled meet (use with --force to backfill).")
    disp.add_argument("--force", action="store_true",
                      help="Bypass the grace/completeness gates.")
    return parser


def run(argv, *, registry, invoke):
    """Execute one CLI command. registry/invoke are injected for testing."""
    args = build_parser().parse_args(argv)

    if args.command == "register":
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        if args.rescrape and registry.get(args.meet_id) is not None:
            registry.put_meet(args.meet_id, categories, args.end_date,
                              grace_hours=args.grace_hours,
                              deadline_hours=args.deadline_hours)
            registry.reset(args.meet_id)
        else:
            registry.put_meet(args.meet_id, categories, args.end_date,
                              grace_hours=args.grace_hours,
                              deadline_hours=args.deadline_hours)
        print(f"Registered meet {args.meet_id} ({', '.join(categories)}) "
              f"end_date={args.end_date} status=scheduled")
        return

    if args.command == "dispatch":
        payload = {}
        if args.meet_id:
            payload["meet_ids"] = [args.meet_id]
        if args.force:
            payload["force"] = True
        invoke(payload)
        print(f"Dispatcher invoked with payload: {payload or '{} (full due-check cycle)'}")
        return


def main():
    import boto3

    from ingestion.registry import MeetRegistry

    registry = MeetRegistry(os.environ["REGISTRY_TABLE"])
    lambda_client = boto3.client("lambda")
    function_name = os.environ["DISPATCHER_FUNCTION"]

    def invoke(payload):
        lambda_client.invoke(
            FunctionName=function_name,
            InvocationType="Event",  # async fire-and-forget
            Payload=json.dumps(payload).encode("utf-8"),
        )

    import sys

    run(sys.argv[1:], registry=registry, invoke=invoke)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest tests/test_cli.py -v`
Expected: 6 passed.

- [ ] **Step 5: Run the full test suite**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && python -m pytest -q`
Expected: all tests pass (meet_has_results 3, completion 5, registry 7, dispatcher 8, scrape_task 2, cli 6 = 31 passed).

- [ ] **Step 6: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/ingestion/cli.py st-scrape/tests/test_cli.py
git commit -m "feat: add swimtrends operational CLI"
```

---

## Task 8: Container image (`Dockerfile`)

**Files:**
- Create: `st-scrape/Dockerfile`
- Create: `st-scrape/.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

`st-scrape/.dockerignore`:

```
db/
logs/
tests/
__pycache__/
*.pyc
*.pdf
*.md
*.html
backup/
```

- [ ] **Step 2: Create the `Dockerfile`**

`st-scrape/Dockerfile`:

```dockerfile
FROM python:3.12-slim

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
```

- [ ] **Step 3: Build the image locally to verify it assembles**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && docker build -t swimtrends-scraper:test .`
Expected: build succeeds through the ENTRYPOINT line. (If Docker is unavailable in this environment, skip the build and rely on the CDK asset build in Task 9; note the skip.)

- [ ] **Step 4: Verify the entrypoint imports cleanly inside the image**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/st-scrape && docker run --rm --entrypoint python swimtrends-scraper:test -c "import ingestion.scrape_task; import scrape_races; print('ok')"`
Expected: prints `ok`. (Skip if Docker unavailable; note the skip.)

- [ ] **Step 5: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/Dockerfile st-scrape/.dockerignore
git commit -m "feat: add scraper container image for Fargate"
```

---

## Task 9: CDK ingestion stack

All ingestion infrastructure in a new stack. Reuses the existing `swimtrends-meet-data` bucket by name. Fargate runs in the default VPC's public subnets with a public IP and an egress-only SG — **no NAT gateway** (the scale-to-zero requirement).

**Files:**
- Create: `swimtrends-app/swimtrends_app/swimtrends_ingestion_stack.py`
- Modify: `swimtrends-app/app.py`

- [ ] **Step 1: Implement the stack**

`swimtrends-app/swimtrends_app/swimtrends_ingestion_stack.py`:

```python
"""Swimtrends ingestion platform (Spec 1 of 3).

DynamoDB meet registry, ECR image + Fargate task running the st-scrape scraper,
a dispatcher Lambda triggered hourly by EventBridge (and on demand by the CLI),
and an SNS topic for alerts. Reuses the existing swimtrends-meet-data S3 bucket.
"""
import os

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

# st-scrape lives alongside swimtrends-app (this file is .../swimtrends_app/).
ST_SCRAPE_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "st-scrape"))

CONTAINER_NAME = "scraper"
RAW_BUCKET_NAME = "swimtrends-meet-data"


class SwimtrendsIngestionStack(Stack):

    def __init__(self, scope: Construct, construct_id: str,
                 alert_email: str = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- Reused raw data bucket ---
        raw_bucket = s3.Bucket.from_bucket_name(
            self, "RawBucket", RAW_BUCKET_NAME)

        # --- Meet registry ---
        registry = dynamodb.Table(
            self, "MeetRegistry",
            table_name="swimtrends-meet-registry",
            partition_key=dynamodb.Attribute(
                name="meet_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # --- Alerts ---
        topic = sns.Topic(self, "AlertTopic", display_name="Swimtrends ingestion alerts")
        if alert_email:
            topic.add_subscription(subs.EmailSubscription(alert_email))

        # --- Networking: default VPC, public subnets, egress-only SG (no NAT) ---
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        scrape_sg = ec2.SecurityGroup(
            self, "ScrapeTaskSG", vpc=vpc, allow_all_outbound=True,
            description="Egress-only SG for the Fargate scrape task")

        # --- ECS cluster + Fargate task definition ---
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc,
                              cluster_name="swimtrends-ingestion")

        task_def = ecs.FargateTaskDefinition(
            self, "ScrapeTaskDef", cpu=512, memory_limit_mib=1024)

        scraper_image = ecs.ContainerImage.from_asset(ST_SCRAPE_DIR)
        task_def.add_container(
            CONTAINER_NAME,
            image=scraper_image,
            logging=ecs.LogDriver.aws_logs(
                stream_prefix="scrape",
                log_retention=logs.RetentionDays.ONE_MONTH),
            environment={
                "RAW_BUCKET": RAW_BUCKET_NAME,
                "REGISTRY_TABLE": registry.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
            },
        )

        # Task role: write raw objects, update registry, publish alerts.
        raw_bucket.grant_put(task_def.task_role, objects_key_pattern="raw/*")
        registry.grant_write_data(task_def.task_role)
        topic.grant_publish(task_def.task_role)

        # --- Dispatcher Lambda (bundles scraper + ingestion + deps) ---
        dispatcher_fn = lambda_.Function(
            self, "Dispatcher",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="ingestion.dispatcher.lambda_handler",
            timeout=Duration.minutes(1),
            memory_size=256,
            code=lambda_.Code.from_asset(
                ST_SCRAPE_DIR,
                bundling={
                    "image": lambda_.Runtime.PYTHON_3_12.bundling_image,
                    "command": [
                        "bash", "-c",
                        "pip install requests beautifulsoup4 -t /asset-output && "
                        "cp scrape_races.py /asset-output/ && "
                        "cp -r ingestion /asset-output/",
                    ],
                },
            ),
            environment={
                "REGISTRY_TABLE": registry.table_name,
                "SNS_TOPIC_ARN": topic.topic_arn,
                "ECS_CLUSTER": cluster.cluster_arn,
                "TASK_DEFINITION": task_def.task_definition_arn,
                "CONTAINER_NAME": CONTAINER_NAME,
                "SUBNET_IDS": ",".join(
                    s.subnet_id for s in vpc.public_subnets),
                "SECURITY_GROUP_ID": scrape_sg.security_group_id,
                "REFERENCE_TZ": "Europe/Copenhagen",
                "MAX_ATTEMPTS": "3",
            },
        )

        # Dispatcher permissions: read/update registry, launch tasks, alert.
        registry.grant_read_write_data(dispatcher_fn)
        topic.grant_publish(dispatcher_fn)
        dispatcher_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ecs:RunTask"],
            resources=[task_def.task_definition_arn]))
        dispatcher_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"],
            resources=[task_def.task_role.role_arn,
                       task_def.execution_role.role_arn]))

        # --- Hourly schedule ---
        events.Rule(
            self, "HourlySchedule",
            schedule=events.Schedule.rate(Duration.hours(1)),
            targets=[targets.LambdaFunction(dispatcher_fn)],
        )
```

- [ ] **Step 2: Wire the stack into `app.py`**

Replace the contents of `swimtrends-app/app.py` with:

```python
#!/usr/bin/env python3

import aws_cdk as cdk

from swimtrends_app.swimtrends_app_stack import SwimtrendsAppStack
from swimtrends_app.swimtrends_ingestion_stack import SwimtrendsIngestionStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")

app = cdk.App()

SwimtrendsAppStack(app, "SwimtrendsAppStack", env=ENV)

SwimtrendsIngestionStack(
    app, "SwimtrendsIngestionStack",
    alert_email=app.node.try_get_context("alert_email"),
    env=ENV,
)

app.synth()
```

- [ ] **Step 3: Synthesize to verify the stack is valid CloudFormation**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/swimtrends-app && .venv/bin/cdk synth SwimtrendsIngestionStack`
Expected: prints the synthesized template with no errors. `Vpc.from_lookup` requires account credentials for context lookup; if credentials are unavailable, expect a lookup error — note it and rely on the assertion tests in Task 10 (which stub the VPC) plus a real `cdk synth` during deployment (Task 11).

- [ ] **Step 4: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add swimtrends-app/swimtrends_app/swimtrends_ingestion_stack.py swimtrends-app/app.py
git commit -m "feat: add CDK ingestion stack (DynamoDB, Fargate, dispatcher, schedule)"
```

---

## Task 10: CDK assertion tests

Verify the stack provisions the expected resources without a real deploy. Use a fixture-injected fake VPC so `from_lookup` doesn't hit AWS.

**Files:**
- Create: `swimtrends-app/tests/unit/test_ingestion_stack.py`

- [ ] **Step 1: Write the failing test**

`swimtrends-app/tests/unit/test_ingestion_stack.py`:

```python
"""Assertion tests for the ingestion stack. VPC context is stubbed so
from_lookup does not require AWS credentials."""
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from swimtrends_app.swimtrends_ingestion_stack import SwimtrendsIngestionStack

ENV = cdk.Environment(account="179537025528", region="eu-west-1")


def _synth():
    app = cdk.App(context={
        # Stub the default-VPC lookup with a minimal 2-AZ VPC.
        "vpc-provider:account=179537025528:filter.isDefault=true:region=eu-west-1:returnAsymmetricSubnets=true": {
            "vpcId": "vpc-12345",
            "vpcCidrBlock": "10.0.0.0/16",
            "availabilityZones": [],
            "subnetGroups": [{
                "name": "Public",
                "type": "Public",
                "subnets": [
                    {"subnetId": "subnet-1", "availabilityZone": "eu-west-1a",
                     "routeTableId": "rtb-1", "cidr": "10.0.0.0/24"},
                    {"subnetId": "subnet-2", "availabilityZone": "eu-west-1b",
                     "routeTableId": "rtb-2", "cidr": "10.0.1.0/24"},
                ],
            }],
        }
    })
    stack = SwimtrendsIngestionStack(app, "TestIngestionStack",
                                     alert_email="ops@example.com", env=ENV)
    return Template.from_stack(stack)


def test_registry_table_created():
    t = _synth()
    t.has_resource_properties("AWS::DynamoDB::Table", {
        "TableName": "swimtrends-meet-registry",
        "KeySchema": [{"AttributeName": "meet_id", "KeyType": "HASH"}],
    })


def test_fargate_task_definition_sized():
    t = _synth()
    t.has_resource_properties("AWS::ECS::TaskDefinition", {
        "Cpu": "512",
        "Memory": "1024",
        "RequiresCompatibilities": ["FARGATE"],
    })


def test_dispatcher_lambda_handler_and_timeout():
    t = _synth()
    t.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "ingestion.dispatcher.lambda_handler",
        "Runtime": "python3.12",
        "Timeout": 60,
    })


def test_hourly_schedule_rule():
    t = _synth()
    t.has_resource_properties("AWS::Events::Rule", {
        "ScheduleExpression": "rate(1 hour)",
    })


def test_sns_topic_and_email_subscription():
    t = _synth()
    t.resource_count_is("AWS::SNS::Topic", 1)
    t.has_resource_properties("AWS::SNS::Subscription", {
        "Protocol": "email",
        "Endpoint": "ops@example.com",
    })


def test_dispatcher_can_run_ecs_tasks():
    t = _synth()
    t.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": {
            "Statement": Match.array_with([
                Match.object_like({"Action": "ecs:RunTask"}),
            ]),
        },
    })
```

- [ ] **Step 2: Run test to verify it fails (then passes once Task 9 code is present)**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/swimtrends-app && .venv/bin/python -m pytest tests/unit/test_ingestion_stack.py -v`
Expected: with Task 9 implemented, 6 passed. If the VPC context key differs by CDK version, run once to read the actual lookup key from the error message and update the context dict key to match.

- [ ] **Step 3: Run the existing stack test too (no regression)**

Run: `cd /home/mortench/keycore/repos/mortench3000/swimtrends/swimtrends-app && .venv/bin/python -m pytest tests/unit -q`
Expected: all unit tests pass.

- [ ] **Step 4: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add swimtrends-app/tests/unit/test_ingestion_stack.py
git commit -m "test: add CDK assertion tests for ingestion stack"
```

---

## Task 11: Deployment & operations runbook

**Files:**
- Create: `st-scrape/README-ingestion.md`

- [ ] **Step 1: Write the runbook**

`st-scrape/README-ingestion.md`:

````markdown
# Swimtrends Ingestion Platform — Runbook

Deploys the `st-scrape` scraper to AWS. Registered meets are scraped
automatically ~6h after they finish; raw JSONL lands in
`s3://swimtrends-meet-data/raw/meet=<id>/`.

## Prerequisites

- AWS credentials for account `179537025528` (region `eu-west-1`).
- Docker running (CDK builds the scraper image as an asset).
- Python env for CDK: `cd swimtrends-app && python -m venv .venv &&
  .venv/bin/pip install -r requirements.txt`.

## Deploy

```bash
cd swimtrends-app
# alert_email subscribes an address to the SNS alert topic (confirm via email).
.venv/bin/cdk deploy SwimtrendsIngestionStack -c alert_email=you@example.com
```

The existing `SwimtrendsAppStack` (S3 bucket, Glue, Athena) is untouched.

## Register meets

The CLI reads two env vars:

```bash
export REGISTRY_TABLE=swimtrends-meet-registry
export DISPATCHER_FUNCTION=$(aws cloudformation describe-stacks \
  --stack-name SwimtrendsIngestionStack \
  --query "Stacks[0].Outputs" --output text | grep -i dispatcher)  # or read from console

cd ../st-scrape
python -m ingestion.cli register 10970 --categories DM-L,DMJ-L --end-date 2024-07-11
```

Optional per-meet overrides: `--grace-hours N` (default 6), `--deadline-hours N`
(default 72). Re-arm a meet that failed/finished: add `--rescrape`.

## Dispatch

```bash
python -m ingestion.cli dispatch                 # normal hourly-style due check
python -m ingestion.cli dispatch 10970 --force   # scrape one meet now, skip gates
python -m ingestion.cli dispatch --all --force   # backfill: scrape all scheduled now
```

The hourly EventBridge schedule runs the same due check automatically; manual
dispatch is for backfill and ad-hoc runs.

## Historical backfill

```bash
python -m ingestion.cli register 10329 --categories DO --end-date 2023-07-09
python -m ingestion.cli register 10969 --categories DO --end-date 2024-07-14
# ... register all historical meets (end_date in the past) ...
python -m ingestion.cli dispatch --all --force
```

Past `end_date` meets dispatch immediately with no completeness polling.

## Status lifecycle

`scheduled → scraping → scraped | failed`. A `failed` meet is retried each cycle
up to 3 attempts, then alerts and stops — reset with `register ... --rescrape`.
Inspect: `aws dynamodb scan --table-name swimtrends-meet-registry`.

## Where things land

- Raw data: `s3://swimtrends-meet-data/raw/meet=<id>/{meet_info,races,results}.jsonl`
  (bucket is versioned → prior scrapes retained automatically).
- Scrape logs: CloudWatch, log group `/aws/ecs/...` stream prefix `scrape`.
- Dispatcher logs: CloudWatch, the Lambda's log group.
- Alerts: SNS email on scrape success, failure, and deadline-forced runs.

## Cost

Idle ≈ S3 storage only. Fargate bills per-second during a scrape; Lambda,
EventBridge, DynamoDB on-demand, and SNS are negligible at this volume. There is
**no NAT gateway** — the scrape task uses a public subnet + public IP.

## Tests

```bash
cd st-scrape && python -m pytest -q                       # ingestion unit tests
cd swimtrends-app && .venv/bin/python -m pytest tests/unit # CDK assertion tests
```
````

- [ ] **Step 2: Commit**

```bash
cd /home/mortench/keycore/repos/mortench3000/swimtrends
git add st-scrape/README-ingestion.md
git commit -m "docs: add ingestion platform deployment runbook"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|------------------|------|
| Containerize st-scrape on Fargate | Task 8 (Dockerfile), Task 9 (task def) |
| DynamoDB meet registry + status lifecycle | Task 4 |
| Dispatcher Lambda (time gate + completeness + RunTask) | Task 3 (gates), Task 5 (orchestration), Task 2 (completeness) |
| Hourly EventBridge trigger | Task 9 |
| CLI dispatch (on-demand + force + --all backfill) | Task 5 (event contract), Task 7 (CLI) |
| Three raw JSONL → S3 `raw/meet=<id>/` | Task 6 |
| `swimtrends register` / `--rescrape` | Task 7 |
| SNS notifications (success/failure/deadline) | Task 5 (dispatch fail + deadline), Task 6 (scrape success/failure) |
| Idempotent claim (no double-launch) | Task 4 (`claim`), Task 5 (claim-then-run) |
| grace=6 / deadline=72 defaults | Task 3 |
| No NAT, public subnet + public IP, egress SG | Task 9 |
| Fargate 0.5 vCPU / 1 GB | Task 9 |
| Reuse `swimtrends-meet-data` bucket by name | Task 9 |
| Retry until max_attempts (3) then alert+stop | Task 5 (`test_exhausted_attempts_are_skipped`) |
| Shared `meet_has_results()` helper | Task 2 |
| New `SwimtrendsIngestionStack`, leave Glue/Athena untouched | Task 9 |
| CloudWatch logs (Fargate + Lambda) | Task 9 |

All in-scope spec requirements map to a task. Points/Parquet/Glue/Athena/DuckDB are explicitly out of scope (Specs 2/3) and intentionally absent.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — every code step contains complete, runnable code.

**Type consistency:** `MeetRegistry` method names (`put_meet`, `get`, `scheduled_meets`, `claim`, `mark_scraped`, `mark_failed`, `reset`) are used identically across Tasks 4, 5, 6, 7. `mark_scraped(meet_id, meet_name, result_count, race_count, when=)` signature matches all call sites. `run_cycle(...)` keyword args (`now`, `run_task`, `has_results`, `notify`, `meet_ids`, `force`, `max_attempts`) match between Task 5's implementation and tests, and the Lambda handler. `run_scrape_task(...)` keyword args match between Task 6's implementation and tests. `cli.run(argv, *, registry, invoke)` matches Task 7's tests. Completion constants (`SKIP`/`CHECK`/`DEADLINE`, `DEFAULT_GRACE_HOURS=6`, `DEFAULT_DEADLINE_HOURS=72`) match between Task 3 and Task 5. Environment variable names (`REGISTRY_TABLE`, `RAW_BUCKET`, `SNS_TOPIC_ARN`, `ECS_CLUSTER`, `TASK_DEFINITION`, `CONTAINER_NAME`, `SUBNET_IDS`, `SECURITY_GROUP_ID`, `REFERENCE_TZ`, `MAX_ATTEMPTS`, `DISPATCHER_FUNCTION`) are consistent between the Lambda handler (Task 5), scrape_task (Task 6), CLI (Task 7), and the CDK stack (Task 9).
````
