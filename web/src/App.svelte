<script>
  import { theme, toggleTheme } from './theme.js'
  import { route } from './router.js'
  import Home from './routes/Home.svelte'
  import Meet from './routes/Meet.svelte'
  import Race from './routes/Race.svelte'
</script>

<header>
  <h1 class="wordmark">Swimtrends</h1>
  <button class="theme-toggle" onclick={toggleTheme} aria-label="Skift tema">
    {$theme === 'dark' ? '☀︎' : '☾'}
  </button>
</header>
<main>
  {#if $route.name === 'race'}
    {#key `${$route.params.cat}/${$route.params.meetId}/${$route.params.raceKey}`}
      <Race params={$route.params} />
    {/key}
  {:else if $route.name === 'meet'}
    {#key `${$route.params.cat}/${$route.params.meetId}`}
      <Meet params={$route.params} />
    {/key}
  {:else}
    {#key $route.params.cat}
      <Home params={$route.params} />
    {/key}
  {/if}
</main>
<footer>
  <a href="https://xn--svmmetider-1cb.dk" rel="noreferrer">Data fra svømmetider.dk</a>
</footer>
