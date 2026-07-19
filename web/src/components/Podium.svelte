<script>
  import { formatTimeStr, formatPoints } from '../lib/format.js'

  // props: { podium } — rows { rank, name, club, time, points }
  let { podium = [] } = $props()

  const byRank = (r) => podium.find((p) => p.rank === r)
  // Physical podium order: silver, gold, bronze — gold stands tallest & centred.
  const order = [2, 1, 3]
</script>

<div class="podium">
  {#each order as r}
    {@const p = byRank(r)}
    {#if p}
      <div class="podium-block rank-{r}">
        <div class="podium-info">
          <div class="podium-name">{p.name}</div>
          <div class="podium-club muted">{p.club}</div>
          <div class="podium-time num">{formatTimeStr(p.time)}</div>
          <div class="podium-points num muted">{formatPoints(p.points)}</div>
        </div>
        <div class="podium-riser">{r}</div>
      </div>
    {/if}
  {/each}
</div>

<style>
  .podium {
    display: flex;
    align-items: flex-end;
    justify-content: center;
    gap: var(--space-3);
    margin: var(--space-4) 0;
  }

  .podium-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 9rem;
  }

  .podium-info {
    text-align: center;
    margin-bottom: var(--space-2);
  }

  .podium-name {
    font-weight: 700;
    font-size: 0.95rem;
    overflow-wrap: anywhere;
  }

  .podium-club {
    font-size: 0.78rem;
    margin-top: 2px;
  }

  .podium-time {
    font-size: 1.05rem;
    font-weight: 700;
    margin-top: var(--space-1);
  }

  .podium-points {
    font-size: 0.78rem;
  }

  .podium-riser {
    width: 100%;
    border-radius: var(--radius) var(--radius) 0 0;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding-top: var(--space-1);
    font-weight: 700;
    font-size: 1.1rem;
  }

  .rank-1 .podium-riser {
    height: 5.5rem;
    background: var(--accent-strong);
    color: var(--bg);
  }

  .rank-2 .podium-riser {
    height: 3.75rem;
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--text);
  }

  .rank-3 .podium-riser {
    height: 2.75rem;
    background: var(--warn);
    color: var(--bg);
  }
</style>
