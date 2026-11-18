# Meet-page filters survive Back (filters in the URL)

## Why
On a meet page the user filters the race list (e.g. IM + Herrer), opens a race,
and presses browser Back. The filters reset, because they live only in
`routes/Meet.svelte` component state, which is discarded when the race page
replaces it. Back should land on the meet page exactly as it was left.

## Goals / non-goals / anti-goals
- **Goals:** Back, reload, and a shared link all reproduce the filtered meet page.
- **Also (added):** a "← Tilbage" link on the race page that returns to the
  page the user came from, so a click lands on the filtered meet.
- **Non-goals:** the race page's "Stævne" breadcrumb stays a plain link to the
  unfiltered meet (user's call). Race URLs are unchanged. No filters on other pages.
- **Anti-goals:** every chip click becoming its own Back step; filtered URLs
  showing up to search engines as separate pages.

## Approaches
- **A. Filters in the meet URL's query string (chosen).** Native Back/reload/share,
  smallest change to the existing router.
- B. Filters in `history.state`: Back works, but reload and sharing lose them.
- C. Per-meet in-memory store: reload loses them, and a later visit shows stale filters.

## Design
- **URL:** `/<cat>/<meetId>?discipline=IM&gender=M`.
  - Parameter names are English (user's call); values are the existing ones
    used by the page: `discipline` ∈ `Fri|Ryg|Bryst|Fly|IM|Stafet`,
    `gender` ∈ `M|F|X`.
  - `all` ("Alle") is the absence of the parameter, so an unfiltered meet keeps
    its bare URL.
- **`web/src/lib/raceFilter.js`:** two pure helpers.
  - `filtersFromSearch(search)` → `{ discipline, gender }`; unknown or missing
    values → `'all'`.
  - `filtersToSearch({ discipline, gender })` → `''` or `'?…'`, omitting `all`.
- **`web/src/routes/Meet.svelte`:**
  - Initial `discipline`/`gender` come from `filtersFromSearch(location.search)`.
  - A chip click sets the filter and calls
    `history.replaceState(history.state, '', location.pathname + filtersToSearch(…))`:
    the URL changes without adding a Back step.
  - Once races load, a filter value the meet doesn't offer (e.g. `Stafet` on a
    meet without relays, from a shared link) falls back to `all` (our call).
- **`web/src/router.js`:**
  - The delegated link handler navigates to `a.pathname + a.search`.
  - `navigate(path)` routes on the path part only (query ignored by `parsePath`).
  - `popstate` is unchanged: Back remounts the meet page, which reads the
    filters from the restored URL.

- **Router marks its own history entries:** `navigate()` pushes
  `{ app: true }` as the history state, so a page can tell whether its Back
  step stays inside the SPA.
- **`web/src/routes/Race.svelte`: "← Tilbage" link** on its own line above the
  breadcrumbs, in the loading, error and loaded states (our call).
  - `href` is the bare meet URL, so it is a real link (middle-click, new tab,
    keyboard all work).
  - On a plain left click, if `history.state?.app` is true, it calls
    `history.back()` (and prevents the default), landing on the filtered meet.
  - Otherwise (shared link, new tab, search result) it follows the href to the
    meet, unfiltered (our call: Tilbage never leaves the site).
  - Modified clicks (Ctrl/Cmd/Shift/Alt, non-left button) are left to the browser.

## Unchanged (checked)
- Race page breadcrumb, home/category pages.
- `prerender.mjs` static shells and `sitemap.xml` (keyed by path).
- Canonical URL: `lib/meta.js` builds it from `location.pathname`, so filtered
  URLs canonicalise to the bare meet path.
- CloudFront `viewer_request.js`: the path rewrite is unaffected. The www->apex
  301 used to drop the query string; fixed in
  `2026-11-18-www-redirect-keeps-query.md`.

## Tests
- `tests/raceFilter.test.js`: helper round-trip, unknown values, `all` omitted.
- `tests/router.test.js`: query kept on navigation, route parsed from the path,
  `navigate()` marks its history entries.
- `tests/routes.render.test.js`: Tilbage goes back after in-app navigation,
  follows its href on a direct landing, leaves modified clicks alone.
- Real-browser check (`/run-web`): filter, open race, Back → filters restored;
  reload keeps them; chip clicks add no Back steps; "Tilbage" returns to the
  filtered meet.
