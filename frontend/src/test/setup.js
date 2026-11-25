import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'
import { isConnected, subscribe } from '../realtime'

// Tests never open a realtime connection; they trigger signals by hand.
vi.mock('../realtime', () => ({ subscribe: vi.fn(), isConnected: vi.fn() }))
beforeEach(() => {
  vi.mocked(subscribe).mockImplementation(() => () => {})
  vi.mocked(isConnected).mockReturnValue(false)
})

// Every request must be explicitly handled by a fixture; never use a real API.
beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error(
        'Unexpected fetch: add a deterministic response in this test.',
      )
    }),
  )
})
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})
