import { fireEvent, render, screen, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue, type AuthStatus } from '../../auth/authContext.ts'
import { LoginPage } from './LoginPage.tsx'

function renderLogin(status: AuthStatus, background: ReactNode = <p>Nächste Seite</p>, overrides: Partial<AuthContextValue> = {}) {
  const auth: AuthContextValue = {
    status,
    user: null,
    error: null,
    returnTo: null,
    signIn: vi.fn<AuthContextValue['signIn']>(),
    signOut: vi.fn<AuthContextValue['signOut']>(),
    ...overrides,
  }
  render(
    <AuthContext value={auth}>
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage background={background} />} />
          <Route path="*" element={<p>Ziel</p>} />
        </Routes>
      </MemoryRouter>
    </AuthContext>,
  )
  return auth
}

describe('LoginPage', () => {
  it('AC-22: renders the background it is given inside the background layer', () => {
    renderLogin('signedOut', <p>Nächste Seite</p>)

    const layer = screen.getByTestId('sign-in-background')
    expect(within(layer).getByText('Nächste Seite')).toBeInTheDocument()
    expect(layer).not.toContainElement(screen.getByRole('dialog', { name: 'Anmelden.' }))
  })

  it('AC-2: submitting the card while signed out calls signIn', () => {
    const auth = renderLogin('signedOut')

    fireEvent.click(screen.getByRole('button', { name: 'Mit Microsoft anmelden' }))

    expect(auth.signIn).toHaveBeenCalledTimes(1)
  })

  it.each(['loading', 'signingIn'] as const)(
    'AC-2: while %s, the button shows "Anmeldung läuft …" with aria-busy and ignores submits',
    (status) => {
      const auth = renderLogin(status)

      const button = screen.getByRole('button', { name: 'Anmeldung läuft …' })
      fireEvent.click(button)

      expect(button).toHaveAttribute('aria-busy', 'true')
      expect(auth.signIn).not.toHaveBeenCalled()
    },
  )

  it('AC-8: shows the error under the sign-in button in an alert, before the note', () => {
    renderLogin('signedOut', null, { error: 'Die Anmeldung wurde abgebrochen.' })

    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Die Anmeldung wurde abgebrochen.')
    expect(alert.previousElementSibling).toBe(screen.getByRole('button', { name: 'Mit Microsoft anmelden' }))
    expect(alert.nextElementSibling).toHaveTextContent('Kein Zugang? Ihre IT-Administration schaltet Sie in Microsoft Entra ID frei.')
  })

  it('once signed in, goes to the path the user wanted', async () => {
    renderLogin('signedIn', null, { returnTo: '/some/route' })

    expect(await screen.findByText('Ziel')).toBeInTheDocument()
  })
})
