<script>
  import { onMount } from 'svelte'
  import { getRace } from '../lib/dataClient.js'
  import { href } from '../router.js'
  import { formatInt, formatTime, formatTimeStr } from '../lib/format.js'
  import Breadcrumbs from '../components/Breadcrumbs.svelte'
  import StatTile from '../components/StatTile.svelte'
  import TrendChart from '../components/TrendChart.svelte'
  import Podium from '../components/Podium.svelte'

  // props: { params: { cat, meetId, raceKey } }
  let { params = {} } = $props()

  let race = $state(null)
  let loading = $state(true)
  let err = $state(null)

  onMount(load)

  async function load() {
    loading = true
    err = null
    try {
      race = await getRace(params.cat, params.meetId, params.raceKey)
    } catch (e) {
      err = e
    } finally {
      loading = false
    }
  }

  const tiles = $derived(
    race
      ? [
          { label: race.is_relay ? 'Hold' : 'Deltagere', value: formatInt(race.facts.contestants) },
          { label: 'Diskvalifikationer', value: formatInt(race.facts.dsq) },
          { label: 'Vindertid', value: formatTimeStr(race.facts.winning_time) },
          ...(race.is_relay ? [] : [
            { label: 'A-finale-grænse', value: formatTime(race.facts.cutline_centiseconds) },
          ]),
          { label: 'Median', value: formatTime(race.facts.median_cs) },
          ...(race.is_relay ? [] : [
            { label: 'Spredning 1.–8.', value: formatTime(race.facts.spread_1_8_cs) },
            { label: 'Juniorer', value: formatInt(race.facts.juniors) },
          ]),
        ]
      : [],
  )

  const crumbs = $derived([
    { label: params.cat, href: href('home', { cat: params.cat }) },
    { label: 'Stævne', href: href('meet', { cat: params.cat, meetId: params.meetId }) },
    { label: race ? race.label : 'Løb' },
  ])
</script>

{#if loading}
  <Breadcrumbs
    items={[
      { label: params.cat, href: href('home', { cat: params.cat }) },
      { label: 'Stævne', href: href('meet', { cat: params.cat, meetId: params.meetId }) },
      { label: 'Løb' },
    ]}
  />
  <p class="state muted">Indlæser…</p>
{:else if err}
  <Breadcrumbs
    items={[
      { label: params.cat, href: href('home', { cat: params.cat }) },
      { label: 'Stævne', href: href('meet', { cat: params.cat, meetId: params.meetId }) },
      { label: 'Løb' },
    ]}
  />
  <p class="state bad">Kunne ikke hentes.</p>
{:else}
  <Breadcrumbs items={crumbs} />

  <h2 class="race-title">{race.label}</h2>

  <div class="tile-grid">
    {#each tiles as t (t.label)}
      <StatTile label={t.label} value={t.value} />
    {/each}
  </div>

  <Podium podium={race.podium} />

  <div class="chart-grid">
    <TrendChart
      data={race.season_comparison}
      x="season"
      y="best_cs"
      yLabel="Bedste tid pr. sæson"
      lowerIsBetter={true}
      format={formatTime}
    />
    <TrendChart
      data={race.season_comparison}
      x="season"
      y="median_cs"
      yLabel="Median tid pr. sæson"
      lowerIsBetter={true}
      format={formatTime}
    />
    {#if !race.is_relay}
      <TrendChart
        data={race.season_comparison}
        x="season"
        y="cutline_cs"
        yLabel="A-finale-grænse pr. sæson"
        lowerIsBetter={true}
        format={formatTime}
      />
    {/if}
    <TrendChart
      data={race.season_comparison}
      x="season"
      y="swims"
      yLabel="Antal starter pr. sæson"
      format={formatInt}
    />
  </div>
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

  .race-title {
    margin: 0 0 var(--space-4);
    font-size: 1.4rem;
    font-weight: 700;
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
  }
</style>
