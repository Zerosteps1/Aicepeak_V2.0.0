import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { stubMatchMedia } from '../test/matchMedia.ts'
import { ThemeProvider } from './ThemeProvider.tsx'
import { useTheme } from './useTheme.ts'

function NestedConsumer() {
  const { theme, setTheme } = useTheme()
  return (
    <button type="button" onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}>
      {theme}
    </button>
  )
}

function renderWithTheme() {
  render(
    <ThemeProvider>
      <section>
        <div>
          <NestedConsumer />
        </div>
      </section>
    </ThemeProvider>,
  )
  return screen.getByRole('button')
}

afterEach(() => {
  window.history.replaceState(null, '', '/')
  sessionStorage.clear()
})

describe('ThemeProvider', () => {
  it('AC-13: exposes the system theme to a nested component and sets data-theme on <html>', () => {
    stubMatchMedia(true)

    const consumer = renderWithTheme()

    expect(consumer).toHaveTextContent('light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('AC-13: falls back to dark when the system does not prefer light', () => {
    stubMatchMedia(false)

    expect(renderWithTheme()).toHaveTextContent('dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('AC-13: falls back to dark when the browser has no matchMedia', () => {
    vi.stubGlobal('matchMedia', undefined)

    expect(renderWithTheme()).toHaveTextContent('dark')
  })

  it.each(['light', 'dark'] as const)('AC-13: ?theme=%s in the URL overrides the system setting', (theme) => {
    const changeSystem = stubMatchMedia(theme === 'dark')
    window.history.replaceState(null, '', `/login?theme=${theme}`)

    const consumer = renderWithTheme()
    act(() => changeSystem(theme === 'dark'))

    expect(consumer).toHaveTextContent(theme)
    expect(document.documentElement).toHaveAttribute('data-theme', theme)
  })

  it('AC-13: a theme forced by the URL is kept when Microsoft returns to /login without the query', () => {
    stubMatchMedia(true)
    window.history.replaceState(null, '', '/login?theme=dark')
    renderWithTheme()
    cleanup()
    window.history.replaceState(null, '', '/login')

    const consumer = renderWithTheme()

    expect(consumer).toHaveTextContent('dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })

  it('AC-13: ?theme=light in the URL overrides a theme forced earlier and replaces it', () => {
    stubMatchMedia(false)
    window.history.replaceState(null, '', '/login?theme=dark')
    renderWithTheme()
    cleanup()
    window.history.replaceState(null, '', '/login?theme=light')

    expect(renderWithTheme()).toHaveTextContent('light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
    cleanup()
    window.history.replaceState(null, '', '/login')
    expect(renderWithTheme()).toHaveTextContent('light')
  })

  it('AC-13: follows changes of the system setting', () => {
    const changeSystem = stubMatchMedia(false)
    const consumer = renderWithTheme()

    act(() => changeSystem(true))

    expect(consumer).toHaveTextContent('light')
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })

  it('AC-13: setTheme switches the theme for all components', () => {
    stubMatchMedia(true)
    const consumer = renderWithTheme()

    fireEvent.click(consumer)

    expect(consumer).toHaveTextContent('dark')
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
  })
})
