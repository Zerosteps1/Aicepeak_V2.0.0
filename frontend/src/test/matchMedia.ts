import { vi } from 'vitest'

const LIGHT_QUERY = '(prefers-color-scheme: light)'

/**
 * Stubs `window.matchMedia` (jsdom has none) with a system that prefers light or not.
 * Returns a function that changes the system setting and notifies the listeners.
 */
export function stubMatchMedia(prefersLight: boolean) {
  let light = prefersLight
  const listeners = new Set<(event: MediaQueryListEvent) => void>()

  vi.stubGlobal('matchMedia', (query: string) => ({
    media: query,
    get matches() {
      return query === LIGHT_QUERY && light
    },
    onchange: null,
    addEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: (event: MediaQueryListEvent) => void) => listeners.delete(listener),
    dispatchEvent: () => true,
  }))

  return (nowLight: boolean) => {
    light = nowLight
    listeners.forEach((listener) => listener({ matches: nowLight, media: LIGHT_QUERY } as MediaQueryListEvent))
  }
}
