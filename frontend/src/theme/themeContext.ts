import { createContext } from 'react'

export type Theme = 'light' | 'dark'

export type ThemeContextValue = {
  theme: Theme
  setTheme: (theme: Theme) => void
}

export const ThemeContext = createContext<ThemeContextValue | null>(null)

export const LIGHT_QUERY = '(prefers-color-scheme: light)'

const FORCED_THEME_KEY = 'aicepeak.forcedTheme'

function asTheme(value: string | null): Theme | null {
  return value === 'light' || value === 'dark' ? value : null
}

/** The theme forced by `?theme=light|dark` in the URL, if any. */
function themeFromUrl(): Theme | null {
  return asTheme(new URLSearchParams(window.location.search).get('theme'))
}

/**
 * The theme forced by the URL, otherwise the one it forced earlier in this tab: Microsoft returns to /login without
 * the query. A theme in the URL always wins and replaces the stored one.
 */
export function forcedTheme(): Theme | null {
  const fromUrl = themeFromUrl()
  try {
    if (fromUrl) {
      sessionStorage.setItem(FORCED_THEME_KEY, fromUrl)
      return fromUrl
    }
    return asTheme(sessionStorage.getItem(FORCED_THEME_KEY))
  } catch {
    // Storage blocked: only the URL counts.
    return fromUrl
  }
}

/** The forced theme, otherwise the system setting; dark when the system gives no preference. */
export function initialTheme(): Theme {
  return forcedTheme() ?? (window.matchMedia?.(LIGHT_QUERY).matches ? 'light' : 'dark')
}
