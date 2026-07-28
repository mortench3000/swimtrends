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
- Every number in the text machine-verifiable against the digest the meet's own
  data produced. (This was originally "against the data already on the page" —
  struck during implementation: the digest deliberately carries a sixth season of
  history and per-stroke medians that the page does not render, so the check is
  against the digest and the page copy says so.)
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
 │      key    = sha256(canonical_json({digest, prompt_v, schema_v, model_id,
 │                                      guardrail_id, guardrail_v, max_tokens}))
 │      s3://swimtrends-meet-data/evaluations/<cat>/<meet>/<key>.json
 │        hit  → reuse verbatim (no model call, no cost)
 │        miss → Strands agent → number check → ApplyGuardrail → store under key
 │      write <out>/<cat>/<meet>/evaluation.json  (else delete a stale one)
 └─ aws s3 sync web/public/data … --delete    # picks up evaluation.json
```

`web-refresh` syncs with `--delete`, so `evaluation.json` must exist in
`web/public/data` before the sync — hence the evaluation step runs between
`webbuild` and the sync, in the same target. A standalone `make web-eval`
target exists for iterating without a full 50-minute rebuild.

The evaluation step opens its own `analytics.loader.connect()`. The digest
queries are cheap aggregates (seconds per meet), so it does not piggyback on
webbuild's slow per-race loop.

### Why the cache key includes prompt, schema, model and guardrail

Keying on the data alone would let a prompt tweak silently change published text
on the next refresh. Including `prompt_version`, `schema_version`, `model_id`,
the guardrail's id and numbered version, and the token budget means:

- Unchanged inputs → the stored text is reused forever; no drift between refreshes.
- A deliberate prompt or model change → every meet regenerates, visibly and on purpose.
- A **tightened guardrail** likewise regenerates every meet. The guardrail is
  half the safety envelope, so text written under a laxer policy must not keep
  being republished unexamined after the policy moves.
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
                       "median_points", "elite_median_points"}, … up to 6 ],
  "top_swims":      [ {"name", "club", "event", "time", "points", "rank"}, … 10 ],
  "by_stroke":      [ {"stroke", "dist_group", "median_points", "prev5_median",
                       "delta"}, … ],
  "derived":        {"<metric>_vs_prev5_pct": …},   # rounded % deltas
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
- `derived` and `by_stroke[].delta` are **precomputed** so the report can quote a
  percentage or a stroke's movement without the model doing arithmetic — the
  prompt forbids calculating, so anything not precomputed here can only be
  described in words. See the number check below.
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

> **Corrected during implementation.** This section originally also claimed
> "model access is verified before the batch runs". There is no pre-flight probe,
> and none was added: a not-enabled model raises `AccessDeniedException` on every
> meet and the run exits non-zero having published nothing, which is the same
> safe outcome as a probe, only noisier. `cache_prompt="default"` was also
> dropped — strands deprecated it, and at ~800 tokens `SYSTEM_PROMPT` is below
> the minimum cacheable prompt length for these models, so it could never have
> produced a hit.

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

One Bedrock Guardrail, defined in `swimtrends-app`, applied at a **numbered
version — never `DRAFT`**:

- **Content filters**, explicitly configured (there is no such thing as a
  service default: omit `content_policy_config` and the guardrail has no content
  filters at all). HATE / INSULTS / SEXUAL at `MEDIUM` input and `HIGH` output;
  VIOLENCE / MISCONDUCT at `MEDIUM` both ways; `PROMPT_ATTACK` at `MEDIUM` on
  input only. Output strengths are the ones that matter — the input is our own
  prompt plus a numeric digest, the output is what gets published next to a
  minor's name. PROMPT_ATTACK is deliberately not `HIGH`: Bedrock evaluates the
  whole untagged input, including our instruction-dense system prompt, so `HIGH`
  risks blocking every meet.
- **Denied topics for all four blocked categories above** — `TalentProjection`,
  `PhysiqueAndHealth`, `PersonalCriticism`, `PersonalDetails`. The fourth was
  added during implementation: the first three left age/school/personal detail
  enforced by the system prompt alone, and since the guardrail exists precisely
  because the model may not follow the prompt, the least-protected category was
  the one about minors' identifying details. `"Hun er 16 år og går i 9. klasse på
  Ordrup Skole."` trips none of the first three.
- **No PII entity filter, deliberately.** Swimmer names are already published on
  the site as result rows and are wanted in the prose, so a `NAME` filter would
  defeat the feature; an `AGE` filter would risk flagging legitimate aggregate
  statements (the digest carries a `juniors` count, and the junior categories are
  defined by an age band). A denied topic targets the harm without breaking the
  data.
- **Contextual grounding check** with the digest as `grounding_source`, the
  instruction the report answers as `query`, and the report as the guarded
  content. Thresholds 0.85 grounding / 0.5 relevance. Grounding runs on
  `source='OUTPUT'` only. The report is well under the 5,000-character response
  limit and the digest well under the 100,000-character source limit.

> **Corrected during implementation: how the guardrail is applied.** The original
> design applied it *inline on the Converse call* only. That cannot work here.
> Structured output is a forced tool call in strands, so the prose comes back
> inside `toolUse.input` rather than a text block — a traced production call
> returned no output assessment at all — and the grounding source and query must
> be `qualifiers` on guard content blocks, which a plain-string prompt cannot
> carry. So the inline guardrail assesses the input, and the *published text* is
> checked by an explicit `ApplyGuardrail` call (`OutputGuard`) with three content
> blocks: the digest qualified `grounding_source`, the fixed Danish instruction
> qualified `query`, and the report unqualified. That call is where the denied
> topics and the grounding check actually run — one extra call per generated
> meet, none on a cache hit. Until it existed, contextual grounding never ran at
> any threshold, so 0.85 is an untuned starting point.

A guardrail block on either call is a failure, not a fallback: the meet is
skipped and nothing is written to the cache.

### Number check (`check.py`)

The deterministic half of "don't make things up", and cheap enough to keep
forever:

1. Extract every numeric literal from the report text.
2. Each must appear in the digest — times normalised to `m:ss.cc`, integers
   compared exactly. **Percentages are licensed only when they are literally in
   `digest.derived`**; nothing is licensed for being *derivable*, which would
   re-open the arithmetic the prompt forbids. Same for a stroke's movement, which
   must be `by_stroke[].delta`.
3. Fail → one retry with the offending **numbers** quoted back to the agent (not
   the sentences: the numbers are what the check knows, and naming them tells the
   model precisely what to drop).
4. Fail again → log and skip the meet.

The cache put happens **only after the check passes** and only after the
`ApplyGuardrail` check above, so a partially-bad report is never published.

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
      Den er eksperimentel og en fortolkning — ikke fakta. Alle tal stammer fra
      stævnets egne data og er maskinelt kontrolleret.
      Genereret {evaluation.generated_at} · {evaluation.model_label}
    </p>
  </details>
{/if}
```

- **Collapsed by default** (`<details>`, no `open`) — native disclosure, no JS.
- **Two-layer disclosure.** The summary line always reads
  "AI-genereret, eksperimentelt" even when collapsed; the footer inside carries
  the full statement that this is an interpretation rather than fact, that the
  numbers come from the meet's own data and are machine-checked, and which model
  produced it on which date. Publishing machine-written prose about named people
  without saying so plainly is the one thing in this design that would be
  indefensible.
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

- No `evaluation.json` for that meet → the section is absent → the rest of the
  page renders exactly as today. A file an earlier run left there is **deleted**,
  so a skip can never republish text written from a superseded digest.
- The **cached** report on S3 is never deleted by a failed regeneration, and the
  bucket is versioned, so re-running restores the section without a model call.
- `webbuild` itself never blocks on Bedrock: the 50-minute rebuild is a separate
  step that completes before the evaluation step starts.

> **Corrected during implementation.** This section originally also promised that
> `web-refresh` "never fails because of" Bedrock. It can, deliberately: a run that
> skips more meets than it writes exits non-zero, which stops `make` before the
> `--delete` sync. That is the point — a systemic failure would otherwise strip
> every skipped meet's section from the live site. A minority of skips in a
> healthy batch still exits 0. The cost is that a failed run leaves the *local*
> `web/public/data` short those sections while the live site stays untouched.

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
- No new Lambda, container, endpoint, or IAM role. The operator running the batch
  needs `bedrock:InvokeModel*` scoped to the exact chosen model /
  inference-profile ARN (never a wildcard), `bedrock:ApplyGuardrail` on the
  guardrail ARN — required both to invoke a model with a guardrail and for the
  explicit output check — and `s3:GetObject`/`s3:PutObject` under the
  `evaluations/` prefix.
- `web-eval` and `web-refresh` remain manual, matching the current
  deploy-when-needed convention.

## Follow-ups explicitly not built

- LLM-as-judge scoring of report quality.
- Season- or category-level evaluations.
- Serving the agent from AgentCore Runtime for an interactive chat tier — the
  agent module is kept dependency-light so this stays possible, but it needs auth
  (parked tier #2) first.
