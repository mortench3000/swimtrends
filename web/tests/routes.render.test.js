import { render, screen, waitFor, fireEvent } from '@testing-library/svelte'
import { expect, test, vi, beforeEach } from 'vitest'
import * as dc from '../src/lib/dataClient.js'
import Meet from '../src/routes/Meet.svelte'
import Race from '../src/routes/Race.svelte'
import meetJson from './fixtures/meet.json'
import racesJson from './fixtures/races.json'
import filterRacesJson from './fixtures/races.filter.json'
import raceJson from './fixtures/race.json'
import evaluationJson from './fixtures/evaluation.json'

beforeEach(() => { dc._resetCache() })

const juniorMeet = {
  category: 'DMJ-L', meet_id: 'C2026', meet_name: 'Combined Champs 2026',
  meet_date: '2026-04-10', season: 2026, junior_scoped: true,
  facts: { swims: 4, entrants: 4, events: 1, clubs: 3, juniors: 4,
           median_points: 500, top_points: 500, elite_median_points: 500 },
  season_comparison: [{ season: 2026, entrants: 4, events: 1, clubs: 3,
                        median_points: 500, top_points: 500, elite_median_points: 500 }],
}

test('junior-scoped meet hides the redundant Juniorer tile', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(juniorMeet)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DMJ-L', meetId: 'C2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Combined Champs 2026' })).toBeInTheDocument())
  expect(screen.queryByText('Juniorer')).toBeNull()
  expect(screen.getByText('Deltagere')).toBeInTheDocument()   // kept
})

test('ordinary meet still shows the Juniorer tile', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.getByText('Juniorer')).toBeInTheDocument()
})

test('Meet renders facts and a race link', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.getByRole('heading', { level: 3, name: /løb/i })).toBeInTheDocument()
})

test('Meet shows a Stafet chip only when the meet has relays', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByRole('button', { name: 'Stafet' })
  expect(screen.getByRole('button', { name: 'Bryst' })).toBeInTheDocument()
})

test('Meet has no Stafet chip when there are no relays', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson) // 2 individual races, no relay
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByRole('button', { name: 'Fri' }) // racesJson has an individual Fri race
  expect(screen.queryByRole('button', { name: 'Stafet' })).toBeNull()
})

test('clicking Bryst narrows the list to bryst individual races', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await fireEvent.click(await screen.findByRole('button', { name: 'Bryst' }))
  expect(screen.getByRole('link', { name: /Kvinder 200m Bryst/ })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Mænd 100m Fri/ })).toBeNull()
  expect(screen.queryByRole('link', { name: /Mix 4x100m HM/ })).toBeNull()
})

test('clicking Stafet shows the relay and hides individual races', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(filterRacesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await fireEvent.click(await screen.findByRole('button', { name: 'Stafet' }))
  expect(screen.getByRole('link', { name: /Mix 4x100m HM/ })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /Mænd 100m Fri/ })).toBeNull()
})

test('Meet renders the coach evaluation with its disclaimers', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(evaluationJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByText(/Trænerens vurdering/)
  expect(screen.getByText(/AI-genereret, eksperimentelt/)).toBeInTheDocument()
  expect(screen.getByRole('heading', { level: 4, name: 'Samlet niveau' })).toBeInTheDocument()
  expect(screen.getByText(/ikke fakta/)).toBeInTheDocument()
  expect(screen.getByText(/maskinelt kontrolleret/)).toBeInTheDocument()
  expect(screen.getByText(/Testmodel/)).toBeInTheDocument()
})

// The digest carries numbers the page does not render (a sixth season of
// history, the per-stroke medians and deltas), so the footer must not promise
// that every number can be looked up in the tables above.
test('the coach footer does not claim the numbers are checkable on the page', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(evaluationJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await screen.findByText(/Trænerens vurdering/)
  expect(screen.queryByText(/efterprøves i tabellerne/)).toBeNull()
})

test('Meet renders nothing when there is no evaluation', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(null)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: meetJson.meet_name })).toBeInTheDocument())
  expect(screen.queryByText(/Trænerens vurdering/)).toBeNull()
})

test('the evaluation section starts collapsed', async () => {
  vi.spyOn(dc, 'getMeet').mockResolvedValue(meetJson)
  vi.spyOn(dc, 'getRaces').mockResolvedValue(racesJson)
  vi.spyOn(dc, 'getEvaluation').mockResolvedValue(evaluationJson)
  render(Meet, { params: { cat: 'DM-L', meetId: 'M2026' } })
  const summary = await screen.findByText(/Trænerens vurdering/)
  expect(summary.closest('details').open).toBe(false)
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

const juniorRace = {
  category: 'DMJ-L', meet_id: 'C2026', race_key: 'M-100-Fri-LCM',
  label: 'M 100m Fri', is_relay: false, junior_scoped: true,
  facts: {
    contestants: 4, dsq: 0, winning_time: '0:57.00', median_cs: 5775,
    spread_1_last_cs: 150, winner_points: 500,
    cutline_centiseconds: null, spread_1_8_cs: null, juniors: null,
  },
  podium: [{ rank: 1, name: 'Junior Fast', swimmer_id: 'cj1', club: 'AGF',
             time: '0:57.00', points: 500 }],
  season_comparison: [{ season: 2026, best_cs: 5700, median_cs: 5775,
                        top8_avg_cs: 5775, cutline_cs: null, swims: 4 }],
}

test('junior-scoped race hides senior-structure tiles', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(juniorRace)
  render(Race, { params: { cat: 'DMJ-L', meetId: 'C2026', raceKey: 'M-100-Fri-LCM' } })
  await waitFor(() => expect(screen.getByText('Junior Fast')).toBeInTheDocument())
  expect(screen.queryByText('A-finale-grænse')).toBeNull()
  expect(screen.queryByText('Spredning 1.–8.')).toBeNull()
  expect(screen.queryByText('Juniorer')).toBeNull()
  expect(screen.getByText('Deltagere')).toBeInTheDocument()   // kept
  expect(screen.queryByText(/A-finale-grænse pr\. sæson/)).toBeNull()   // cutline chart hidden
})

test('non-junior race still shows the A-finale-grænse tile', async () => {
  vi.spyOn(dc, 'getRace').mockResolvedValue(raceJson)
  render(Race, { params: { cat: 'DM-L', meetId: 'M2026', raceKey: 'M-100-Fri-LCM' } })
  await waitFor(() => expect(screen.getByText(raceJson.podium[0].name)).toBeInTheDocument())
  expect(screen.getByText('A-finale-grænse')).toBeInTheDocument()
  expect(screen.getByText(/A-finale-grænse pr\. sæson/)).toBeInTheDocument()   // cutline chart shown
})
