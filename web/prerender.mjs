// Post-build step: turn the single-URL SPA into crawlable pages.
//
// Vite emits one dist/index.html with an empty <div id="app">. Google can run
// JS, but with nothing in the HTML and no distinct URLs there is nothing to
// index — see docs/superpowers/specs/2026-07-30-search-indexable-pages-design.md.
// So for the home page, each category and each meet we write a copy of that
// template with a real <title>, description, canonical and static Danish body
// (the AI evaluation prose), plus a sitemap.
//
// Input comes from the *live* /data zone over HTTPS: web/public/data is
// gitignored, so CI has no local copy. A fetch failure must fail the build —
// `make web-deploy` syncs with --delete, so prerendering nothing would delete
// the good pages out of the bucket.
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import {
  ORIGIN, canonical, catLabel, categoryMeta, homeMeta, meetMeta,
} from './src/lib/seo.js'

const DATA_BASE = process.env.SEO_DATA_BASE || `${ORIGIN}/data`
const DIST = join(import.meta.dirname, 'dist')

const esc = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')

/** Stamp one page into vite's template. Throws rather than silently no-op:
 *  a missed replacement would publish every page with the generic <title>. */
export function renderShell(template, { title, description, path, body }) {
  const subs = [
    [/<title>[^<]*<\/title>/, `<title>${esc(title)}</title>`],
    [/<meta name="description" content="[^"]*"\s*\/?>/,
      `<meta name="description" content="${esc(description)}" />`],
    [/<link rel="canonical" href="[^"]*"\s*\/?>/,
      `<link rel="canonical" href="${esc(canonical(path))}" />`],
    [/<div id="app"><\/div>/, `<div id="app">${body}</div>`],
  ]
  let html = template
  for (const [marker, replacement] of subs) {
    if (!marker.test(html)) throw new Error(`prerender: marker ${marker} not found in dist/index.html`)
    html = html.replace(marker, replacement)
  }
  return html
}

// ponytail: no <lastmod>. It would change on every build and buys nothing —
// Google treats it as a hint at best. Add it if Search Console asks for it.
export function buildSitemap(paths) {
  const urls = paths.map((p) => `  <url><loc>${esc(canonical(p))}</loc></url>`).join('\n')
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${urls}
</urlset>
`
}

async function getJson(rel, { optional = false } = {}) {
  const res = await fetch(`${DATA_BASE}/${rel}`)
  if (res.status === 404 && optional) return null
  if (!res.ok) throw new Error(`prerender: GET ${DATA_BASE}/${rel} -> HTTP ${res.status}`)
  return res.json()
}

const link = (path, label) => `<a href="${esc(path)}">${esc(label)}</a>`

// The site header (and its <h1>Swimtrends</h1>) is Svelte-rendered, so the static
// shell owns the page's only <h1> — the thing the page is actually about.
function homeBody(categories) {
  return `<h1>Danske svømmestævner</h1><p>Swimtrends analyserer resultater fra `
    + `danske mesterskabsstævner: point, deltagerudvikling og trends sæson for sæson.</p>`
    + `<ul>${categories.map((c) => `<li>${link(`/${c.code}`, catLabel(c.code))}</li>`).join('')}</ul>`
}

function categoryBody(cat, meets) {
  return `<h1>${esc(catLabel(cat))}</h1><ul>${meets.map((m) =>
    `<li>${link(`/${cat}/${m.meet_id}`, m.meet_name)} — ${esc(m.meet_date)}, `
    + `${esc(m.entrants)} deltagere fra ${esc(m.clubs)} klubber</li>`).join('')}</ul>`
}

function meetBody(meet, evaluation) {
  const f = meet.facts ?? {}
  const sections = (evaluation?.sections ?? []).map((s) =>
    `<h2>${esc(s.heading)}</h2><p>${esc(s.body)}</p>`).join('')
  return `<h1>${esc(meet.meet_name)}</h1>`
    + `<p>${esc(catLabel(meet.category))}, sæson ${esc(meet.season)}, afholdt ${esc(meet.meet_date)}. `
    + `${esc(f.entrants)} deltagere fra ${esc(f.clubs)} klubber i ${esc(f.events)} løb. `
    + `Medianpoint ${esc(f.median_points)}, højeste ${esc(f.top_points)}.</p>`
    + sections
}

async function write(path, html) {
  const file = join(DIST, path === '/' ? 'index.html' : `${path.slice(1)}/index.html`)
  await mkdir(dirname(file), { recursive: true })
  await writeFile(file, html)
}

async function main() {
  const template = await readFile(join(DIST, 'index.html'), 'utf8')
  const index = await getJson('index.json')
  const paths = ['/']

  await write('/', renderShell(template, {
    ...homeMeta(), path: '/', body: homeBody(index.categories),
  }))

  for (const { code } of index.categories) {
    const { meets } = await getJson(`${code}/meets.json`)
    paths.push(`/${code}`)
    await write(`/${code}`, renderShell(template, {
      ...categoryMeta(code), path: `/${code}`, body: categoryBody(code, meets),
    }))

    await Promise.all(meets.map(async ({ meet_id: id }) => {
      const [meet, evaluation] = await Promise.all([
        getJson(`${code}/${id}/meet.json`),
        getJson(`${code}/${id}/evaluation.json`, { optional: true }),
      ])
      const path = `/${code}/${id}`
      paths.push(path)
      await write(path, renderShell(template, {
        ...meetMeta(meet, evaluation), path, body: meetBody(meet, evaluation),
      }))
    }))
  }

  paths.sort()
  await writeFile(join(DIST, 'sitemap.xml'), buildSitemap(paths))
  console.log(`prerendered ${paths.length} pages + sitemap.xml from ${DATA_BASE}`)
}

if (process.argv[1] === import.meta.filename) await main()
