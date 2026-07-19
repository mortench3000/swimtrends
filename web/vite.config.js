import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

export default defineConfig({
  plugins: [svelte()],
  resolve: process.env.VITEST ? { conditions: ['browser'] } : undefined,
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.js'], globals: true },
})
