# Meet-page race filter — design

**Date:** 2026-07-24
**Status:** approved, ready for implementation plan
**Scope:** `web/` frontend only. No backend, webbuild, curate, or data-pipeline change.

## Problem

The meet details page (`web/src/routes/Meet.svelte`) renders every race of a meet
as one long flat list under the `Løb` heading. Large meets have dozens of races
(all strokes × distances × genders + relays), so finding a specific one means
scrolling the whole list.

## Goal

Add a filter bar on top of the race list that narrows it by **discipline**
(individual stroke *or* relays) and by **gender**. Both apply to the
already-loaded list; nothing is re-fetched.

## Why frontend-only

Each race object returned by `getRaces()` already carries every field the filter
needs — confirmed in `st-scrape/webbuild/queries.py`:

- `stroke` — Danish: `Fri`, `Ryg`, `Bryst`, `Fly`, `IM` (individual), `HM` (team medley, always a relay)
- `is_relay` — `true` / `false`
- `gender` — `M` / `F` / `X` (X = mixed relay)

So no JSON-shape, webbuild, or CDK change is required.

## Filter model

Two **single-select** dimensions, AND-combined:

### Discipline (mutually exclusive)
- `Alle` (default) — no discipline filter.
- One chip per **individual** stroke present in the meet, in canonical order
  `Fri, Ryg, Bryst, Fly, IM`. Selecting a stroke shows that stroke's individual
  races (`stroke === value && !is_relay`), across all genders (subject to the
  gender filter).
- `Stafet` — shown **only if the meet has any relay**. Selecting it shows all
  relays (`is_relay === true`) regardless of their stroke (this is where `HM`
  and relay `Fri` land).

Strokes and relays are mutually exclusive because discipline is a single-select:
you pick a stroke *or* `Stafet` *or* `Alle`, never a combination.

### Gender
- `Alle` (default) — no gender filter.
- `Herrer` (M) · `Damer` (F) · `Mix` (X) — one chip per gender value present in
  the meet. Applies on top of the discipline filter.

Note: a mixed (`X`) race only ever exists as a relay, so selecting an individual
stroke + `Mix` legitimately yields an empty list. That is acceptable and shows
the empty-state message.

## Dynamic options

Chips are derived from **this meet's own races**, not a fixed list:
- discipline chips = `Alle` + individual strokes present (canonical order) +
  `Stafet` iff any race `is_relay`.
- gender chips = `Alle` + genders present (order `M, F, X`).

A meet with no relays shows no `Stafet` chip; a men-only meet shows no `Damer`
chip. No dead options.

## Architecture

New module `web/src/lib/raceFilter.js` — pure, framework-free, unit-testable:

- `filterRaces(races, { discipline, gender })` → filtered array.
  - discipline: `'all'` → keep all; `'Stafet'` → `r.is_relay`; else
    `r.stroke === discipline && !r.is_relay`.
  - gender: `'all'` → keep all; else `r.gender === gender`.
  - AND-combined.
- `disciplineOptions(races)` → ordered list of discipline values present
  (`['all', ...strokesInCanonicalOrder, 'Stafet'?]`).
- `genderOptions(races)` → ordered list of gender values present
  (`['all', ...gendersInOrder]`).

`Meet.svelte` changes:
- Two `$state` selections: `discipline = 'all'`, `gender = 'all'`.
- `$derived` filtered list via `filterRaces`; `$derived` option lists via the
  derivers above.
- Filter bar rendered between the `Løb` heading and the list: two groups of
  `<button aria-pressed={selected}>` chips. Gender chips labelled
  `Alle / Herrer / Damer / Mix` via a small value→label map; discipline chips
  show the stroke value as-is, and `Stafet` for relays.
- Race-count `{n} løb` shown next to the heading so the filter's effect is
  visible.
- Empty filtered result → `Ingen løb matcher filteret.` (distinct from the
  existing `Ingen løb fundet.` no-data state).

Styling reuses existing CSS custom properties (`--surface`, `--border`,
`--accent`, spacing vars); chip active state uses `--accent`.

## Testing (TDD)

`web/tests/raceFilter.test.js` (new):
- `filterRaces` — a stroke keeps only that stroke's individual races and excludes
  relays; `Stafet` keeps only relays (incl. `HM`) and excludes individual;
  gender narrows correctly; discipline+gender combined; stroke+`Mix` → empty.
- `disciplineOptions` — canonical stroke order; `Stafet` present iff a relay
  exists; absent otherwise.
- `genderOptions` — only present genders, in `M, F, X` order.

`web/tests/routes.render.test.js` (extend, using a fixture with mixed
individual + relay + both genders):
- discipline chips render only for present values (no `Stafet` when no relay);
- clicking `Bryst` narrows visible rows to bryst individual races;
- clicking `Stafet` shows the relay row and hides individual races.

## Explicitly out of scope

- URL / query-string persistence (local component state only; router is
  hash-only today).
- Multi-select within a dimension.
- Distance / course filters.
- Any change to the race JSON, webbuild, curate, or CDK.

These can be added later without reworking this design.
