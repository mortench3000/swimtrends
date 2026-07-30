# Spec seed: a club-performance section in the AI meet evaluation

Status: **not specified yet** — this is the pre-work for a planning session,
written 2026-07-30 so the sizing work isn't repeated. Not a plan, not approved.

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
