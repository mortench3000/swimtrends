<script>
  import { onMount } from 'svelte'
  import { getIndex, getMeets } from '../lib/dataClient.js'
  import { href, navigate } from '../router.js'
  import { formatInt } from '../lib/format.js'
  import { setMeta } from '../lib/meta.js'
  import { categoryMeta, homeMeta } from '../lib/seo.js'
  import Breadcrumbs from '../components/Breadcrumbs.svelte'

  // props: { params } — params.cat preselects a category; falls back to the
  // first category once the index has loaded.
  let { params = {} } = $props()

  let index = $state(null)
  let cat = $state(params.cat || null)
  let meets = $state(null)
  let loading = $state(true)
  let err = $state(null)
  let meetsErr = $state(null)

  onMount(load)

  async function load() {
    loading = true
    err = null
    try {
      index = await getIndex()
      if (!cat) cat = index.categories[0]?.code ?? null
      // The bare root stays the site landing page; /DM-L is the category page.
      setMeta(params.cat ? categoryMeta(cat) : homeMeta())
      await loadMeets()
    } catch (e) {
      err = e
    } finally {
      loading = false
    }
  }

  async function loadMeets() {
    if (!cat) return
    meets = null
    meetsErr = null
    try {
      const res = await getMeets(cat)
      meets = res.meets
    } catch (e) {
      meetsErr = e
    }
  }

  function pick(code) {
    if (code === cat) return
    cat = code
    // navigate() re-keys the route in App.svelte, which remounts this component
    // and re-runs load() — hence no setMeta here.
    navigate(href('home', { cat }))
    loadMeets()
  }
</script>

<Breadcrumbs items={[{ label: 'Kategori' }]} />

{#if loading}
  <p class="state muted">Indlæser…</p>
{:else if err}
  <p class="state bad">Kunne ikke hentes.</p>
{:else}
  <div class="chips" role="tablist" aria-label="Kategori">
    {#each index.categories as c (c.code)}
      <button
        type="button"
        class="chip"
        class:active={c.code === cat}
        role="tab"
        aria-selected={c.code === cat}
        onclick={() => pick(c.code)}
      >
        {c.code}
      </button>
    {/each}
  </div>

  {#if meetsErr}
    <p class="state bad">Kunne ikke hentes.</p>
  {:else if meets === null}
    <p class="state muted">Indlæser…</p>
  {:else if meets.length === 0}
    <p class="state muted">Ingen stævner fundet.</p>
  {:else}
    <div class="meet-grid">
      {#each meets as m (m.meet_id)}
        <a class="meet-card" href={href('meet', { cat, meetId: m.meet_id })}>
          <h3 class="meet-name">{m.meet_name}</h3>
          <div class="meet-meta muted">{m.season} · {m.meet_date}</div>
          <div class="meet-stats num muted">
            {formatInt(m.entrants)} deltagere · {formatInt(m.events)} løb · {formatInt(m.clubs)} klubber
          </div>
        </a>
      {/each}
    </div>
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

  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
  }

  .chip {
    background: var(--surface);
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 999px;
    padding: 0.4rem 0.95rem;
    font-size: 0.85rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    cursor: pointer;
    transition:
      border-color 0.15s ease,
      color 0.15s ease,
      background 0.15s ease;
  }

  .chip:hover {
    border-color: var(--accent);
    color: var(--text);
  }

  .chip.active {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--bg);
  }

  .meet-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: var(--space-3);
  }

  .meet-card {
    display: block;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--space-3);
    color: var(--text);
    text-decoration: none;
    transition: border-color 0.15s ease;
  }

  .meet-card:hover {
    border-color: var(--accent);
  }

  .meet-name {
    margin: 0;
    font-size: 1.02rem;
    font-weight: 700;
  }

  .meet-meta {
    margin-top: var(--space-1);
    font-size: 0.82rem;
  }

  .meet-stats {
    margin-top: var(--space-2);
    font-size: 0.8rem;
  }
</style>
