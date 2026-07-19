const BASE = (import.meta.env?.BASE_URL ?? '/').replace(/\/$/, '')
let cache = new Map()
export function _resetCache() { cache = new Map() }

async function get(path) {
  if (cache.has(path)) return cache.get(path)
  const p = fetch(`${BASE}/data/${path}`).then((r) => {
    if (!r.ok) throw new Error(`fetch ${path}: ${r.status}`)
    return r.json()
  })
  cache.set(path, p)
  return p
}

export const getIndex = () => get('index.json')
export const getMeets = (cat) => get(`${cat}/meets.json`)
export const getMeet = (cat, meetId) => get(`${cat}/${meetId}/meet.json`)
export const getRaces = (cat, meetId) => get(`${cat}/${meetId}/races.json`)
export const getRace = (cat, meetId, raceKey) => get(`${cat}/${meetId}/${raceKey}.json`)
