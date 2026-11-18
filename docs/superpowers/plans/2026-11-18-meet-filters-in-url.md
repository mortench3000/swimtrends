# Meet Filters in the URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Meet-page race filters live in the URL query, so browser Back from a race (and reload/share) restores them; the race page gets a "← Tilbage" link that does the same.

**Architecture:** Two pure helpers in `lib/raceFilter.js` convert between the query string and `{ discipline, gender }`. `Meet.svelte` initialises its filter state from `location.search` and writes it back with `history.replaceState` on each chip click. The router keeps `a.search` on in-app link clicks and routes on the path only.

**Tech Stack:** Svelte 5 (runes), Vite, Vitest + @testing-library/svelte (jsdom). Run tests from `web/` with `npm test`.

**Spec:** `docs/specs/2026-11-18-meet-filters-in-url.md`

## Global Constraints

- Query parameter names: `discipline`, `gender` (English). Values: `discipline` ∈ `Fri|Ryg|Bryst|Fly|IM|Stafet`, `gender` ∈ `M|F|X`.
- `all` is never written to the URL: an unfiltered meet keeps its bare path.
- Chip clicks use `history.replaceState`, never `pushState`.
- The race page's "Stævne" breadcrumb (plain meet link), canonical URL, prerender and sitemap are unchanged.
- "Tilbage" copy: `← Tilbage`. Its href is always the bare meet URL.

## Review Focus

1. Back from a race lands on the filtered meet: covered by Task 3's "initial filters come from the URL" test and Task 4's browser check.
2. Chip clicks add no Back steps: Task 3 asserts `history.length` is unchanged after clicks.
3. A shared link naming a filter the meet lacks (`?discipline=Stafet` on a meet with no relays) falls back to Alle: Task 3 test.
4. Junk queries (`?discipline=foo`, `?gender=m` lower-case, unrelated `utm_*` params) parse to `all` and don't break the page: Task 1 test.
5. Choosing "Alle" again returns the URL to the bare path (no dangling `?`): Task 1 (`filtersToSearch` → `''`) and Task 3.
6. "Tilbage" on a race reached by a shared link must not leave the site: Task 4 "direct landing" test.

---

### Task 1: Query-string helpers

**Files:**
- Modify: `web/src/lib/raceFilter.js`
- Test: `web/tests/raceFilter.test.js`

**Interfaces:**
- Produces: `filtersFromSearch(search: string) -> { discipline: string, gender: string }` and `filtersToSearch({ discipline, gender }) -> string` (`''` or a string starting with `?`).

- [ ] **Step 1: Write the failing tests** in `web/tests/raceFilter.test.js`:

```js
test('filtersFromSearch reads known values', () => {
  expect(filtersFromSearch('?discipline=IM&gender=M')).toEqual({ discipline: 'IM', gender: 'M' })
})
test('filtersFromSearch maps missing, unknown and wrong-case values to all', () => {
  expect(filtersFromSearch('')).toEqual({ discipline: 'all', gender: 'all' })
  expect(filtersFromSearch('?discipline=foo&gender=m&utm_source=x'))
    .toEqual({ discipline: 'all', gender: 'all' })
})
test('filtersToSearch omits all and round-trips', () => {
  expect(filtersToSearch({ discipline: 'all', gender: 'all' })).toBe('')
  expect(filtersToSearch({ discipline: 'Stafet', gender: 'all' })).toBe('?discipline=Stafet')
  const s = filtersToSearch({ discipline: 'IM', gender: 'F' })
  expect(s).toBe('?discipline=IM&gender=F')
  expect(filtersFromSearch(s)).toEqual({ discipline: 'IM', gender: 'F' })
})
```

- [ ] **Step 2: Run, expect FAIL** — `npm test -- raceFilter` → "filtersFromSearch is not a function" (or import error).
- [ ] **Step 3: Implement** both in `raceFilter.js` with `URLSearchParams`; valid values are `STROKE_ORDER` plus `'Stafet'`, and `GENDER_ORDER` (reuse the existing constants). Order in output: `discipline` then `gender`.
- [ ] **Step 4: Run, expect PASS** — `npm test -- raceFilter`.
- [ ] **Step 5: Commit** — `git commit -m "feat(web): parse and build meet filter query strings"`

### Task 2: Router keeps the query

**Files:**
- Modify: `web/src/router.js` (`parsePath`, `navigate`, the delegated click handler)
- Test: `web/tests/router.test.js`

**Interfaces:**
- Produces: `navigate(pathWithOptionalQuery)` pushes the full string with history state `{ app: true }`; `route` is parsed from the path part only.

- [ ] **Step 1: Write the failing tests:**

```js
test('parsePath ignores a query string', () => {
  expect(parsePath('/DM-L/M2026?discipline=IM&gender=M'))
    .toEqual({ name: 'meet', params: { cat: 'DM-L', meetId: 'M2026' } })
})
test('navigate keeps the query in the URL and routes on the path', () => {
  navigate('/DM-K/9999?gender=F')
  expect(location.pathname).toBe('/DM-K/9999')
  expect(location.search).toBe('?gender=F')
  expect(get(route)).toEqual({ name: 'meet', params: { cat: 'DM-K', meetId: '9999' } })
  navigate('/')
})
test('navigate marks its history entries as in-app', () => {
  navigate('/DM-K/9999')
  expect(history.state).toEqual({ app: true })
  navigate('/')
})
test('intercepted links keep their query', () => {
  clickLink({ href: '/DM-L/12486?discipline=Fly' })
  expect(location.search).toBe('?discipline=Fly')
  navigate('/')
})
```

- [ ] **Step 2: Run, expect FAIL** — `npm test -- router` (parsePath returns `meetId: 'M2026?discipline=IM&gender=M'`; link loses `?discipline=Fly`).
- [ ] **Step 3: Implement** — `parsePath` drops everything from the first `?`; `navigate` pushes `{ app: true }`; the click handler calls `navigate(a.pathname + a.search)`. `popstate` stays as is.
- [ ] **Step 4: Run, expect PASS** — `npm test -- router`.
- [ ] **Step 5: Commit** — `git commit -m "feat(web): keep the query string on in-app navigation"`

### Task 3: Meet page reads and writes its filters in the URL

**Files:**
- Modify: `web/src/routes/Meet.svelte` (filter state at ~L22-23, chip `onclick`s at ~L170-185, `load()`)
- Test: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: `filtersFromSearch`, `filtersToSearch` (Task 1).

- [ ] **Step 1: Write the failing tests** (fixtures: `racesJson` = individual Fri/M and Bryst/F, no relays; `filterRacesJson` has relays). Set the URL with `history.replaceState({}, '', '/DM-L/M2026?…')` before `render`, and reset to `'/'` after each test:

  - `'Meet takes its initial filters from the URL'`: URL `?discipline=Bryst&gender=F`, `filterRacesJson` → after load the `Bryst` and `Damer` chips have `aria-pressed="true"`.
  - `'clicking chips rewrites the URL without adding history entries'`: bare URL, `racesJson`; record `history.length`; click `Fri`, then `Herrer` → `location.search === '?discipline=Fri&gender=M'`, `history.length` unchanged; click the discipline `Alle` and the gender `Alle` → `location.search === ''`, `location.pathname === '/DM-L/M2026'`.
  - `'a filter the meet does not offer falls back to Alle'`: URL `?discipline=Stafet`, `racesJson` (no relays) → discipline `Alle` chip pressed, both races listed, and `location.search === ''`.

  The two "Alle" chips share a name, so select them within their group: `within(screen.getByRole('group', { name: 'Disciplin' })).getByRole('button', { name: 'Alle' })`.

- [ ] **Step 2: Run, expect FAIL** — `npm test -- routes.render`.
- [ ] **Step 3: Implement** — initialise `discipline`/`gender` from `filtersFromSearch(location.search)`; add `setFilters({ discipline, gender })` that assigns state and calls `history.replaceState(history.state, '', location.pathname + filtersToSearch(...))`; the chips call it. After `races` load in `load()`, if the current value is not in `disciplineOptions(races)` / `genderOptions(races)`, reset it to `'all'` through `setFilters` (so the URL is cleaned too).
- [ ] **Step 4: Run, expect PASS** — `npm test` (whole SPA suite; previous count 52 + the new tests).
- [ ] **Step 5: Commit** — `git commit -m "feat(web): keep meet filters in the URL so Back restores them"`

### Task 4: "← Tilbage" on the race page

**Files:**
- Modify: `web/src/routes/Race.svelte` (top of the markup, above all three `<Breadcrumbs>`; render it once, outside the `{#if loading}` chain)
- Test: `web/tests/routes.render.test.js`

**Interfaces:**
- Consumes: history state `{ app: true }` from Task 2's `navigate`; `href('meet', …)` from `router.js`.

- [ ] **Step 1: Write the failing tests** (mock `getRace` with `raceJson`; render `Race` with `params: { cat: 'DM-L', meetId: 'M2026', raceKey: <raceJson's key> }`; spy `history.back` with `vi.spyOn(history, 'back').mockImplementation(() => {})`):
  - `'Tilbage links to the meet'`: `screen.getByRole('link', { name: '← Tilbage' })` has `href` `/DM-L/M2026`.
  - `'Tilbage goes back after in-app navigation'`: `history.replaceState({ app: true }, '', '/DM-L/M2026/x')`, click it with `fireEvent.click` → `history.back` called once and the click's default prevented.
  - `'Tilbage follows its link on a direct landing'`: `history.replaceState(null, '', '/DM-L/M2026/x')`, click → `history.back` not called.
  - `'Tilbage leaves modified clicks to the browser'`: `{ app: true }` state, click with `{ ctrlKey: true }` → `history.back` not called, default not prevented.
- [ ] **Step 2: Run, expect FAIL** — `npm test -- routes.render` (no link named "← Tilbage").
- [ ] **Step 3: Implement** — an `<a class="back" href={href('meet', { cat: params.cat, meetId: params.meetId })} onclick={back}>← Tilbage</a>`; `back(e)` returns early for `e.button !== 0` or any modifier key, otherwise if `history.state?.app` it calls `e.preventDefault()` then `history.back()`. Style it like the breadcrumb links (small, `--muted`), with the same bottom margin.
- [ ] **Step 4: Run, expect PASS** — `npm test`.
- [ ] **Step 5: Commit** — `git commit -m "feat(web): add a Tilbage link on the race page"`

### Task 5: Real-browser check, PR

- [ ] **Step 1:** `npx playwright install chromium` (confirm the browser matches the installed Playwright package), then use the `run-web` skill against `web/public/data`: open a meet, click `IM` + `Herrer`, open a race, go Back. Pass = URL `…?discipline=IM&gender=M`, both chips pressed, list filtered. Repeat using "← Tilbage" instead of Back (same result). Then reload (still filtered), click "Stævne" on a race page (lands unfiltered, bare URL), and open a race URL directly in a fresh page and click "← Tilbage" (lands on the bare meet). Screenshot the restored meet page and the race page header.
- [ ] **Step 2:** `npm test` green; push the branch; `gh pr create` (no AI attribution); `gh pr checks --watch`; `gh pr merge --squash --delete-branch`. The SPA deploys itself on merge; no data refresh needed.
