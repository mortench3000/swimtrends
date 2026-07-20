<script>
  import { onMount } from 'svelte'
  import { getMeet, getRaces } from '../lib/dataClient.js'
  import { href } from '../router.js'
  import { formatInt, formatPoints, formatTimeStr, formatDelta } from '../lib/format.js'
  import Breadcrumbs from '../components/Breadcrumbs.svelte'
  import StatTile from '../components/StatTile.svelte'
  import TrendChart from '../components/TrendChart.svelte'

  // props: { params: { cat, meetId } }
  let { params = {} } = $props()

  let meet = $state(null)
  let races = $state(null)
  let loading = $state(true)
  let err = $state(null)

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
          { label: 'Juniorer', value: formatInt(meet.facts.juniors) },
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

  <h3 class="section-title">Løb</h3>
  {#if races.length === 0}
    <p class="state muted">Ingen løb fundet.</p>
  {:else}
    <ul class="race-list">
      {#each races as r (r.race_key)}
        <li>
          <a class="race-row" href={href('race', { cat: params.cat, meetId: params.meetId, raceKey: r.race_key })}>
            <span class="race-label">{r.label}</span>
            <span class="race-winner muted">{r.winner_name ?? '–'}</span>
            <span class="race-time num">{formatTimeStr(r.winning_time)}</span>
            <span class="race-count num muted">{formatInt(r.contestants)} deltagere</span>
          </a>
        </li>
      {/each}
    </ul>
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
