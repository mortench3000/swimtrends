import { expect, test } from 'vitest'
import { get } from 'svelte/store'
import { route, parseHash, href } from '../src/router.js'

test('parses race route', () => {
  expect(parseHash('#/c/DM-L/m/M2026/r/M-100-Fri-LCM'))
    .toEqual({ name: 'race', params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
})
test('unknown falls back to home', () => {
  expect(parseHash('#/garbage').name).toBe('home')
})
test('href builds meet link', () => {
  expect(href('meet', { cat: 'DM-L', meetId: 'M2026' })).toBe('#/c/DM-L/m/M2026')
})
