<script>
  import * as Plot from '@observablehq/plot'
  import { formatInt } from '../lib/format.js'

  // props: { data, x, y, kind='line', yLabel, lowerIsBetter=false, format }
  // data: rows already keyed by season (desc or asc — sorted internally).
  // format: value -> string, used for both axis ticks and direct point labels.
  let {
    data = [],
    x,
    y,
    kind = 'line',
    yLabel = '',
    lowerIsBetter = false,
    format = formatInt,
  } = $props()

  let el

  const rows = $derived(
    (data ?? [])
      .filter((d) => d[y] != null)
      .slice()
      .sort((a, b) => a[x] - b[x]),
  )

  $effect(() => {
    // Re-run whenever `rows` (or el) changes; Plot renders a fresh SVG each
    // time rather than patching, which is fine at this data scale (<=5 pts).
    const container = el
    if (!container) return
    container.replaceChildren()
    if (rows.length === 0) return

    const width = container.clientWidth || 320
    const marks = [Plot.gridY({ stroke: 'var(--border)' })]

    if (kind === 'bar') {
      marks.push(Plot.barY(rows, { x, y, fill: 'var(--accent)', rx: 3 }))
    } else {
      marks.push(
        Plot.line(rows, { x, y, stroke: 'var(--accent)', strokeWidth: 2 }),
        Plot.dot(rows, {
          x,
          y,
          r: 4,
          fill: 'var(--accent)',
          stroke: 'var(--surface)',
          strokeWidth: 1.5,
        }),
      )
    }
    marks.push(
      Plot.text(rows, {
        x,
        y,
        text: (d) => format(d[y]),
        dy: -12,
        fill: 'var(--text)',
        fontSize: 11,
      }),
    )

    const plot = Plot.plot({
      width,
      height: 180,
      marginLeft: 56,
      marginBottom: 26,
      marginTop: 18,
      style: {
        background: 'transparent',
        color: 'var(--muted)',
        fontFamily: 'inherit',
        fontSize: '11px',
      },
      x: { type: 'point', label: null, tickFormat: (d) => String(d) },
      y: { label: null, grid: false, reverse: lowerIsBetter, nice: true, tickFormat: format },
      marks,
    })
    container.appendChild(plot)
    return () => plot.remove()
  })
</script>

<div class="trend-chart">
  {#if yLabel}
    <h4 class="trend-title">
      {yLabel}
      {#if lowerIsBetter}<span class="trend-hint">(lavere er bedre)</span>{/if}
    </h4>
  {/if}
  {#if rows.length === 0}
    <p class="trend-empty muted">Ingen data.</p>
  {:else}
    <div class="trend-canvas" bind:this={el}></div>
    <ul class="sr-only">
      {#each rows as r}
        <li>{r[x]}: {format(r[y])}</li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .trend-chart {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--space-3);
  }

  .trend-title {
    margin: 0 0 var(--space-2);
    font-size: 0.78rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }

  .trend-hint {
    text-transform: none;
    font-weight: 400;
    letter-spacing: normal;
    opacity: 0.8;
  }

  .trend-canvas {
    width: 100%;
    min-height: 180px;
  }

  .trend-empty {
    font-size: 0.85rem;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    list-style: none;
    padding: 0;
  }
</style>
