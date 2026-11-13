import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// Testing Library cleans up automatically only when test globals are enabled; they are not.
afterEach(() => {
  cleanup()
})
