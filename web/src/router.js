import { writable } from 'svelte/store'

export function parsePath(path) {
  const parts = (path || '').split('/').filter(Boolean)
  // CloudFront rewrites /DM-L/12486 to the .../index.html object key, so the
  // browser never shows that suffix — but anyone who types it should still get
  // the meet page, not a race lookup for a raceKey of "index.html".
  if (parts.at(-1) === 'index.html') parts.pop()
  // [] | [cat] | [cat, meetId] | [cat, meetId, raceKey] — unambiguous by count:
  // category codes are non-numeric (DM-L, DO, …) and meet ids are numeric.
  if (parts.length >= 3) {
    return { name: 'race', params: { cat: parts[0], meetId: parts[1], raceKey: parts[2] } }
  }
  if (parts.length === 2) return { name: 'meet', params: { cat: parts[0], meetId: parts[1] } }
  if (parts.length === 1) return { name: 'home', params: { cat: parts[0] } }
  return { name: 'home', params: {} }
}

export function href(name, p = {}) {
  if (name === 'race') return `/${p.cat}/${p.meetId}/${p.raceKey}`
  if (name === 'meet') return `/${p.cat}/${p.meetId}`
  if (name === 'home' && p.cat) return `/${p.cat}`
  return '/'
}

/** Path for a link shared back when the app used hash routing, else null.
 *  '#/c/DM-L/m/12486' -> '/DM-L/12486' — the odd segments carry the values, the
 *  even ones are the old c/m/r markers. */
export function legacyPath(hash) {
  const parts = (hash || '').replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] !== 'c' || parts.length < 2) return null
  return '/' + parts.filter((_, i) => i % 2 === 1).join('/')
}

export const route = writable(parsePath(
  typeof location !== 'undefined' ? location.pathname : ''))

export function navigate(path) {
  history.pushState({}, '', path)
  route.set(parsePath(path))
}

if (typeof window !== 'undefined') {
  const legacy = legacyPath(location.hash)
  if (legacy) {
    history.replaceState({}, '', legacy)
    route.set(parsePath(legacy))
  }
  addEventListener('popstate', () => route.set(parsePath(location.pathname)))
  // Delegated, so no component has to know about routing. Everything the browser
  // should keep owning — other origins, new tabs, downloads, modified clicks —
  // falls through untouched.
  addEventListener('click', (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = e.target.closest?.('a')
    if (!a || !a.href || a.origin !== location.origin) return
    if (a.target || a.hasAttribute('download')) return
    e.preventDefault()
    navigate(a.pathname)
  })
}
