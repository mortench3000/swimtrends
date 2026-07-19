<script>
  // items: [{ label, href? }] — the last item is treated as "you are here"
  // (no link) unless it explicitly carries an href.
  let { items = [] } = $props()
</script>

<nav class="breadcrumbs" aria-label="Brødkrumme">
  {#each items as item, i}
    {#if i > 0}
      <span class="crumb-sep" aria-hidden="true">▸</span>
    {/if}
    {#if item.href}
      <a href={item.href}>{item.label}</a>
    {:else}
      <span class="crumb-current" aria-current="page">{item.label}</span>
    {/if}
  {/each}
</nav>

<style>
  .breadcrumbs {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-1);
    font-size: 0.85rem;
    color: var(--muted);
    margin-bottom: var(--space-3);
  }

  .breadcrumbs a {
    color: var(--muted);
    text-decoration: none;
  }

  .breadcrumbs a:hover {
    color: var(--accent);
    text-decoration: underline;
  }

  .crumb-current {
    color: var(--text);
    font-weight: 600;
  }

  .crumb-sep {
    color: var(--border);
  }
</style>
