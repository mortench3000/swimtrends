import '@fontsource/inter'
import './app.css'
import App from './App.svelte'
import { mount } from 'svelte'
// Svelte 5's mount() appends, so the prerendered static body (prerender.mjs)
// would stay on screen underneath the hydrated app. Clear it first.
const target = document.getElementById('app')
target.replaceChildren()
export default mount(App, { target })
