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

const relayRace = {
  category: 'DM-L', meet_id: 'R2026', race_key: 'F-4x100-HM-LCM',
  label: 'F 4x100m HM', is_relay: true,
  facts: { contestants: 3, dsq: 1, winning_time: '4:10.51', median_cs: 25444,
           spread_1_last_cs: 1203, winner_points: 500 },
  podium: [{ rank: 1, name: 'Aalborg 1', swimmer_id: null, club: 'Aalborg SK',
             time: '4:10.51', points: 500 }],
  season_comparison: [{ season: 2026, best_cs: 25051, median_cs: 25444,
                        top8_avg_cs: 25300, cutline_cs: null, swims: 3 }],
}

test('Race renders a relay page without junior/cut-line/spread tiles and with a plain team name', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(relayRace)
  const { container } = render(Race, { params: { cat: 'DM-L', meetId: 'R2026', raceKey: 'F-4x100-HM-LCM' } })
  await waitFor(() => expect(screen.getByText('Aalborg 1')).toBeInTheDocument())
  expect(container.textContent).not.toContain('A-finale-grænse')
  expect(container.textContent).not.toContain('Juniorer')
  expect(container.querySelector('a.swimmer-link')).toBeNull()
})
