<script>
  import { theme, toggleTheme } from './theme.js'
  import { route } from './router.js'
  let { children } = $props()
</script>

<header>
  <h1 class="wordmark">Swimtrends</h1>
  <button class="theme-toggle" onclick={toggleTheme} aria-label="Skift tema">
    {$theme === 'dark' ? '☀︎' : '☾'}
  </button>
</header>
<main>
  {#if $route.name === 'race'}
    <p>Løb: {$route.params.raceKey}</p>
  {:else if $route.name === 'meet'}
    <p>Stævne: {$route.params.meetId}</p>
  {:else}
    <p>Forside</p>
  {/if}
</main>
<footer>
  <a href="https://xn--svmmetider-1cb.dk" rel="noreferrer">Data fra svømmetider.dk</a>
</footer>
