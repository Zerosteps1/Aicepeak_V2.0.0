import { InteractionRequiredAuthError } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { apiFetch } from '../api/httpClient.ts'
import { ACCOUNT, createFakeMsal } from '../test/fakeMsal.ts'
import { AuthProvider } from './AuthProvider.tsx'
import { useAuth } from './useAuth.ts'

const USER = { tid: ACCOUNT.tenantId, oid: ACCOUNT.localAccountId, name: 'Erika Mustermann' }

function NestedConsumer() {
  const { status, user, signOut } = useAuth()
  return (
    <button type="button" onClick={signOut}>
      {status}: {user ? user.name : 'no user'}
    </button>
  )
}

function renderWithAuth(msal: ReturnType<typeof createFakeMsal>) {
  return render(
    <MsalProvider instance={msal.instance}>
      <AuthProvider>
        <main>
          <section>
            <NestedConsumer />
          </section>
        </main>
      </AuthProvider>
    </MsalProvider>,
  )
}

beforeEach(() => {
  vi.stubEnv('VITE_ENTRA_API_SCOPE', 'api://api-client-id/access_as_user')
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => Response.json(USER)))
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('AuthProvider', () => {
  it('AC-14: a nested component reads the current user from useAuth', async () => {
    renderWithAuth(createFakeMsal({ accounts: [ACCOUNT] }))

    expect(await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })).toBeInTheDocument()
  })

  it('AC-14: a nested component sees no user when nobody is signed in', async () => {
    renderWithAuth(createFakeMsal())

    expect(await screen.findByRole('button', { name: 'signedOut: no user' })).toBeInTheDocument()
  })

  it('AC-14: signing out through useAuth clears the user for all components', async () => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderWithAuth(msal)

    fireEvent.click(await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' }))

    expect(screen.getByRole('button', { name: 'signedOut: no user' })).toBeInTheDocument()
    expect(msal.mocks.clearCache).toHaveBeenCalledWith()
  })

  it('keeps the user signed in when a later silent token request fails', async () => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })
    msal.mocks.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required', 'test'))

    await act(() => expect(apiFetch('/login')).rejects.toThrow(InteractionRequiredAuthError))

    expect(screen.getByRole('button', { name: 'signedIn: Erika Mustermann' })).toBeInTheDocument()
  })

  it('removes its MSAL event callback when unmounted', async () => {
    const msal = createFakeMsal()
    const view = renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedOut: no user' })

    view.unmount()

    expect(msal.callbackCount()).toBe(0)
  })

  it('unregisters its access token provider when unmounted', async () => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    const view = renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })

    view.unmount()
    await apiFetch('/login')

    expect(vi.mocked(fetch)).toHaveBeenLastCalledWith('/api/v1/login', {})
    expect(msal.mocks.acquireTokenSilent).toHaveBeenCalledTimes(1)
  })
})
