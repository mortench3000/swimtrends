---
name: run-web
description: Launch the Swimtrends web app (Vite dev server) and screenshot it headlessly with Playwright. Use when asked to run, view, or screenshot the web app / a page / the UI in the real browser (not tests).
---

# Run & screenshot the Swimtrends web app

The app (`web/`) is a Svelte 5 + Vite SPA that fetches `/data/*.json`. **That data
is committed under `web/public/data/`**, so the dev server renders real meets
fully offline — no build, no AWS, no `make web-refresh` needed.

Routes are hash-based: `#/c/<cat>/m/<meetId>` (meet page), `#/c/<cat>` (home),
`#/c/<cat>/m/<meetId>/r/<raceKey>` (race). Good showcase meet with relays and both
genders: `DM-L/10334` (DM Langbane 2023).

## Launch

```bash
cd web
npm run dev -- --port 5199 >/tmp/vite5199.log 2>&1 &
sleep 3 && curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5199/   # expect 200
```

## Screenshot (headless Playwright)

Playwright is **not** a project dependency. Install it transiently — order matters,
and both gotchas below are load-bearing:

```bash
cd web
npm i --no-save playwright      # node_modules only; leaves package.json/lock untouched
npx playwright install chromium # MUST run AFTER the line above, so the browser build
                                # matches the just-installed playwright version
node screenshot.mjs             # driver lives IN web/ — bare `import 'playwright'`
                                # only resolves from web/node_modules, not from /tmp
```

`web/screenshot.mjs` (committed) full-page-shots the meet page. Override targets
with env vars:

```bash
OUT=/tmp/home ROUTE='#/c/DM-L' PORT=5199 node screenshot.mjs
```

Then **look at the PNG** (Read it). A blank frame means the SPA never mounted —
check `/tmp/vite5199.log` and that the route/meet exists under `web/public/data/`.

To drive interactions (click a filter chip, then shoot), copy `screenshot.mjs` and
add Playwright calls before `page.screenshot`, e.g.
`await page.getByRole('button', { name: 'Bryst', exact: true }).click()`.
Chips animate with a 150 ms background fade — `await page.waitForTimeout(200)` after a
click before shooting, or colors will be caught mid-transition.

## Cleanup

```bash
pkill -f "vite --port 5199"
```

## Gotchas (all verified 2026-07-24)

- No system Chromium; Playwright's headless shell (~110 MB) downloads to
  `~/.cache/ms-playwright/` on first `install chromium` and is reused after.
- ESM ignores `NODE_PATH` and won't reach into another dir's `node_modules` —
  hence `npm i --no-save` into `web/` + driver kept in `web/`.
- Installing the browser before installing playwright gives a build-version
  mismatch (`Executable doesn't exist at …headless_shell-<n>`). Always install
  playwright first, browser second.
