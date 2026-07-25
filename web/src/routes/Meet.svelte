<script>
  import { onMount } from 'svelte'
  import { getMeet, getRaces } from '../lib/dataClient.js'
  import { href } from '../router.js'
  import { formatInt, formatPoints, formatTimeStr, formatDelta } from '../lib/format.js'
  import { filterRaces, disciplineOptions, genderOptions } from '../lib/raceFilter.js'
  import Breadcrumbs from '../components/Breadcrumbs.svelte'
  import StatTile from '../components/StatTile.svelte'
  import TrendChart from '../components/TrendChart.svelte'

  // props: { params: { cat, meetId } }
  let { params = {} } = $props()

  let meet = $state(null)
  const jr = $derived(meet?.junior_scoped === true)
  let races = $state(null)
  let loading = $state(true)
  let err = $state(null)

  let discipline = $state('all')
  let gender = $state('all')

  const DISCIPLINE_LABEL = { all: 'Alle', Stafet: 'Stafet' } // strokes fall back to their own value
  const GENDER_LABEL = { all: 'Alle', M: 'Herrer', F: 'Damer', X: 'Mix' }

  const disciplines = $derived(races ? disciplineOptions(races) : ['all'])
  const genders = $derived(races ? genderOptions(races) : ['all'])
  const shownRaces = $derived(races ? filterRaces(races, { discipline, gender }) : [])

  onMount(load)

  async function load() {
    loading = true
    err = null
    try {
      const [m, r] = await Promise.all([
        getMeet(params.cat, params.meetId),
        getRaces(params.cat, params.meetId),
      ])
      meet = m
      races = r.races
    } catch (e) {
      err = e
    } finally {
      loading = false
    }
  }

  // season_comparison[0] is the meet's own season; [1] is the prior season on
  // record for this category (not necessarily season - 1).
  const prev = $derived(meet?.season_comparison?.[1] ?? null)

  const tiles = $derived(
    meet
      ? [
          {
            label: 'Deltagere',
            value: formatInt(meet.facts.entrants),
            delta: formatDelta(meet.facts.entrants, prev?.entrants),
          },
          {
            label: 'Løb',
            value: formatInt(meet.facts.events),
            delta: formatDelta(meet.facts.events, prev?.events),
          },
          {
            label: 'Klubber',
            value: formatInt(meet.facts.clubs),
            delta: formatDelta(meet.facts.clubs, prev?.clubs),
          },
          ...(jr ? [] : [{ label: 'Juniorer', value: formatInt(meet.facts.juniors) }]),
          {
            label: 'Median point',
            value: formatPoints(meet.facts.median_points),
            delta: formatDelta(meet.facts.median_points, prev?.median_points),
          },
          { label: 'Bedste point', value: formatPoints(meet.facts.top_points) },
        ]
      : [],
  )

  const crumbs = $derived([
    { label: params.cat, href: href('home', { cat: params.cat }) },
    { label: meet ? meet.meet_name : 'Stævne' },
  ])
</script>

{#if loading}
  <Breadcrumbs items={[{ label: params.cat, href: href('home', { cat: params.cat }) }, { label: 'Stævne' }]} />
  <p class="state muted">Indlæser…</p>
{:else if err}
  <Breadcrumbs items={[{ label: params.cat, href: href('home', { cat: params.cat }) }, { label: 'Stævne' }]} />
  <p class="state bad">Kunne ikke hentes.</p>
{:else}
  <Breadcrumbs items={crumbs} />

  <div class="meet-header">
    <h2 class="meet-title">{meet.meet_name}</h2>
    <div class="meet-meta muted">{meet.season} · {meet.meet_date}</div>
  </div>

  <div class="tile-grid">
    {#each tiles as t (t.label)}
      <StatTile label={t.label} value={t.value} delta={t.delta} />
    {/each}
  </div>

  <div class="chart-grid">
    <TrendChart
      data={meet.season_comparison}
      x="season"
      y="entrants"
      yLabel="Deltagere pr. sæson"
      format={formatInt}
    />
    <TrendChart
      data={meet.season_comparison}
      x="season"
      y="median_points"
      yLabel="Median point pr. sæson"
      format={formatInt}
    />
    <TrendChart
      data={meet.season_comparison}
      x="season"
      y="elite_median_points"
      yLabel="Elite-median point pr. sæson (top 10 pr. løb)"
      format={formatInt}
    />
  </div>

  <div class="race-head">
    <h3 class="section-title">Løb</h3>
    <span class="race-tally muted">{formatInt(shownRaces.length)}</span>
  </div>

  {#if races.length === 0}
    <p class="state muted">Ingen løb fundet.</p>
  {:else}
    <div class="filters">
      <div class="filter-group" role="group" aria-label="Disciplin">
        {#each disciplines as d (d)}
          <button
            type="button"
            class="chip"
            aria-pressed={discipline === d}
            onclick={() => (discipline = d)}
          >{DISCIPLINE_LABEL[d] ?? d}</button>
        {/each}
      </div>
      <div class="filter-group" role="group" aria-label="Køn">
        {#each genders as g (g)}
          <button
            type="button"
            class="chip"
            aria-pressed={gender === g}
            onclick={() => (gender = g)}
          >{GENDER_LABEL[g] ?? g}</button>
        {/each}
      </div>
    </div>

    {#if shownRaces.length === 0}
      <p class="state muted">Ingen løb matcher filteret.</p>
    {:else}
      <ul class="race-list">
        {#each shownRaces as r (r.race_key)}
          <li>
            <a class="race-row" href={href('race', { cat: params.cat, meetId: params.meetId, raceKey: r.race_key })}>
              <span class="race-label">{r.label}</span>
              <span class="race-winner muted">{r.winner_name ?? '–'}</span>
              <span class="race-time num">{formatTimeStr(r.winning_time)}</span>
              <span class="race-count num muted">{formatInt(r.contestants)} {r.is_relay ? 'hold' : 'deltagere'}</span>
            </a>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
{/if}

<style>
  .state {
    font-size: 0.95rem;
    padding: var(--space-4) 0;
  }

  .muted {
    color: var(--muted);
  }

  .bad {
    color: var(--bad);
  }

  .meet-header {
    margin-bottom: var(--space-4);
  }

  .meet-title {
    margin: 0;
    font-size: 1.4rem;
    font-weight: 700;
  }

  .meet-meta {
    margin-top: var(--space-1);
    font-size: 0.88rem;
  }

  .tile-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-4);
  }

  .chart-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    gap: var(--space-3);
    margin-bottom: var(--space-5);
  }

  .section-title {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin: 0 0 var(--space-2);
  }

  .race-head {
    display: flex;
    align-items: baseline;
    gap: var(--space-2);
    margin: 0 0 var(--space-2);
  }

  .race-head .section-title {
    margin: 0;
  }

  .race-tally {
    font-size: 0.8rem;
  }

  .filters {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }

  .filter-group {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
  }

  .chip {
    font: inherit;
    font-size: 0.82rem;
    cursor: pointer;
    padding: var(--space-1) var(--space-2);
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: border-color 0.15s ease, background 0.15s ease;
  }

  .chip:hover {
    border-color: var(--accent);
  }

  .chip[aria-pressed='true'] {
    border-color: var(--accent);
    background: var(--accent);
    color: #fff;
  }

  .race-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .race-row {
    display: grid;
    grid-template-columns: 2fr 1.4fr auto auto;
    align-items: center;
    gap: var(--space-3);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--space-2) var(--space-3);
    color: var(--text);
    text-decoration: none;
    transition: border-color 0.15s ease;
  }

  .race-row:hover {
    border-color: var(--accent);
  }

  .race-label {
    font-weight: 600;
    font-size: 0.92rem;
  }

  .race-winner,
  .race-count {
    font-size: 0.82rem;
  }

  .race-time {
    font-weight: 700;
    font-size: 0.95rem;
  }

  @media (max-width: 32rem) {
    .race-row {
      grid-template-columns: 1fr;
      gap: var(--space-1);
    }
  }
</style>
