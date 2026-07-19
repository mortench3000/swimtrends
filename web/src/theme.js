import { writable } from 'svelte/store'

const KEY = 'swimtrends-theme'
const initial = (typeof localStorage !== 'undefined' && localStorage.getItem(KEY)) || 'dark'
export const theme = writable(initial)
theme.subscribe((v) => {
  if (typeof document !== 'undefined') document.documentElement.setAttribute('data-theme', v)
  if (typeof localStorage !== 'undefined') localStorage.setItem(KEY, v)
})
export function toggleTheme() {
  theme.update((v) => (v === 'dark' ? 'light' : 'dark'))
}
