import { render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../../auth/authContext.ts'
import { LoginPage } from './LoginPage.tsx'
import type { SignInTransition } from './SignInTransition.tsx'

// Replacing the transition module must take the whole layering (and later the animation) with it.
vi.mock('./SignInTransition.tsx', () => ({
  SignInTransition: ({ phase, background, children }: ComponentProps<typeof SignInTransition>) => (
    <div data-testid="replacement" data-phase={phase}>
      <div data-testid="replacement-background">{background}</div>
      <div data-testid="replacement-card">{children}</div>
    </div>
  ),
}))

describe('LoginPage with a replaced SignInTransition', () => {
  it('AC-23: renders its card and background only through the SignInTransition module', () => {
    const { container } = render(
      <AuthContext value={{ status: 'signedOut', user: null, error: null, returnTo: null, signIn: vi.fn<AuthContextValue['signIn']>(), signOut: vi.fn<AuthContextValue['signOut']>() }}>
        <MemoryRouter>
          <LoginPage background={<p>Nächste Seite</p>} />
        </MemoryRouter>
      </AuthContext>,
    )

    const replacement = screen.getByTestId('replacement')
    expect(container.children).toHaveLength(1)
    expect(container.firstElementChild).toBe(replacement)
    expect(replacement).toHaveAttribute('data-phase', 'out')
    expect(within(screen.getByTestId('replacement-card')).getByRole('dialog', { name: 'Anmelden.' })).toBeInTheDocument()
    expect(within(screen.getByTestId('replacement-background')).getByText('Nächste Seite')).toBeInTheDocument()
    expect(screen.queryByTestId('sign-in-background')).not.toBeInTheDocument()
  })
})
