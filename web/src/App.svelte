<script>
  import { theme, toggleTheme } from './theme.js'
  let { children } = $props()
</script>

<header>
  <h1 class="wordmark">Swimtrends</h1>
  <button class="theme-toggle" onclick={toggleTheme} aria-label="Skift tema">
    {$theme === 'dark' ? '☀︎' : '☾'}
  </button>
</header>
<main>{@render children?.()}</main>
<footer>
  <a href="https://xn--svmmetider-1cb.dk" rel="noreferrer">Data fra svømmetider.dk</a>
</footer>
