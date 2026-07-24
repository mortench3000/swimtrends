# Relays on Meet Pages — Design

**Date:** 2026-07-23
**Status:** Approved (brainstorm complete)

## Problem

Team relays are currently excluded from every meet detail page. The exclusion
is deliberate — `individual_results` (`analytics/views/00_base.sql:25`) drops
relay rows (`NOT is_relay`) alongside DQ and null-swimmer rows, and every
webbuild query reads through `results_by_category`, which inherits that filter.

Relays *are* scraped, curated, scored, and stored (in `obt_result`); they are
only hidden at the analytics-view layer. We want them visible on meet pages —
in the race list and as their own race-detail page — **while still excluding
DQs and para results.**

## Data facts (verified against scraped meets 10334 / 10340)

A relay race row:
- `type` is always `Timed final` → maps to `phase='timed_final'`. **No heats,
  therefore no A-final cut-line.**
- `distance` is **per-leg** (100 for a 4×100), `relay_count` is the leg count
  (4), `stroke` is `Fri`/`HM`/etc. `HM` (team medley) never collides with the
  individual `IM`.
- `Name` is the team entry (e.g. "Aalborg Damer 1"); `club` is the club
  ("Aalborg Svømmeklub"). `Podium.svelte` already shows name + club.
- `swimmer_id` is **null**. `SwimmerLink.svelte` already renders plain text when
  `id` is null, so relay podiums need no swimmer-link changes.
- Relay **member names are NOT captured** — the scraper stores only the team
  row and discards the per-member `Svommer`/`Tur` columns
  (`scrape_races.py:497-499`). Showing the four swimmers is therefore **out of
  scope** for this work (see Deferred).

## Key design decision

**Do NOT widen `individual_results`.** Relay rows have `swimmer_id IS NULL` and
relay-specific points; folding them into `individual_results` would silently
pollute every downstream aggregate — `medal_count`, `elite_median_points`,
junior bands, `event_standard_by_season`, meet median points. Instead add a
**narrow parallel relay path** that surfaces relays only where the meet pages
list and expand races. All individual analytics stay byte-for-byte unchanged.

DQ and para stay excluded on the relay path via the same filters used
everywhere else: `NOT is_dq` and `class = 'open'`.

## race_key collision

A 4×100 Fri relay stores `distance=100`, so its `(gender, distance, stroke,
course)` tuple `(F,100,Fri,LCM)` is **identical** to the individual 100 Fri.
`race_key` must disambiguate. Relay keys become self-describing:

- individual: `F-100-Fri-LCM` (unchanged — no link migration)
- relay: `F-4x100-HM-LCM` (`{gender}-{relay_count}x{distance}-{stroke}-{course}`)

Individual keys never contain `Nx`, so the two spaces cannot collide, and the
key is filename-safe for the per-race JSON.

## Scope by layer

### Analytics SQL
- `00_base.sql`: add `relay_results` = `SELECT * FROM results WHERE is_relay AND
  NOT is_dq` (mirror of `individual_results`; keeps null `swimmer_id`).
- new `55_relays.sql`:
  - `relay_results_by_category` — relays unnested over `dim_meet.category`,
    mirroring `results_by_category` (webbuild is category-scoped).
  - `relay_event_standard_by_season` — best / median / top8-avg / swims per
    season, keyed on the relay event `(category, season, course, gender,
    distance, stroke, relay_count)`. **No cut-line view** (relays are timed
    finals).

### webbuild
- `shape.py`: `race_key(gender, distance, stroke, course, relay_count=1)` — emit
  the `Nx` form when `relay_count > 1`.
- `queries.py`:
  - `build_races`: UNION relay events from `relay_results_by_category`
    (contestants = team count, winner = winning team + time). Race dicts carry
    `relay_count`.
  - meet **event count** (`facts.events`, `season_comparison[].events`,
    `build_meets[].events`) includes relay events. Entrants, clubs, median
    points stay individual-only (relays have no per-swimmer entrants; relay
    points would skew the median). Additive relay-event counts merged in Python,
    following the existing `elite_median_points` merge pattern — no rewrite of
    the individual SQL.
  - `build_race`: when `relay_count > 1`, route to relay facts (contestants =
    teams, winning_time, winner_points, median_cs, spread_1_last_cs, dsq via an
    `is_relay AND is_dq` count) + team podium + relay season-comparison (from
    `relay_event_standard_by_season`, cut-line field null). Emit `is_relay:
    true`. Omit cut-line, spread-1-8, and junior facts (all heats/swimmer based).
- `build.py`: `build_all` passes `relay_count` through to `build_race`.

### Frontend
- `Race.svelte`: on `race.is_relay`, drop the Junior tile, the A-final-grænse
  (cut-line) tile, and the Spredning-1.–8. tile; drop the cut-line trend chart.
  Best / median / swims charts and the podium render unchanged.
- `Meet.svelte`: relay race rows say "hold" instead of "deltagere" for the
  count (uses an `is_relay` flag now present on the race-list rows).

### Tests
- Python (pytest): relay rows go in a **separate** fixture, never the shared
  `curated_con()` — existing tests assert `events==2` / `entrants==22` and must
  stay valid. Cover: `relay_results` keeps relays / drops DQ; category unnest;
  `relay_event_standard_by_season`; `race_key` relay form; `build_races` lists a
  relay with team winner + `is_relay`; `build_meets`/`build_meet` event count
  includes the relay; `build_race` returns a team podium, relay DSQ, `is_relay`,
  and trends with null cut-line.
- JS (vitest): extend `routes.render.test.js` to render `Race.svelte` with a
  relay payload — no cut-line/junior tiles, podium shows team name as plain
  text (no `<a>` swimmer link).

## Deferred (separate branch)
Relay **member names** in a tooltip: requires a scraper change to parse the
discarded member column, a `relay_members` schema field on the obt row, a full
sequential re-scrape/backfill of all meets, plus curate + webbuild + a frontend
tooltip. Feasible (the names are in HTML the scraper already fetches) but its
cost is the backfill, and it is independent of this work.

## Out of scope / unchanged
- Individual analytics, championship/junior/medal views, elite median.
- Curate and the scraper (relays already flow through and are scored).
- The `_MEET_FACTS_SQL` entrants/clubs/median semantics.
