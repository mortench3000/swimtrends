# Meet-page filters survive Back (filters in the URL)

## Why
On a meet page the user filters the race list (e.g. IM + Herrer), opens a race,
and presses browser Back. The filters reset, because they live only in
`routes/Meet.svelte` component state, which is discarded when the race page
replaces it. Back should land on the meet page exactly as it was left.

## Goals / non-goals / anti-goals
- **Goals:** Back, reload, and a shared link all reproduce the filtered meet page.
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

## Unchanged (checked)
- Race page, its breadcrumb, home/category pages.
- `prerender.mjs` static shells and `sitemap.xml` (keyed by path).
- Canonical URL: `lib/meta.js` builds it from `location.pathname`, so filtered
  URLs canonicalise to the bare meet path.
- CloudFront `viewer_request.js`: rewrites `request.uri` only; the query string
  is not part of it.

## Tests
- `tests/raceFilter.test.js`: helper round-trip, unknown values, `all` omitted.
- `tests/router.test.js`: query kept on navigation, route parsed from the path.
- Real-browser check (`/run-web`): filter, open race, Back → filters restored;
  reload keeps them; chip clicks add no Back steps.
