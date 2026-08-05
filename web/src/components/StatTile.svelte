<script>
  // props: { label, value, share?, delta? } — delta: { text, dir: 'good'|'bad'|'flat' }
  let { label, value, share = null, delta = null } = $props()
</script>

<div class="stat-tile">
  <div class="stat-label">{label}</div>
  <div class="stat-value num">{value}{#if share}<span class="stat-share">{share}</span>{/if}</div>
  {#if delta}
    <div class="stat-delta num dir-{delta.dir}">
      {delta.text}
      <span class="sr-only">
        {delta.dir === 'good' ? 'forbedring' : delta.dir === 'bad' ? 'forværring' : 'uændret'} siden sidste sæson
      </span>
    </div>
  {/if}
</div>

<style>
  .stat-tile {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--space-3);
  }

  .stat-label {
    font-size: 0.72rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }

  .stat-value {
    font-size: 1.6rem;
    font-weight: 700;
    margin-top: var(--space-1);
    line-height: 1.1;
  }

  .stat-share {
    margin-left: 0.35em;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--muted);
    white-space: nowrap;
  }

  .stat-delta {
    margin-top: var(--space-1);
    font-size: 0.8rem;
    font-weight: 600;
  }

  .dir-good {
    color: var(--good);
  }

  .dir-bad {
    color: var(--bad);
  }

  .dir-flat {
    color: var(--muted);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
</style>
