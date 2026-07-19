<script>
  import { theme, toggleTheme } from './theme.js'
  let { children } = $props()
</script>

<header>
  <span class="wordmark">Swimtrends</span>
  <button class="theme-toggle" onclick={toggleTheme} aria-label="Skift tema">
    {$theme === 'dark' ? '☀︎' : '☾'}
  </button>
</header>
<main>{@render children?.()}</main>
<footer>
  <a href="https://xn--svmmetider-1cb.dk" rel="noreferrer">Data fra svømmetider.dk</a>
</footer>
