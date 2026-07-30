# Spec seed: per-entity aggregates in the AI meet evaluation digest

Status: **not specified yet** — this is the pre-work for a planning session,
written 2026-07-30 so the sizing work isn't repeated. Not a plan, not approved.

Two requests that turn out to be the same shape of work — an aggregate **per
entity within one meet**, precomputed into the digest so the model reports it
rather than derives it. They share a design conversation and one regeneration:

1. **Club performance** — a new section evaluating clubs at the meet.
2. **Multi-title swimmers** — a swimmer who wins several finals is currently
   invisible to the report, even when it is the meet's headline achievement.

Both hinge on the same constraint: **the digest is the model's entire world**,
and `SYSTEM_PROMPT` rule 1 forbids computing a number. Anything the report
should say must be *in* the digest as a value, not inferable from it.

---

# Part 1 — Club performance

## What is wanted
A fifth section in the generated Danish meet report, evaluating **club
performance** at that meet, alongside the existing four (`Samlet niveau`,
`Bredde`, `Fremhævede svømninger`, `Discipliner i bevægelse`).

## What is already in place (checked, not assumed)
- **The SPA needs no change.** `web/src/routes/Meet.svelte:138` renders sections
  generically (`{#each evaluation.sections as s (s.heading)}`), so a fifth
  section appears by itself.
- **A club view exists** — `club_leaderboard` in
  `st-scrape/analytics/views/30_aggregates.sql`: swims, swimmers, podiums,
  total_points, best_points. But it groups by **club × season**, and the digest
  needs club × *meet*. So: a new view (or a digest-local query) is required.

## What makes this a planning job rather than an edit
1. `HEADINGS` is both interpolated into `SYSTEM_PROMPT` *and* the `Literal` in
   the `Section` structured-output schema, so a fifth heading bumps
   **`PROMPT_VERSION` and `SCHEMA_VERSION`** — every meet regenerates.
2. **Grounding.** Per-section contextual grounding at 0.5 punishes a thin
   section: measured 2026-07-30, sections given fewer digest facts scored
   0.25–0.49 and were blocked while the same report's fact-dense sections
   scored 0.85+. The club section must carry enough of its own numbers.
3. **Comparative claims are the whole point of the section and the main
   guardrail risk.** "Bedste klub", "flest podier" is a claim about every club
   that is not named. The *ranking itself must be in the digest* — the model may
   report an order, never derive one.
4. `evaluation/check.py` must license the new club figures, and
   `allowed_numbers` already had to be taught that club *names* carry digits
   ("MK31", "A6 JGI-Swim").
5. Clubs are organisations, not minors — so rule 3's person-protections don't
   transfer. The spec should say plainly what may be said about a club, or the
   section will drift into judging clubs.

## The decision the spec has to make first
**What "club performance" means.** These rank clubs very differently:

| Metric | Bias |
| --- | --- |
| total points | size — the biggest club almost always wins |
| podium count | size, plus depth in strong events |
| entrants | pure size, no performance content at all |
| points per swimmer | favours small, sharp squads; noisy at n=1 |
| best_points | one swimmer's day, not the club's |

Probably two of these together (one volume, one rate), but that is the
conversation to have, not a default to pick.

---

# Part 2 — Multi-title swimmers

## The bug this fixes, with the case that found it
`DM-L/10334` (DM Langbane 2023). **Mathias Christensen won four individual
finals and was second in a fifth** — across three strokes, which is the rare
part; four titles ordinarily requires excelling in at least two disciplines.

| Event | Points | Rank |
| --- | --- | --- |
| 200m IM | 764 | 1 |
| 100m Fly | 729 | 1 |
| 200m Bryst | 725 | 1 |
| 400m IM | 715 | 1 |
| 100m Bryst | 690 | 2 |

**The report does not mention him, and could not have.** Two independent
reasons, and fixing only the first would not help:

1. **He is not in the digest at all.** `_TOP_SWIMS_SQL` is
   `ORDER BY points DESC LIMIT TOP_N` with `TOP_N = 10`
   (`st-scrape/webbuild/digest.py:103,122`). The 10th slot at this meet is 779
   points; his best swim is 764. He falls below the cutoff, so the model never
   saw his name.
2. **The digest has no notion of a title count.** `top_swims` is a flat list of
   individual swims. Nothing counts wins per swimmer, and rule 1 forbids the
   model from computing "four" — so even with all five rows present it could
   only have listed four unrelated-looking swims.

## The systematic bias worth naming
**Ranking by WA points structurally hides exactly this swimmer.** Points run
higher in sprint free and fly than in breast and IM, so a single-event
specialist takes a top-10 slot at 822 while a swimmer winning four titles
across three strokes at 715–764 takes none. *The rarer achievement is the one
the metric filters out.* Raising `TOP_N` mitigates but does not fix this — it
buys a few more rows of the same biased ordering.

## Sketch (to be argued in the spec, not adopted here)
A `multi_title_swimmers` block: per swimmer with `count(rank = 1) >= N` at this
meet — name, club, the title count, the strokes covered, and each winning
event. Precomputed, so the report states the count instead of deriving it.

## Cheaper than Part 1, and worth keeping separate
This one **need not add a section**, and therefore need not bump
`SCHEMA_VERSION`: the existing `Fremhævede svømninger` is already the
named-swimmer section, so new digest facts plus a prompt rule may be enough.
`HEADINGS` is the `Literal` in the structured-output schema — leave it alone
and only `PROMPT_VERSION` moves.

## Decisions the spec has to make
- **Threshold.** 2+ titles is common at a small meet; 3+ is probably the
  interesting line. Should it scale with meet size?
- **Relays.** Do team-medley/relay wins count toward a swimmer's title tally?
  (`top_swims` is individual-only today.)
- **The junior path too.** `_JUNIOR_TOP_SWIMS_SQL` has the same `LIMIT` and the
  same blind spot — a junior sweeping several events is hidden identically.
- **Does the second place belong in it?** "Four wins and a second" is the human
  framing, but a runner-up count is a second derived figure to precompute.
- **Grounding.** A named swimmer with a title count is fact-dense, so this
  should score well — but per rule 3 the prose stays on results only, and many
  of these swimmers are minors.
