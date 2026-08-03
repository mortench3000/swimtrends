# Per-entity aggregates in the AI meet evaluation digest

Status: **approved design**, 2026-08-03. Supersedes the sizing notes in
[`2026-07-30-digest-entity-aggregates-seed.md`](2026-07-30-digest-entity-aggregates-seed.md),
which stays for the measurements behind the decisions here.

Two changes to the generated Danish meet report, shipped together because they
share one batch regeneration:

1. **`Klubberne`** — a fifth section, a club medal table for the meet.
2. **Multi-title swimmers** — a swimmer who wins three or more individual
   finals is currently absent from the digest and therefore unmentionable, even
   when it is the meet's headline achievement.

Both are the same shape of work: an aggregate **per entity within one meet**,
precomputed into the digest. The digest is the model's entire world and
`SYSTEM_PROMPT` rule 1 forbids computing a number, so anything the report may
say has to be *in* the digest as a value.

## The bug behind Part 2

`DM-L/10334` (DM Langbane 2023): Mathias Christensen won **four individual
finals across three strokes** — 200m IM (764), 100m Fly (729), 200m Bryst
(725), 400m IM (715) — and was second in the 100m Bryst. The report never
mentions him, for two independent reasons:

- `_TOP_SWIMS_SQL` is `ORDER BY points DESC LIMIT 10`, and the 10th slot at
  that meet is 779 points. He is not in the digest at all.
- Nothing in the digest counts wins per swimmer, so even with all five rows
  present the model could only have listed four unrelated-looking swims.

Ranking by WA points structurally hides exactly this swimmer: points run higher
in sprint free and fly than in breast and IM, so a single-event specialist
takes a top-10 slot at 822 while four titles across three strokes at 715–764
takes none. **Raising `TOP_N` is not the fix** — it buys more rows of the same
biased ordering. A precomputed per-swimmer aggregate is.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Club metric | Medal table: titles, then podiums | One precomputed order. The model may report an order, never derive one. Biased toward big clubs — at a national championship that is the honest story, and it is how the sport reports itself. |
| Club section placement | A real fifth section, not a paragraph inside `Bredde` | Grounding is scored per section, so a mixed section's verdict rides on its weaker half. The `SCHEMA_VERSION` bump costs one `Literal` edit, and the batch regenerates anyway. |
| Title threshold | `titles >= 3`, fixed | Two titles is ordinary at a DM; three is the interesting line. No scaling with meet size (YAGNI). |
| Per-win detail | Yes — `wins[{event, points}]` | Fact density is what grounding rewards: sections given few digest facts scored 0.25–0.49 and were blocked while fact-dense sections in the same report scored 0.85+. |
| Runner-up count | Excluded | "Four wins and a second" needs a second derived figure for one phrase. |
| Relays | Excluded — not a choice | Relay rows carry `swimmer_id = NULL` and the scraper discards per-member columns, so a relay win is not attributable to a swimmer. |
| New analytics views | None | Both blocks are digest-local SQL, like every other block in `digest.py`. A view with one consumer is an abstraction with no second reader. |

## Title and podium definitions

Reused from `medal_count` (`analytics/views/50_field_evolution.sql:25`), which
already settles that a heat win is not a medal:

```
senior:  phase IN ('final', 'timed_final') AND class = 'open'
         title  = rank = 1        podium = rank IN (1, 2, 3)
junior:  junior_championship (already phase- and class-scoped)
         title  = junior_rank = 1  podium = junior_rank IN (1, 2, 3)
```

Dead heats share a `rank`, so two swimmers can both hold one title. Deliberate,
and the same behaviour as `medal_count`.

Counted **per result row**, not per event — so a dead-heated event contributes
two titles to the table. Both queries sit on `results_by_category` /
`junior_championship`, which are built on `individual_results`: relays and DQs
are already excluded, so a club's titles are its **individual** titles only.

## Digest blocks

Added to the dict returned by `webbuild/digest.py:build`. Each has a senior and
a junior query, selected by the existing `junior` flag, exactly as `top_swims`
and `by_stroke` already are.

### `clubs`

Top 5 clubs. Fields: `club`, `swimmers`, `titles`, `podiums`, `rank`.

`ORDER BY titles DESC, podiums DESC, swimmers DESC, club` — **a total order**,
because a `LIMIT` over a partial order silently changes the digest between two
builds of unchanged data, and the digest is part of the evaluation cache key
(see the comment above `_TOP_SWIMS_SQL` and the `digest-must-be-deterministic`
finding). `swimmers` sits in the chain so that a meet whose curated data holds
no finals at all still ranks by something meaningful rather than alphabetically.

`rank` is emitted so the report can state a position without counting rows.

### `multi_title_swimmers`

Every swimmer with `titles >= 3` at this meet. **No `LIMIT`** — a cutoff is the
bug being fixed, and a meet yields only a handful of rows.

Fields: `name`, `club`, `titles`, `strokes[]`, `wins[{event, points}]`.

`strokes[]` is the distinct Danish stroke names of the titles, in the canonical
order used everywhere else in the project — `Fri, Ryg, Bryst, Fly, IM` — not
alphabetical and not order of appearance, both of which vary with scan order.
`wins[]` is ordered `points DESC, event`.

`ORDER BY titles DESC, name, swimmer_id`. `swimmer_id` is the final tiebreak so
the order is total even for two swimmers with the same name; it is **not**
emitted (the digest names no ids today).

An empty list is normal — a meet where nobody won three finals says nothing
about multi-title swimmers, which is correct, not a failure.

## Prompt and schema

`evaluation/agent.py`:

- `HEADINGS` gains **`Klubberne`** as the fifth and last heading. It feeds both
  `SYSTEM_PROMPT` and the `Literal` in the `Section` schema, and
  `MeetEvaluation.all_four_in_order` compares against the same tuple — one edit
  reaches all three. The validator's name and message are updated to say five.
- `PROMPT_VERSION` 6 → 7, `SCHEMA_VERSION` 2 → 3.
- Word budget 250 → 300 words, still "about".
- **Rule 3** licenses names from `digest.top_swims` only today. It must license
  `digest.multi_title_swimmers` as well, or the intended report is an
  unlicensed-name violation. Everything else in rule 3 is unchanged: results
  facts only, no potential, technique, body, health, age, training or
  schooling, no criticism of a named person, many of them are minors.
- **New rule (clubs).** The `Klubberne` section reports which clubs led the
  meet and with what figures. The report may state the order in `digest.clubs`
  and the figures in it. It may not judge a club, rank a club that is not in the
  table, imply anything about clubs outside the top 5, or say anything about a
  club beyond those numbers. Clubs are organisations, so rule 3's
  person-protections do not apply — but rule 6 still does: club names are not
  locations, and no explanation may be offered for a club's position.
- A precomputed `titles` count means the model must be told to quote it rather
  than count. The `misattributed` retry prompt (`agent.py:322`) currently says
  *"never total up a swimmer's wins"*, which is now wrong: it becomes "take a
  swimmer's title count from `digest.multi_title_swimmers[].titles` — never
  count wins yourself".

## `evaluation/check.py`

Three functions read `top_swims` exclusively and each is wrong once names and
figures also live elsewhere:

1. **`allowed_numbers`** licenses club-name digits from `top_swims[].club` only.
   Club names carry digits ("Svømmeklubben MK31", "A6 JGI-Swim"), so a club in
   the new table would be reported as a fabricated number and spend the meet's
   rewrite on a false positive — the failure that left `DM-K/7088`
   unpublished. Extend to `clubs[].club` and `multi_title_swimmers[].club`.
   Still digit runs from club names only; the rest of the digest's free text
   stays unlicensed.
2. **`points_owners`** binds a points value to the swimmer who owns it. Add
   `multi_title_swimmers[].wins[].points`, otherwise the newly nameable
   swimmers' figures are the only ones in the report nothing protects.
3. **`genders_in_digest`** maps (distance, stroke) to the genders the digest
   holds. Add `wins[].event`, which strictly widens what `check_genders`
   judges — an event absent from the digest is unjudged, never wrong.

`titles`, `podiums` and `swimmers` need no licensing work: `_walk` already
walks the whole digest, so any integer in it is licensed. They are aggregates
rather than one swimmer's result, so they also belong in `_aggregate_values`,
which keeps a club's count from being mistaken for a swimmer's points in
`check_attribution`.

## Affected paths, explicitly

| Path | Change |
| --- | --- |
| `st-scrape/webbuild/digest.py` | Two new query pairs (senior + junior), two new keys in `build`'s return |
| `st-scrape/evaluation/agent.py` | Fifth heading, both versions, rules 3 + new club rule, word budget, misattribution retry text |
| `st-scrape/evaluation/check.py` | `allowed_numbers`, `points_owners`, `genders_in_digest`, `_aggregate_values` |
| `st-scrape/tests/test_digest.py` | New blocks, senior + junior, ties, empty case |
| `st-scrape/tests/test_evaluation_check.py` | Club digits, `wins` attribution, gender flip on a win |
| `st-scrape/tests/test_evaluation_agent.py` | Five headings in order |
| `web/` | **No change.** `Meet.svelte:138` renders sections generically, `prerender.mjs:82` maps them all, `seo.js:53` reads `sections[0]`, which is still `Samlet niveau`. Meet shells pick up the new prose on the next build after the eval deploy. |
| `swimtrends-app/` | **No change.** No new guardrail policy, so no new guardrail version. |
| `analytics/views/*.sql` | **No change.** No new view. |
| Curated zone / Parquet | **No change.** Nothing is recomputed upstream of the digest. |

## Tests

TDD, failing first. Fixtures are `tests/analytics_fixtures.build_curated` +
`analytics.loader.create_views` — in-memory DuckDB, no S3, no model.

- `clubs`: ranking order; that a heat win is not a title; `class='open'` only;
  top-5 truncation; the all-zero-titles meet still ordered by `swimmers`.
- `multi_title_swimmers`: a 3-title swimmer present with correct `strokes` and
  `wins`; a 2-title swimmer absent; no rows when nobody qualifies; a dead heat
  giving two swimmers the same title.
- Junior path: both blocks built from `junior_championship` when the meet is a
  combined DMJ-L meet.
- Determinism: two builds of the same fixture give byte-identical
  `canonical_json` (this is what protects the cache key).
- `check.py`: a club with digits in its name passes; a `wins` points value
  credited to the wrong name is caught; a gender flip on a `wins` event is
  caught.
- `agent.py`: `MeetEvaluation` rejects four sections and accepts the five in
  order.

**Acceptance case:** built from the real `DM-L/10334` shape, Mathias
Christensen appears in `multi_title_swimmers` with `titles = 4` and three
strokes — the swimmer the current digest cannot see.

## Rollout

1. Merge. Both version bumps invalidate all 41 cache entries.
2. `make web-eval` — the whole batch regenerates (~$0.30). Expect a few
   grounding blocks; the verdict is stochastic, so **re-roll, never tighten the
   prompt** to chase a threshold.
3. `make web-eval-deploy`, then `make web-eval-verify`.
4. **No `make web-refresh`.** Only `*/evaluation.json` changes.

## Out of scope

- Runner-up counts, and any second club ranking (points-per-swimmer, medians).
- Raising `TOP_N`, or changing `top_swims` at all.
- Relay member names — a separate parked item needing a scraper change and a
  full re-scrape.
- Club aggregates anywhere outside the digest (no SPA club page, no new view).
