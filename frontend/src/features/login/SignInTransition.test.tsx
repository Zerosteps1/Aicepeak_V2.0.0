import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SignInTransition } from './SignInTransition.tsx'

function transition(phase: 'out' | 'auth' | 'in', onDone: () => void) {
  return (
    <SignInTransition phase={phase} background={<button type="button">App</button>} onDone={onDone}>
      <button type="button">Karte</button>
    </SignInTransition>
  )
}

function renderTransition(phase: 'out' | 'auth' | 'in', onDone = vi.fn<() => void>()) {
  return { ...render(transition(phase, onDone)), onDone }
}

/** jsdom runs no CSS transitions: report these for the app layer behind the card. */
function stubTransition(transitionDuration: string, transitionDelay: string) {
  const original = window.getComputedStyle.bind(window)
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element, pseudo) => {
    const style = original(element, pseudo)
    if (element instanceof HTMLElement && element.dataset.testid === 'sign-in-background') {
      return { ...style, transitionDuration, transitionDelay } as CSSStyleDeclaration
    }
    return style
  })
}

function transitionEnd(propertyName: string) {
  const event = new Event('transitionend', { bubbles: true })
  Object.defineProperty(event, 'propertyName', { value: propertyName })
  return event
}

describe('SignInTransition', () => {
  it.each(['out', 'auth'] as const)('AC-22: in phase %s the background is inert and hidden, the card is usable', (phase) => {
    const { onDone } = renderTransition(phase)

    const background = screen.getByTestId('sign-in-background')
    expect(background).toHaveAttribute('inert')
    expect(background).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('button', { name: 'Karte' }).closest('[inert]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'App' })).not.toBeInTheDocument()
    expect(onDone).not.toHaveBeenCalled()
  })

  it('signing in frees the background and takes the card out of reach', () => {
    const { onDone, rerender } = renderTransition('auth')

    rerender(transition('in', onDone))

    const background = screen.getByTestId('sign-in-background')
    expect(background).not.toHaveAttribute('inert')
    expect(background).not.toHaveAttribute('aria-hidden')
    expect(screen.getByText('Karte').closest('[inert]')).not.toBeNull()
  })

  it('calls onDone at once when no transition runs (reduced motion)', () => {
    const { onDone, rerender } = renderTransition('auth')

    rerender(transition('in', onDone))

    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('waits for the zoom of the app behind the card before calling onDone', () => {
    stubTransition('1.2s, 1200ms', '0s')
    const { onDone, rerender } = renderTransition('auth')

    rerender(transition('in', onDone))
    expect(onDone).not.toHaveBeenCalled()

    const background = screen.getByTestId('sign-in-background')
    fireEvent(background, transitionEnd('filter'))
    expect(onDone).not.toHaveBeenCalled()
    fireEvent(background, transitionEnd('transform'))
    fireEvent(background, transitionEnd('transform'))
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('calls onDone after the longest transition when transitionend never arrives', () => {
    vi.useFakeTimers()
    try {
      stubTransition('520ms, 1.2s', '0s, 100ms')
      const { onDone, rerender } = renderTransition('auth')

      rerender(transition('in', onDone))
      vi.advanceTimersByTime(1300 + 99)
      expect(onDone).not.toHaveBeenCalled()
      vi.advanceTimersByTime(1)
      expect(onDone).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('calls onDone at once when it is shown already signed in', () => {
    stubTransition('1.2s', '0s')

    const { onDone } = renderTransition('in')

    expect(onDone).toHaveBeenCalledTimes(1)
  })
})
