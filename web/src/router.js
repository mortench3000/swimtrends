import { writable } from 'svelte/store'

export function parseHash(hash) {
  const parts = (hash || '').replace(/^#\/?/, '').split('/').filter(Boolean)
  // [] | [c,cat] | [c,cat,m,meetId] | [c,cat,m,meetId,r,raceKey]
  if (parts[0] === 'c' && parts[2] === 'm' && parts[4] === 'r') {
    return { name: 'race', params: { cat: parts[1], meetId: parts[3], raceKey: parts[5] } }
  }
  if (parts[0] === 'c' && parts[2] === 'm') {
    return { name: 'meet', params: { cat: parts[1], meetId: parts[3] } }
  }
  if (parts[0] === 'c') return { name: 'home', params: { cat: parts[1] } }
  return { name: 'home', params: {} }
}

export function href(name, p = {}) {
  if (name === 'race') return `#/c/${p.cat}/m/${p.meetId}/r/${p.raceKey}`
  if (name === 'meet') return `#/c/${p.cat}/m/${p.meetId}`
  if (name === 'home' && p.cat) return `#/c/${p.cat}`
  return '#/'
}

export const route = writable(parseHash(typeof location !== 'undefined' ? location.hash : ''))
if (typeof window !== 'undefined') {
  window.addEventListener('hashchange', () => route.set(parseHash(location.hash)))
}
