import {
  BrowserAuthError,
  BrowserAuthErrorCodes,
  ClientAuthError,
  ClientAuthErrorCodes,
  InteractionRequiredAuthError,
} from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { isStreamBreak, readValidationRun, validationStreamPath } from '../api/documentStreams.ts'
import { apiFetch } from '../api/httpClient.ts'
import { stubApi } from '../test/fakeApi.ts'
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
  window.__AICEPEAK_CONFIG__ = { clientId: 'api-client-id', apiScope: 'api://api-client-id/access_as_user' }
  vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => Response.json(USER)))
})

afterEach(() => {
  delete window.__AICEPEAK_CONFIG__
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

  // How MSAL v5 reports a token renewal that does not get through: FetchClient turns the failed fetch into one of
  // these codes, and sendPostRequest rethrows it as a BrowserAuthError.
  it.each([
    ['offline', new BrowserAuthError(BrowserAuthErrorCodes.noNetworkConnectivity, 'test')],
    ['the token request failed', new BrowserAuthError(BrowserAuthErrorCodes.postRequestFailed, 'test')],
    ['the authority metadata request failed', new BrowserAuthError(BrowserAuthErrorCodes.getRequestFailed, 'test')],
    ['the network module failed', new ClientAuthError(ClientAuthErrorCodes.networkError, 'test')],
  ])('reports a token request that hits a network failure (%s) as a network error, like fetch', async (_case, cause) => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })
    msal.mocks.acquireTokenSilent.mockRejectedValue(cause)

    const error = await act(() => apiFetch('/login').then(() => null, (failure: unknown) => failure))

    expect(error).toBeInstanceOf(TypeError)
    expect(error).toMatchObject({ cause })
    expect(isStreamBreak(error)).toBe(true)
    expect(screen.getByRole('button', { name: 'signedIn: Erika Mustermann' })).toBeInTheDocument()
  })

  it('does not reconnect a run whose token Microsoft refused: the error is passed on unchanged', async () => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })
    const api = stubApi()
    api.streams(validationStreamPath('p1'))
    const refused = new InteractionRequiredAuthError('interaction_required', 'test')
    msal.mocks.acquireTokenSilent.mockRejectedValue(refused)
    const waits: number[] = []

    const error = await act(() =>
      readValidationRun('p1', () => {}, {
        sleep: async (ms) => {
          waits.push(ms)
        },
      }).then(() => null, (failure: unknown) => failure),
    )

    expect(error).toBe(refused)
    expect(waits).toEqual([])
    expect(api.sent('GET', validationStreamPath('p1'))).toHaveLength(0)
  })

  it('reconnects a run whose token renewal hit the network failure, with the token once it is back', async () => {
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderWithAuth(msal)
    await screen.findByRole('button', { name: 'signedIn: Erika Mustermann' })
    const api = stubApi()
    const streams = api.streams(validationStreamPath('p1'))
    msal.mocks.acquireTokenSilent.mockRejectedValueOnce(new BrowserAuthError(BrowserAuthErrorCodes.postRequestFailed, 'test'))
    const waits: number[] = []
    const events: unknown[] = []

    const reading = readValidationRun('p1', (event) => events.push(event), {
      sleep: async (ms) => {
        waits.push(ms)
      },
    })
    await act(() => vi.waitFor(() => expect(streams).toHaveLength(1)))
    streams[0]?.push({ overallProgress: 100, document: '' })
    streams[0]?.end()
    await act(() => reading)

    expect(waits).toEqual([1000])
    expect(events).toEqual([{ overallProgress: 100, document: '' }])
    expect(msal.mocks.acquireTokenSilent).toHaveBeenCalledTimes(3)
    expect(api.sent('GET', validationStreamPath('p1')).map((request) => request.headers.get('Authorization'))).toEqual([
      'Bearer test-access-token',
    ])
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
