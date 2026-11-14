import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SignInTransition } from './SignInTransition.tsx'

function renderTransition(phase: 'out' | 'auth' | 'in', onDone = vi.fn<() => void>()) {
  const view = render(
    <SignInTransition phase={phase} background={<button type="button">App</button>} onDone={onDone}>
      <button type="button">Karte</button>
    </SignInTransition>,
  )
  return { ...view, onDone }
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

  it('AC-23: without an animation yet, calls onDone as soon as the phase is in and frees the background', () => {
    const { onDone, rerender } = renderTransition('auth')

    rerender(
      <SignInTransition phase="in" background={<button type="button">App</button>} onDone={onDone}>
        <button type="button">Karte</button>
      </SignInTransition>,
    )

    expect(onDone).toHaveBeenCalledTimes(1)
    const background = screen.getByTestId('sign-in-background')
    expect(background).not.toHaveAttribute('inert')
    expect(background).not.toHaveAttribute('aria-hidden')
    expect(screen.getByText('Karte').closest('[inert]')).not.toBeNull()
  })
})
