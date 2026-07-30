// Titles, descriptions and canonical URLs. Pure, and imported by *both* the SPA
// (client-side <head> updates) and prerender.mjs (static shells), so the two can
// never disagree about what a page is called.

export const ORIGIN = 'https://swimtrends.dk'
export const SITE = 'Swimtrends'
export const MAX_DESCRIPTION = 160

const CATEGORY_LABEL = {
  'DM-L': 'DM Langbane',
  'DM-K': 'DM Kortbane',
  'DMJ-L': 'DM Junior Langbane',
  'DMJ-K': 'DM Junior Kortbane',
  DO: 'Danish Open',
}

export function catLabel(code) {
  return CATEGORY_LABEL[code] ?? code
}

export function canonical(path) {
  return ORIGIN + path
}

/** Trim to `max` characters on a word boundary, ellipsis included in the count. */
export function clip(text, max = MAX_DESCRIPTION) {
  const s = (text ?? '').replace(/\s+/g, ' ').trim()
  if (s.length <= max) return s
  const cut = s.slice(0, max - 1)
  const lastSpace = cut.lastIndexOf(' ')
  return (lastSpace > 0 ? cut.slice(0, lastSpace) : cut) + '…'
}

export function homeMeta() {
  return {
    title: `${SITE} — trends i dansk konkurrencesvømning`,
    description: 'Analyser af danske svømmestævner: DM Langbane, DM Kortbane, '
      + 'DM Junior og Danish Open. Point, deltagerudvikling og resultater.',
  }
}

export function categoryMeta(cat) {
  const label = catLabel(cat)
  return {
    title: `${label} — stævner og resultater | ${SITE}`,
    description: clip(`Alle ${label}-stævner i Swimtrends: deltagere, løb, `
      + 'point og udvikling sæson for sæson.'),
  }
}

export function meetMeta(meet, evaluation) {
  const f = meet?.facts ?? {}
  const prose = evaluation?.sections?.[0]?.body
  const facts = `${f.entrants} deltagere fra ${f.clubs} klubber, ${f.events} løb. `
    + `Medianpoint ${f.median_points}, højeste ${f.top_points}.`
  return {
    title: `${meet.meet_name} — resultater og analyse | ${SITE}`,
    description: clip(prose || facts),
  }
}

export function raceMeta(race) {
  return {
    title: `${race.label} — ${catLabel(race.category)} | ${SITE}`,
    description: clip(`Resultater, podium og pointudvikling for ${race.label} `
      + `ved ${catLabel(race.category)}.`),
  }
}
