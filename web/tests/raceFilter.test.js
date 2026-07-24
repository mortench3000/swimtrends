import { expect, test } from 'vitest'
import { filterRaces, disciplineOptions, genderOptions } from '../src/lib/raceFilter.js'

const races = [
  { race_key: 'M-100-Fri',   stroke: 'Fri',   gender: 'M', is_relay: false },
  { race_key: 'F-200-Bryst', stroke: 'Bryst', gender: 'F', is_relay: false },
  { race_key: 'M-200-Bryst', stroke: 'Bryst', gender: 'M', is_relay: false },
  { race_key: 'X-4x100-HM',  stroke: 'HM',    gender: 'X', is_relay: true  },
  { race_key: 'M-4x100-Fri', stroke: 'Fri',   gender: 'M', is_relay: true  },
]

test('discipline=all gender=all keeps everything', () => {
  expect(filterRaces(races, { discipline: 'all', gender: 'all' })).toHaveLength(5)
})

test('a stroke keeps only that stroke and excludes relays', () => {
  const out = filterRaces(races, { discipline: 'Bryst', gender: 'all' })
  expect(out.map((r) => r.race_key)).toEqual(['F-200-Bryst', 'M-200-Bryst'])
})

test('Stafet keeps only relays regardless of stroke', () => {
  const out = filterRaces(races, { discipline: 'Stafet', gender: 'all' })
  expect(out.map((r) => r.race_key)).toEqual(['X-4x100-HM', 'M-4x100-Fri'])
})

test('gender narrows within a discipline', () => {
  const out = filterRaces(races, { discipline: 'Bryst', gender: 'M' })
  expect(out.map((r) => r.race_key)).toEqual(['M-200-Bryst'])
})

test('stroke + Mix (X) yields empty (X only exists as relay)', () => {
  expect(filterRaces(races, { discipline: 'Fri', gender: 'X' })).toHaveLength(0)
})

test('disciplineOptions lists present individual strokes in canonical order then Stafet', () => {
  expect(disciplineOptions(races)).toEqual(['all', 'Fri', 'Bryst', 'Stafet'])
})

test('disciplineOptions omits Stafet when no relay present', () => {
  const noRelay = races.filter((r) => !r.is_relay)
  expect(disciplineOptions(noRelay)).toEqual(['all', 'Fri', 'Bryst'])
})

test('genderOptions lists present genders in M,F,X order', () => {
  expect(genderOptions(races)).toEqual(['all', 'M', 'F', 'X'])
})
