import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from './authContext.ts'
import { RequireAuth } from './RequireAuth.tsx'

describe('RequireAuth', () => {
  it('does not send a user with a session being restored to /login', () => {
    const auth: AuthContextValue = {
      status: 'loading',
      user: null,
      error: null,
      returnTo: null,
      signIn: vi.fn<AuthContextValue['signIn']>(),
      signOut: vi.fn<AuthContextValue['signOut']>(),
    }

    render(
      <AuthContext value={auth}>
        <MemoryRouter initialEntries={['/some/route']}>
          <Routes>
            <Route path="/login" element={<p>Anmeldeseite</p>} />
            <Route
              path="*"
              element={
                <RequireAuth>
                  <p>Geschützte Seite</p>
                </RequireAuth>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthContext>,
    )

    expect(screen.queryByText('Anmeldeseite')).not.toBeInTheDocument()
    expect(screen.queryByText('Geschützte Seite')).not.toBeInTheDocument()
  })
})
