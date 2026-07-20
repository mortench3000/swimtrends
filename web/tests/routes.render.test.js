import { render, screen, waitFor } from '@testing-library/svelte'
import { expect, test, vi, beforeEach } from 'vitest'
import * as dc from '../src/lib/dataClient.js'
import Meet from '../src/routes/Meet.svelte'
import Race from '../src/routes/Race.svelte'
import meetJson from './fixtures/meet.json'
import racesJson from './fixtures/races.json'
import raceJson from './fixtures/race.json'

beforeEach(() => { dc._resetCache() })

test('Meet renders facts and a race link', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.getByRole('heading', { level: 3, name: /løb/i })).toBeInTheDocument()
})

test('Race renders podium winner and winning time', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(raceJson)
  render(Race, { params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
  await waitFor(() => expect(screen.getByText(raceJson.podium[0].name)).toBeInTheDocument())
  expect(screen.getAllByText(raceJson.facts.winning_time)).toHaveLength(2)
})

test('podium winner name links to their svømmetider.dk profile in a new tab', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(raceJson)
  render(Race, { params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
  const link = await screen.findByRole('link', { name: new RegExp(raceJson.podium[0].name) })
  expect(link).toHaveAttribute(
    'href',
    `https://svømmetider.dk/svoemmer/?${raceJson.podium[0].swimmer_id}`,
  )
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
})
