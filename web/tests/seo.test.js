import { expect, test } from 'vitest'
import { catLabel, clip, homeMeta, categoryMeta, meetMeta, raceMeta } from '../src/lib/seo.js'
import { renderShell, buildSitemap } from '../prerender.mjs'

const meet = {
  category: 'DM-L', meet_id: '12486', meet_name: 'DM Langbane 2026',
  meet_date: '09-07-2026', season: 2026,
  facts: { entrants: 581, clubs: 76, events: 42, median_points: 578, top_points: 870 },
}
const evaluation = {
  sections: [
    { heading: 'Samlet niveau', body: 'Medianen på stævnet var 578 point, hvilket er 5 procent under gennemsnittet for de seneste fem sæsoner. Elitens medianpoint lå på 701 og den højeste score var 870.' },
    { heading: 'Bredde', body: 'Stævnet omfattede 581 deltagere fra 76 klubber.' },
  ],
}

test('category codes get Danish labels, unknown codes pass through', () => {
  expect(catLabel('DM-L')).toBe('DM Langbane')
  expect(catLabel('DMJ-K')).toBe('DM Junior Kortbane')
  expect(catLabel('DO')).toBe('Danish Open')
  expect(catLabel('XX')).toBe('XX')
})

test('clip cuts on a word boundary and never exceeds the limit', () => {
  expect(clip('en to tre fire', 100)).toBe('en to tre fire')
  const out = clip('en to tre fire fem seks syv otte', 20)
  expect(out.length).toBeLessThanOrEqual(20)
  expect(out.endsWith('…')).toBe(true)
  expect(out).toBe('en to tre fire fem…')
})

test('meet meta uses the meet name and the evaluation prose', () => {
  const m = meetMeta(meet, evaluation)
  expect(m.title).toBe('DM Langbane 2026 — resultater og analyse | Swimtrends')
  expect(m.description.startsWith('Medianen på stævnet var 578 point')).toBe(true)
  expect(m.description.length).toBeLessThanOrEqual(160)
})

test('meet meta falls back to facts when there is no evaluation', () => {
  const m = meetMeta(meet, null)
  expect(m.description).toContain('581 deltagere')
  expect(m.description).toContain('76 klubber')
  expect(m.description).toContain('42 løb')
})

test('home, category and race meta', () => {
  expect(homeMeta().title).toContain('Swimtrends')
  expect(categoryMeta('DM-L').title).toContain('DM Langbane')
  expect(raceMeta({ label: 'M 100m Fri', category: 'DM-L' }).title)
    .toBe('M 100m Fri — DM Langbane | Swimtrends')
})

// --- prerender ---------------------------------------------------------------

const TEMPLATE = `<!doctype html>
<html lang="da"><head>
<title>Swimtrends</title>
<meta name="description" content="x" />
<link rel="canonical" href="https://swimtrends.dk/" />
<script type="module" src="/assets/index-abc.js"></script>
</head><body><div id="app"></div></body></html>`

test('renderShell stamps head tags and static body into the vite template', () => {
  const html = renderShell(TEMPLATE, {
    title: 'DM Langbane 2026 — resultater | Swimtrends',
    description: 'Medianen var 578 point.',
    path: '/DM-L/12486',
    body: '<h2>DM Langbane 2026</h2><p>Medianen var 578 point.</p>',
  })
  expect(html).toContain('<title>DM Langbane 2026 — resultater | Swimtrends</title>')
  expect(html).toContain('content="Medianen var 578 point."')
  expect(html).toContain('href="https://swimtrends.dk/DM-L/12486"')
  expect(html).toContain('<div id="app"><h2>DM Langbane 2026</h2>')
  expect(html).toContain('/assets/index-abc.js')   // vite's bundle survives
  expect(html).not.toContain('<title>Swimtrends</title>')
})

// String replacement is only safe if it actually matched: a silent miss would
// publish 46 pages carrying the generic title.
test('renderShell throws when a marker is missing', () => {
  expect(() => renderShell('<html><head></head><body></body></html>', { title: 't', description: 'd', path: '/', body: '' }))
    .toThrow(/marker/i)
})

test('buildSitemap emits absolute URLs and escapes nothing unexpected', () => {
  const xml = buildSitemap(['/', '/DM-L/12486'])
  expect(xml).toContain('<loc>https://swimtrends.dk/</loc>')
  expect(xml).toContain('<loc>https://swimtrends.dk/DM-L/12486</loc>')
  expect(xml.trim().startsWith('<?xml')).toBe(true)
  expect(xml).toContain('</urlset>')
})
