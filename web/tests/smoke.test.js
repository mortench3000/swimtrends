import { render, screen } from '@testing-library/svelte'
import { expect, test } from 'vitest'
import App from '../src/App.svelte'

test('shell shows title and Danish attribution', () => {
  render(App)
  expect(screen.getByText('Swimtrends')).toBeInTheDocument()
  expect(screen.getByText(/Data fra svømmetider\.dk/)).toBeInTheDocument()
})
