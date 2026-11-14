import { useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from 'react'
import { forcedTheme, initialTheme, LIGHT_QUERY, ThemeContext, type Theme } from './themeContext.ts'

/** Provides light/dark mode to all components and sets `data-theme` on `<html>` for the design tokens. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme)

  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  // Follow the system setting unless the URL forces a theme.
  useEffect(() => {
    const query = forcedTheme() ? undefined : window.matchMedia?.(LIGHT_QUERY)
    if (!query) {
      return
    }
    const onChange = (event: MediaQueryListEvent) => setTheme(event.matches ? 'light' : 'dark')
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const value = useMemo(() => ({ theme, setTheme }), [theme])
  return <ThemeContext value={value}>{children}</ThemeContext>
}
