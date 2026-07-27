# AI coach evaluation on meet pages — design

**Date:** 2026-07-27
**Status:** Design approved, ready for implementation plan.
**Supersedes nothing.** Replaces web-app deferred tiers #2 (auth) and #3 (Bedrock
chat) as the next web-app initiative — those stay parked (see the
`web-app-deferred-tiers` memory).

## Summary

Add a collapsible **"Trænerens vurdering"** section to the meet detail page: a
~250-word Danish report in the voice of an experienced swimming coach, comparing
the meet against the last five seasons on record and calling out standout swims
and disciplines trending up or down.

The text is produced **offline, in batch**, by a Strands agent calling Amazon
Bedrock with a versioned Guardrail, and cached content-addressed on S3 so
identical data always yields identical published text. The SPA loads it as
static JSON. There is no runtime LLM endpoint and no per-view cost.

## Goals

- A coach-style read of each meet that a human would recognise as informed.
- Every number in the text verifiable against the data already on the page.
- Deterministic output: same data + same prompt + same model → byte-identical text.
- Zero cost and zero latency per page view; no public endpoint to abuse.
- A measured basis for choosing the model (quality vs price/performance).

## Non-goals

- No interactive chat or follow-up questions (that is the parked tier #3; this
  design deliberately leaves the agent module packageable for it later).
- No AgentCore Runtime, no container, no API, no auth.
- No per-swimmer narrative pages, no season-level or category-level evaluation.

## Architecture

Two decoupled offline steps. **`webbuild` never calls Bedrock.**

```
make web-refresh
 ├─ python -m webbuild   --out web/public/data      # unchanged, ~50 min
 ├─ python -m evaluation --out web/public/data      # NEW: seconds on cache hit
 │    for each (category, meet):
 │      digest = digest.build(con, cat, meet)             # pure SQL, deterministic
 │      key    = sha256(canonical_json({digest, prompt_v, schema_v, model_id}))
 │      s3://swimtrends-meet-data/evaluations/<cat>/<meet>/<key>.json
 │        hit  → reuse verbatim (no model call, no cost)
 │        miss → Strands agent → number check → store under key
 │      write <out>/<cat>/<meet>/evaluation.json  (only if we have one)
 └─ aws s3 sync web/public/data … --delete    # picks up evaluation.json
```

`web-refresh` syncs with `--delete`, so `evaluation.json` must exist in
`web/public/data` before the sync — hence the evaluation step runs between
`webbuild` and the sync, in the same target. A standalone `make web-eval`
target exists for iterating without a full 50-minute rebuild.

The evaluation step opens its own `analytics.loader.connect()`. The digest
queries are cheap aggregates (seconds per meet), so it does not piggyback on
webbuild's slow per-race loop.

### Why the cache key includes prompt, schema and model

Keying on the data alone would let a prompt tweak silently change published text
on the next refresh. Including `prompt_version`, `schema_version` and `model_id`
means:

- Unchanged inputs → the stored text is reused forever; no drift between refreshes.
- A deliberate prompt or model change → every meet regenerates, visibly and on purpose.
- **Revoke** = `python -m evaluation --force [--meets …]`, or delete the S3 object.

`PROMPT_VERSION` and `SCHEMA_VERSION` are module constants in `agent.py`, bumped
by hand when the system prompt or `MeetEvaluation` changes. The bucket is already
versioned, so a regeneration keeps the prior text.

## Components

Each module is independently testable and small (none over ~150 lines).

| Module | Responsibility | Depends on |
| --- | --- | --- |
| `st-scrape/webbuild/digest.py` | SQL → digest dict for one meet | DuckDB views only |
| `st-scrape/evaluation/agent.py` | digest → report dict (Strands + Bedrock + guardrail) | `strands`, `boto3` |
| `st-scrape/evaluation/cache.py` | content-addressed get/put on S3 | `boto3` |
| `st-scrape/evaluation/check.py` | every number in the text appears in the digest | pure |
| `st-scrape/evaluation/__main__.py` | the loop; `--meets/--force/--model/--dry-run/--out` | the four above |

`digest.py` lives in `webbuild/` because it is pure curated-zone SQL of the same
kind as `queries.py`, and because the model-eval harness and the frontend both
want the same shape.

### Digest

Everything the agent is allowed to know. All numbers come from here.

```python
digest = {
  "meet":    {"name", "date", "season", "category", "course"},
  "facts":   {"entrants", "events", "clubs", "juniors",
              "median_points", "elite_median_points", "top_points"},
  "season_history": [ {"season", "entrants", "clubs",
                       "median_points", "elite_median_points"}, … up to 5 ],
  "top_swims":      [ {"name", "club", "event", "time", "points", "rank"}, … 10 ],
  "by_stroke":      [ {"stroke", "dist_group", "median_points", "prev5_median"}, … ],
}
```

- `facts` and `season_history` reuse the existing `_MEET_FACTS_SQL` /
  `_MEET_COMPARE_SQL` / `_MEET_ELITE_SQL` shapes already behind
  `queries.build_meet` (including the junior-scoped `DMJ-L` variants), truncated
  to the meet's season plus the five prior seasons on record.
- `top_swims` and `by_stroke` are the two new aggregates: top-N individual swims
  by `points` for the meet, and median points per stroke × distance group for the
  meet vs the mean of the five prior seasons. `class = 'open'`, `NOT is_dq`,
  scored swims only.
- `dist_group` buckets distances as sprint (50/100), middle (200/400), long
  (800/1500) so the "disciplines in motion" section has something coarse enough
  to be true.
- Coverage is real: 37 meets, seasons 2016–2026, 5 categories. A meet with fewer
  than five prior seasons produces a shorter `season_history` and the prompt must
  handle that without inventing a comparison.

### Agent

```python
COACH = Agent(
    model=BedrockModel(model_id=MODEL_ID, region_name="eu-west-1",
                       guardrail_id=GUARDRAIL_ID, guardrail_version=GUARDRAIL_VERSION,
                       max_tokens=1200, cache_prompt="default"),
    system_prompt=SYSTEM_PROMPT,
)
result = COACH(f"<digest>{canonical_json(digest)}</digest>",
               structured_output_model=MeetEvaluation)
report = result.structured_output
```

- **Converse API via Strands' `BedrockModel`** — never legacy `InvokeModel`.
  `region_name` passed explicitly (`AWS_REGION` is the lowest-priority fallback
  in the boto3 chain).
- **Structured output** via `structured_output_model` on `__call__` (the current
  API; `agent.structured_output()` is deprecated). `MeetEvaluation` is a Pydantic
  model with one field per section, so the frontend renders sections instead of
  parsing prose and section order is fixed without prompt-pleading.
- **No tools, no memory, no session manager.** The digest is the agent's entire
  world; that is what makes both the grounding check and the cache honest.
- `max_tokens=1200` sized to the ~250-word report: `input_tokens + max_tokens` is
  reserved 1:1 against the TPM quota at request start, so an oversized value
  blocks concurrency for nothing.
- Prompt caching with the static system prompt first and the digest last.
- **Model access is verified before the batch runs** (a not-enabled model fails
  the first Converse call with `AccessDeniedException`, which we would rather see
  on meet 1 than meet 30).

### Report shape (`MeetEvaluation`)

```
sections: [
  {heading: "Samlet niveau",          body: …},
  {heading: "Bredde",                 body: …},
  {heading: "Fremhævede svømninger",  body: …},   # 2–4 named swims
  {heading: "Discipliner i bevægelse",body: …},
]
```

Danish throughout — the site is Danish and the stroke names in the data
(`Fri`/`Ryg`/`Bryst`/`Fly`/`IM`/`HM`) are Danish already.

### Safety: named swimmers

The evaluation ships on **all five categories, including the junior
championships (DMJ-K/DMJ-L), where the named swimmers are 16–18.** Names already
appear on the site as result rows, so this adds no new personal data — only prose
about times. What it must never add is judgement about people.

Enforced in two places, prompt and guardrail:

**Allowed** — results-grounded statements only: time, points, placement, event.

> **Corrected during implementation.** This line originally also allowed
> "improvement against a swimmer's own prior best". The digest has no such field
> — `top_swims` rows are `name/club/event/time/points/rank`, and `derived` holds
> meet-level deltas only — so the claim cannot be grounded and the system prompt
> does not authorise it. Adding it later means adding a per-swimmer prior-best to
> the digest first (the `personal_best` analytics view already exists), not
> loosening the prompt.

**Blocked** — talent or future projections ("et kommende OL-emne"); technique,
body, health, injury or training speculation ("virker utrænet på de sidste 50
m"); anything framed as criticism of a named person ("skødesløs vending");
age, school, or any personal detail beyond club affiliation.

### Guardrail (CDK, versioned)

One Bedrock Guardrail, defined in `swimtrends-app`, applied inline on the
Converse call at a **numbered version — never `DRAFT`**:

- Content filters at service defaults.
- **Denied topics** for the three blocked categories above.
- **Contextual grounding check** with the digest as `grounding_source`, the user
  turn as `query`, and the report as the guarded content. Starting thresholds
  0.7 grounding / 0.5 relevance, tuned from the model-eval run's false-positive
  rate. Grounding runs on `source='OUTPUT'` only. The report is well under the
  5,000-character response limit and the digest well under the 100,000-character
  source limit.

A guardrail block is a failure, not a fallback: the meet is skipped and nothing
is written to the cache.

### Number check (`check.py`)

The deterministic half of "don't make things up", and cheap enough to keep
forever:

1. Extract every numeric literal from the report text.
2. Each must appear in the digest — times normalised to `m:ss.cc`, integers
   compared exactly, percentages allowed when derivable from two digest numbers.
3. Fail → one retry with the offending sentences quoted back to the agent.
4. Fail again → log and skip the meet.

The cache put happens **only after the check passes**, so a partially-bad report
is never published.

## Frontend

`web/src/routes/Meet.svelte`, directly below `.chart-grid`:

```svelte
{#if evaluation}
  <details class="coach">
    <summary>Trænerens vurdering <span class="muted">· AI-genereret, eksperimentelt</span></summary>
    {#each evaluation.sections as s (s.heading)}
      <h4>{s.heading}</h4><p>{s.body}</p>
    {/each}
    <p class="muted fine">
      Denne vurdering er automatisk genereret af en sprogmodel ud fra stævnets tal.
      Den er eksperimentel og en fortolkning — ikke fakta. Alle tal kan efterprøves
      i tabellerne ovenfor. Genereret {evaluation.generated_at} · {evaluation.model_label}
    </p>
  </details>
{/if}
```

- **Collapsed by default** (`<details>`, no `open`) — native disclosure, no JS.
- **Two-layer disclosure.** The summary line always reads
  "AI-genereret, eksperimentelt" even when collapsed; the footer inside carries
  the full statement that this is an interpretation rather than fact, that the
  numbers are checkable in the tables above, and which model produced it on which
  date. Publishing machine-written prose about named people without saying so
  plainly is the one thing in this design that would be indefensible.
- `dataClient.getEvaluation(cat, meetId)` swallows a 404 → `null` → the section
  is simply absent. The page renders exactly as today.

## Model evaluation

`make eval-models MEETS=12486,11902,10771` runs the same `agent.py` against the
same digests with each candidate, applies the number check, and writes a
side-by-side HTML page plus a table of number-check pass rate, input/output
tokens, cost per meet, and latency. A human picks the winner once; the number
check stays in the pipeline.

Candidates: Claude Sonnet and Claude Haiku via the `eu.` cross-region inference
profile (EU data residency), plus Amazon Nova Pro and Mistral Large as cheap
controls. **Exact Bedrock model IDs and per-MTok prices are verified against the
Bedrock model catalog and the Bedrock pricing page at implementation time** —
they are not hardcoded from memory, and Bedrock pricing is separate from
first-party Anthropic API pricing.

Not in scope: an LLM-as-judge rubric. Add it only if reading four reports for
three meets turns out to be too slow to iterate on.

## Error handling

Any failure — Bedrock throttle, `AccessDeniedException`, guardrail block, number
check failing twice, structured-output validation error — logs and skips that
meet. Consequences by design:

- No `evaluation.json` for that meet → the section is absent → page unchanged.
- A previously cached, valid report is **never** deleted by a failed regeneration.
- The 50-minute data refresh never blocks on Bedrock and never fails because of it.

## Testing (TDD, no network)

- `test_digest.py` — in-memory DuckDB via `tests/analytics_fixtures.build_curated`
  + `analytics.loader.create_views`: the 5-season window, `top_swims` ordering,
  `by_stroke` prev5 medians, junior-scoped `DMJ-L`, and a meet with no prior
  seasons.
- `test_cache_key.py` — same digest → same key; reordered dict → same key;
  bumped `prompt_version` → different key.
- `test_check.py` — a fabricated number fails; a legitimate report passes; time
  formats round-trip.
- `test_agent.py` — Bedrock client stubbed: asserts region, guardrail id and
  numbered version are passed, and that a guardrail-blocked response raises
  rather than writing to cache.
- `web/` unit test for the section: renders with `evaluation`, renders nothing
  without it, disclaimer text present.
- One CDK assertion test in `swimtrends-app/tests/unit` for the guardrail and its
  version.

No test calls Bedrock. `make eval-models` is the only thing that does, and it is
run by hand.

## Cost and operations

- One Guardrail. One S3 prefix (`evaluations/`) on the existing versioned bucket.
- ~37 model calls for a full regeneration; cents. €0 for a refresh where no
  digest changed.
- No new Lambda, container, endpoint, or IAM role beyond `bedrock:InvokeModel*`
  scoped to the exact chosen model ARN (never a wildcard) for the operator
  running the batch.
- `web-eval` and `web-refresh` remain manual, matching the current
  deploy-when-needed convention.

## Follow-ups explicitly not built

- LLM-as-judge scoring of report quality.
- Season- or category-level evaluations.
- Serving the agent from AgentCore Runtime for an interactive chat tier — the
  agent module is kept dependency-light so this stays possible, but it needs auth
  (parked tier #2) first.
