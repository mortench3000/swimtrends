import { expect, test, vi, beforeEach } from 'vitest'
import * as dc from '../src/lib/dataClient.js'

beforeEach(() => { dc._resetCache() })

function mockFetch(map) {
  globalThis.fetch = vi.fn(async (url) => {
    const key = Object.keys(map).find((k) => url.endsWith(k))
    if (!key) return { ok: false, status: 404 }
    return { ok: true, json: async () => map[key] }
  })
}

test('getMeet fetches the right path and caches', async () => {
  mockFetch({ 'data/DM-L/M2026/meet.json': { meet_id: 'M2026', facts: { events: 2 } } })
  const a = await dc.getMeet('DM-L', 'M2026')
  const b = await dc.getMeet('DM-L', 'M2026')
  expect(a.facts.events).toBe(2)
  expect(globalThis.fetch).toHaveBeenCalledTimes(1) // cached
})

test('throws on non-ok', async () => {
  mockFetch({})
  await expect(dc.getRaces('DM-L', 'NOPE')).rejects.toThrow()
})
