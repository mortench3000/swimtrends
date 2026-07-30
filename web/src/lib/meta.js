// Client-side <head> updates on navigation. The tags themselves live in
// index.html (and are stamped by prerender.mjs for the static shells), so this
// only ever overwrites — prerender.mjs is what fails loudly if they go missing.
import { canonical } from './seo.js'

export function setMeta({ title, description }, path = location.pathname) {
  document.title = title
  set('meta[name="description"]', 'content', description)
  set('link[rel="canonical"]', 'href', canonical(path))
}

function set(selector, attr, value) {
  document.head.querySelector(selector)?.setAttribute(attr, value)
}
