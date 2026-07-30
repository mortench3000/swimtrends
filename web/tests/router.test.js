import { expect, test } from 'vitest'
import { get } from 'svelte/store'
import { route, parsePath, href, legacyPath, navigate } from '../src/router.js'

test('parses race route', () => {
  expect(parsePath('/DM-L/M2026/M-100-Fri-LCM'))
    .toEqual({ name: 'race', params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
})
test('parses meet route', () => {
  expect(parsePath('/DM-L/M2026'))
    .toEqual({ name: 'meet', params: { cat: 'DM-L', meetId: 'M2026' } })
})
test('parses category route', () => {
  expect(parsePath('/DM-L')).toEqual({ name: 'home', params: { cat: 'DM-L' } })
})
test('root is home', () => {
  expect(parsePath('/')).toEqual({ name: 'home', params: {} })
  expect(parsePath('')).toEqual({ name: 'home', params: {} })
})
test('ignores a trailing index.html (the prerendered object key)', () => {
  expect(parsePath('/DM-L/M2026/index.html'))
    .toEqual({ name: 'meet', params: { cat: 'DM-L', meetId: 'M2026' } })
  expect(parsePath('/index.html')).toEqual({ name: 'home', params: {} })
})
test('tolerates a trailing slash', () => {
  expect(parsePath('/DM-L/M2026/'))
    .toEqual({ name: 'meet', params: { cat: 'DM-L', meetId: 'M2026' } })
})

test('href builds paths', () => {
  expect(href('home')).toBe('/')
  expect(href('home', { cat: 'DM-L' })).toBe('/DM-L')
  expect(href('meet', { cat: 'DM-L', meetId: 'M2026' })).toBe('/DM-L/M2026')
  expect(href('race', { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' }))
    .toBe('/DM-L/M2026/M-100-Fri-LCM')
})

// Links shared while the app used hash routing must still resolve.
test('legacyPath converts old hash links', () => {
  expect(legacyPath('#/c/DM-L/m/12486/r/M-100-Fri-LCM')).toBe('/DM-L/12486/M-100-Fri-LCM')
  expect(legacyPath('#/c/DM-L/m/12486')).toBe('/DM-L/12486')
  expect(legacyPath('#/c/DM-L')).toBe('/DM-L')
  expect(legacyPath('#/')).toBe(null)
  expect(legacyPath('')).toBe(null)
  expect(legacyPath('#/garbage')).toBe(null)
})

test('navigate pushes history and updates the store', () => {
  navigate('/DM-K/9999')
  expect(location.pathname).toBe('/DM-K/9999')
  expect(get(route)).toEqual({ name: 'meet', params: { cat: 'DM-K', meetId: '9999' } })
  navigate('/')
})

// The delegated click listener is what keeps in-app links from doing a full
// page load. It must leave everything else alone.
function clickLink(attrs, init = {}) {
  const a = document.createElement('a')
  for (const [k, v] of Object.entries(attrs)) a.setAttribute(k, v)
  a.textContent = 'x'
  document.body.append(a)
  const ev = new MouseEvent('click', { bubbles: true, cancelable: true, button: 0, ...init })
  a.dispatchEvent(ev)
  a.remove()
  return ev
}

test('intercepts internal links', () => {
  const ev = clickLink({ href: '/DM-L/12486' })
  expect(ev.defaultPrevented).toBe(true)
  expect(location.pathname).toBe('/DM-L/12486')
  navigate('/')
})

test('leaves external, new-tab, download and modified clicks to the browser', () => {
  expect(clickLink({ href: 'https://xn--svmmetider-1cb.dk/x' }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1', target: '_blank' }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1', download: '' }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1' }, { metaKey: true }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1' }, { ctrlKey: true }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1' }, { shiftKey: true }).defaultPrevented).toBe(false)
  expect(clickLink({ href: '/DM-L/1' }, { button: 1 }).defaultPrevented).toBe(false)
  expect(location.pathname).toBe('/')
})
