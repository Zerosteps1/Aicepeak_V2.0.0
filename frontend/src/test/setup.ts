import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach } from 'vitest'
import { stubMatchMedia } from './matchMedia.ts'

// jsdom has no matchMedia; tests that need a system setting call stubMatchMedia again.
beforeEach(() => {
  stubMatchMedia(false)
})

// Testing Library cleans up automatically only when test globals are enabled; they are not.
afterEach(() => {
  cleanup()
})
