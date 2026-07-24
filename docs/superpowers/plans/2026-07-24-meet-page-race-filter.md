# Meet-page race filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a filter bar on the meet details page that narrows the race list by discipline (individual stroke *or* relays) and by gender, filtering the already-loaded data with no re-fetch.

**Architecture:** A new pure, framework-free module `web/src/lib/raceFilter.js` holds the filter logic and option-derivation (unit-testable without rendering). `web/src/routes/Meet.svelte` holds two single-select `$state` selections, derives the chip options and the filtered list from that module, and renders two chip groups above the list.

**Tech Stack:** Svelte 5 (runes: `$state`, `$derived`), Vite, Vitest + @testing-library/svelte. No new dependencies.

## Global Constraints

- No new npm dependency — filter is plain JS + Svelte runes.
- Svelte 5 runes only (`$state`/`$derived`), matching the existing components.
- UI copy is Danish; stroke values are Danish (`Fri`, `Ryg`, `Bryst`, `Fly`, `IM`, `HM`).
- Frontend-only: no change to the races JSON, webbuild, curate, or CDK.
- Match surrounding style in `Meet.svelte`; reuse existing CSS custom properties (`--surface`, `--border`, `--accent`, `--muted`, `--text`, spacing vars).
- Run tests from `web/` with `npm test` (vitest).

---

### Task 1: Pure filter + option-derivation module

**Files:**
- Create: `web/src/lib/raceFilter.js`
- Test: `web/tests/raceFilter.test.js`

**Interfaces:**
- Consumes: nothing (pure functions over the race array shape from `getRaces()`; each race has `stroke`, `is_relay`, `gender`).
- Produces:
  - `filterRaces(races, { discipline, gender }) → Race[]`
  - `disciplineOptions(races) → string[]` (e.g. `['all','Fri','Bryst','Stafet']`)
  - `genderOptions(races) → string[]` (e.g. `['all','M','F','X']`)

- [ ] **Step 1: Write the failing test**

Create `web/tests/raceFilter.test.js`:

```js
import { expect, test } from 'vitest'
import { filterRaces, disciplineOptions, genderOptions } from '../src/lib/raceFilter.js'

const races = [
  { race_key: 'M-100-Fri',   stroke: 'Fri',   gender: 'M', is_relay: false },
  { race_key: 'F-200-Bryst', stroke: 'Bryst', gender: 'F', is_relay: false },
  { race_key: 'M-200-Bryst', stroke: 'Bryst', gender: 'M', is_relay: false },
  { race_key: 'X-4x100-HM',  stroke: 'HM',    gender: 'X', is_relay: true  },
  { race_key: 'M-4x100-Fri', stroke: 'Fri',   gender: 'M', is_relay: true  },
]

test('discipline=all gender=all keeps everything', () => {
  expect(filterRaces(races, { discipline: 'all', gender: 'all' })).toHaveLength(5)
})

test('a stroke keeps only that stroke and excludes relays', () => {
  const out = filterRaces(races, { discipline: 'Bryst', gender: 'all' })
  expect(out.map((r) => r.race_key)).toEqual(['F-200-Bryst', 'M-200-Bryst'])
})

test('Stafet keeps only relays regardless of stroke', () => {
  const out = filterRaces(races, { discipline: 'Stafet', gender: 'all' })
  expect(out.map((r) => r.race_key)).toEqual(['X-4x100-HM', 'M-4x100-Fri'])
})

test('gender narrows within a discipline', () => {
  const out = filterRaces(races, { discipline: 'Bryst', gender: 'M' })
  expect(out.map((r) => r.race_key)).toEqual(['M-200-Bryst'])
})

test('stroke + Mix (X) yields empty (X only exists as relay)', () => {
  expect(filterRaces(races, { discipline: 'Fri', gender: 'X' })).toHaveLength(0)
})

test('disciplineOptions lists present individual strokes in canonical order then Stafet', () => {
  expect(disciplineOptions(races)).toEqual(['all', 'Fri', 'Bryst', 'Stafet'])
})

test('disciplineOptions omits Stafet when no relay present', () => {
  const noRelay = races.filter((r) => !r.is_relay)
  expect(disciplineOptions(noRelay)).toEqual(['all', 'Fri', 'Bryst'])
})

test('genderOptions lists present genders in M,F,X order', () => {
  expect(genderOptions(races)).toEqual(['all', 'M', 'F', 'X'])
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- raceFilter`
Expected: FAIL — `raceFilter.js` does not exist / functions not defined.

- [ ] **Step 3: Write minimal implementation**

Create `web/src/lib/raceFilter.js`:

```js
// Canonical order for the discipline chips. Individual strokes only; relays are
// collapsed into the single 'Stafet' option regardless of their stroke (Fri/HM…).
const STROKE_ORDER = ['Fri', 'Ryg', 'Bryst', 'Fly', 'IM']
const GENDER_ORDER = ['M', 'F', 'X']

// discipline: 'all' | 'Stafet' | <stroke>.  gender: 'all' | 'M' | 'F' | 'X'.
export function filterRaces(races, { discipline = 'all', gender = 'all' } = {}) {
  return races.filter((r) => {
    if (discipline === 'Stafet') {
      if (!r.is_relay) return false
    } else if (discipline !== 'all') {
      if (r.is_relay || r.stroke !== discipline) return false
    }
    if (gender !== 'all' && r.gender !== gender) return false
    return true
  })
}

export function disciplineOptions(races) {
  const present = new Set(races.filter((r) => !r.is_relay).map((r) => r.stroke))
  const opts = ['all', ...STROKE_ORDER.filter((s) => present.has(s))]
  if (races.some((r) => r.is_relay)) opts.push('Stafet')
  return opts
}

export function genderOptions(races) {
  const present = new Set(races.map((r) => r.gender))
  return ['all', ...GENDER_ORDER.filter((g) => present.has(g))]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npm test -- raceFilter`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/raceFilter.js web/tests/raceFilter.test.js
git commit -m "feat(web): pure race-filter helpers for meet page"
```

---

### Task 2: Wire the filter bar into the meet page

**Files:**
- Modify: `web/src/routes/Meet.svelte` (script + the `Løb` section markup at lines 120-136, plus styles)
- Create: `web/tests/fixtures/races.filter.json`
- Modify: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: `filterRaces`, `disciplineOptions`, `genderOptions` from Task 1.
- Produces: nothing consumed by later tasks (terminal task).

- [ ] **Step 1: Write the failing test**

Create `web/tests/fixtures/races.filter.json` (individual Fri M, individual Bryst F, a mixed relay):

```json
{
  "category": "DM-L",
  "meet_id": "M2026",
  "races": [
    {
      "race_key": "M-100-Fri-LCM",
      "label": "Mænd 100m Fri",
      "gender": "M", "distance": 100, "stroke": "Fri", "course": "LCM",
      "is_relay": false, "contestants": 28,
      "winner_name": "Magnus Jensen", "winning_time": "00:48.32"
    },
    {
      "race_key": "F-200-Bryst-LCM",
      "label": "Kvinder 200m Bryst",
      "gender": "F", "distance": 200, "stroke": "Bryst", "course": "LCM",
      "is_relay": false, "contestants": 24,
      "winner_name": "Lena Andersen", "winning_time": "02:25.18"
    },
    {
      "race_key": "X-4x100-HM-LCM",
      "label": "Mix 4x100m HM",
      "gender": "X", "distance": 100, "stroke": "HM", "course": "LCM",
      "relay_count": 4, "is_relay": true, "contestants": 6,
      "winner_name": "Aalborg 1", "winning_time": "03:45.10"
    }
  ]
}
```

Add to `web/tests/routes.render.test.js` — extend the imports at the top and append these tests. The existing import block is:

```js
import { render, screen, waitFor } from '@testing-library/svelte'
import { expect, test, vi, beforeEach } from 'vitest'
```

Change the first import line to add `fireEvent`, and add the fixture import alongside the others:

```js
import { render, screen, waitFor, fireEvent } from '@testing-library/svelte'
import filterRacesJson from './fixtures/races.filter.json'
```

Then append:

```js
test('Meet shows a Stafet chip only when the meet has relays', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByRole('button', { name: 'Stafet' })
  expect(screen.getByRole('button', { name: 'Bryst' })).toBeInTheDocument()
})

test('Meet has no Stafet chip when there are no relays', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson) // 2 individual races, no relay
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByRole('button', { name: 'Alle' })
  expect(screen.queryByRole('button', { name: 'Stafet' })).toBeNull()
})

test('clicking Bryst narrows the list to bryst individual races', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await fireEvent.click(await screen.findByRole('button', { name: 'Bryst' }))
  expect(screen.getByRole('link', { name: /Kvinder 200m Bryst/ })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Mænd 100m Fri/ })).toBeNull()
  expect(screen.queryByRole('link', { name: /Mix 4x100m HM/ })).toBeNull()
})

test('clicking Stafet shows the relay and hides individual races', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await fireEvent.click(await screen.findByRole('button', { name: 'Stafet' }))
  expect(screen.getByRole('link', { name: /Mix 4x100m HM/ })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Mænd 100m Fri/ })).toBeNull()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm test -- routes.render`
Expected: FAIL — no `Bryst`/`Stafet`/`Alle` buttons exist yet (the filter bar is not rendered).

- [ ] **Step 3: Write minimal implementation**

Edit `web/src/routes/Meet.svelte`.

(a) Add the import after the existing `format` import (line 5):

```js
  import { filterRaces, disciplineOptions, genderOptions } from '../lib/raceFilter.js'
```

(b) Add filter state after `let err = $state(null)` (line 16):

```js
  let discipline = $state('all')
  let gender = $state('all')

  const DISCIPLINE_LABEL = { all: 'Alle', Stafet: 'Stafet' } // strokes fall back to their own value
  const GENDER_LABEL = { all: 'Alle', M: 'Herrer', F: 'Damer', X: 'Mix' }

  const disciplines = $derived(races ? disciplineOptions(races) : ['all'])
  const genders = $derived(races ? genderOptions(races) : ['all'])
  const shownRaces = $derived(races ? filterRaces(races, { discipline, gender }) : [])
```

(c) Replace the `Løb` section (current lines 120-136, from `<h3 class="section-title">Løb</h3>` through the closing `{/if}` of the race list) with:

```svelte
  <div class="race-head">
    <h3 class="section-title">Løb</h3>
    <span class="race-tally muted">{formatInt(shownRaces.length)}</span>
  </div>

  {#if races.length === 0}
    <p class="state muted">Ingen løb fundet.</p>
  {:else}
    <div class="filters">
      <div class="filter-group" role="group" aria-label="Disciplin">
        {#each disciplines as d (d)}
          <button
            type="button"
            class="chip"
            aria-pressed={discipline === d}
            onclick={() => (discipline = d)}
          >{DISCIPLINE_LABEL[d] ?? d}</button>
        {/each}
      </div>
      <div class="filter-group" role="group" aria-label="Køn">
        {#each genders as g (g)}
          <button
            type="button"
            class="chip"
            aria-pressed={gender === g}
            onclick={() => (gender = g)}
          >{GENDER_LABEL[g] ?? g}</button>
        {/each}
      </div>
    </div>

    {#if shownRaces.length === 0}
      <p class="state muted">Ingen løb matcher filteret.</p>
    {:else}
      <ul class="race-list">
        {#each shownRaces as r (r.race_key)}
          <li>
            <a class="race-row" href={href('race', { cat: params.cat, meetId: params.meetId, raceKey: r.race_key })}>
              <span class="race-label">{r.label}</span>
              <span class="race-winner muted">{r.winner_name ?? '–'}</span>
              <span class="race-time num">{formatTimeStr(r.winning_time)}</span>
              <span class="race-count num muted">{formatInt(r.contestants)} {r.is_relay ? 'hold' : 'deltagere'}</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
```

(d) Add styles inside the `<style>` block (after the `.section-title` rule, before `.race-list`):

```css
  .race-head {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0 0 var(--space-2);
  }

  .race-head .section-title {
    margin: 0;
  }

  .race-tally {
    font-size: 0.8rem;
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }

  .filter-group {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }

  .chip {
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
    padding: var(--space-1) var(--space-2);
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: border-color 0.15s ease, background 0.15s ease;
  }

  .chip:hover {
    border-color: var(--accent);
  }

  .chip[aria-pressed='true'] {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }
```

Note: the old standalone `<h3 class="section-title">Løb</h3>` is removed — the heading now lives inside `.race-head`. The `.section-title` rule keeps its shared styling; `.race-head .section-title` just resets its margin.

- [ ] **Step 4: Run the full web test suite**

Run: `cd web && npm test`
Expected: PASS — all existing tests plus the 4 new render tests and Task 1's 8 tests. (The existing "Meet renders facts and a race link" test still passes: `racesJson` has no relays so no Stafet chip, both individual races render under the default `Alle`/`Alle`.)

- [ ] **Step 5: Commit**

```bash
git add web/src/routes/Meet.svelte web/tests/fixtures/races.filter.json web/tests/routes.render.test.js
git commit -m "feat(web): filter meet race list by discipline and gender"
```

---

## Self-Review

**Spec coverage:**
- Discipline single-select (Alle / strokes / Stafet), mutually exclusive → Task 1 `filterRaces` + `disciplineOptions`, Task 2 chip group. ✓
- Gender single-select (Alle/Herrer/Damer/Mix) applied on top → Task 1 `genderOptions`, Task 2 `GENDER_LABEL` + chip group. ✓
- Dynamic options (Stafet only if relays; only present genders) → `disciplineOptions`/`genderOptions` + tests. ✓
- Stroke + Mix → empty allowed → covered by unit test + `Ingen løb matcher filteret.` empty state. ✓
- Race count next to heading → `.race-tally`. ✓
- A11y `<button aria-pressed>` in labelled groups → Task 2 markup. ✓
- Pure logic isolated in `raceFilter.js`, not `format.js` → Task 1. ✓
- Out-of-scope items (URL state, multi-select, distance/course, JSON change) → not implemented. ✓

**Placeholder scan:** none — all steps contain runnable code/commands.

**Type consistency:** `filterRaces`, `disciplineOptions`, `genderOptions` names and `{ discipline, gender }` option shape match between Task 1 definition and Task 2 usage. Discipline sentinel values `'all'`/`'Stafet'` and gender `'all'`/`M`/`F`/`X` are consistent across module, state, and tests.
