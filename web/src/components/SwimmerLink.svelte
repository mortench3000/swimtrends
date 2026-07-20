<script>
  // A swimmer's name linking to their svømmetider.dk profile, opening in a new
  // tab. Falls back to plain text when there is no id (relay/missing swimmer).
  let { name, id } = $props()
  const TITLE = 'Åbn svømmerprofil på svømmetider.dk (åbner i ny fane)'
</script>

{#if id != null && id !== ''}
  <a
    class="swimmer-link"
    href={`https://svømmetider.dk/svoemmer/?${id}`}
    target="_blank"
    rel="noopener noreferrer"
    title={TITLE}
    aria-label={`${name} — ${TITLE}`}
  >
    {name}<svg
      class="ext"
      viewBox="0 0 24 24"
      width="0.7em"
      height="0.7em"
      aria-hidden="true"
    >
      <path
        d="M14 3h7v7M21 3 10 14M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      />
    </svg>
  </a>
{:else}
  {name}
{/if}

<style>
  .swimmer-link {
    color: inherit;
    text-decoration: none;
    border-bottom: 1px dotted var(--muted);
    transition: color 0.12s, border-color 0.12s;
  }
  .swimmer-link:hover,
  .swimmer-link:focus-visible {
    color: var(--accent-strong);
    border-bottom-color: var(--accent-strong);
  }
  .ext {
    margin-left: 0.3em;
    vertical-align: baseline;
    opacity: 0.55;
  }
  .swimmer-link:hover .ext,
  .swimmer-link:focus-visible .ext {
    opacity: 1;
  }
</style>
