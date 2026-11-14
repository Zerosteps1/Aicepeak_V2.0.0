import { AuthError, CacheLookupPolicy, InteractionRequiredAuthError, ServerError } from '@azure/msal-browser'
import { MsalProvider } from '@azure/msal-react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { StrictMode } from 'react'
import { MemoryRouter, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from './App.tsx'
import { AuthProvider } from './auth/AuthProvider.tsx'
import { useAuth } from './auth/useAuth.ts'
import { deferred } from './test/deferred.ts'
import { ACCOUNT, createFakeMsal, type RedirectOutcome } from './test/fakeMsal.ts'
import { ThemeProvider } from './theme/ThemeProvider.tsx'

const API_SCOPE = 'api://api-client-id/access_as_user'
const USER = {
  tid: 'db760528-cb7c-455c-bd41-e50a38f6fd62',
  oid: '7b4a5e1c-0000-4000-8000-000000000001',
  name: 'Erika Mustermann',
}
const FAILED = 'Die Anmeldung ist fehlgeschlagen. Bitte versuchen Sie es erneut.'
const CANCELLED = 'Die Anmeldung wurde abgebrochen.'

function stubLoginApi(respond: () => Response | Promise<Response> = () => Response.json(USER)) {
  const fetchMock = vi.fn<typeof fetch>(async () => respond())
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function Probe() {
  const { pathname } = useLocation()
  const { user } = useAuth()
  return (
    <>
      <p data-testid="location">{pathname}</p>
      <p data-testid="user">{user?.name ?? 'none'}</p>
    </>
  )
}

function renderApp(path: string, msal: ReturnType<typeof createFakeMsal>, authResponseAtStart = false) {
  render(
    <StrictMode>
      <MsalProvider instance={msal.instance}>
        <MemoryRouter initialEntries={[path]}>
          <ThemeProvider>
            <AuthProvider authResponseAtStart={authResponseAtStart}>
              <App />
              <Probe />
            </AuthProvider>
          </ThemeProvider>
        </MemoryRouter>
      </MsalProvider>
    </StrictMode>,
  )
}

/** Renders the app as it starts after Microsoft redirected back to /login. */
function renderRedirectReturn(redirect: RedirectOutcome) {
  const msal = createFakeMsal({ redirect })
  renderApp('/login', msal)
  return msal
}

const currentPath = () => screen.getByTestId('location').textContent
const signInButton = () => screen.findByRole('button', { name: 'Mit Microsoft anmelden' })

beforeEach(() => {
  vi.stubEnv('VITE_ENTRA_CLIENT_ID', 'spa-client-id')
  vi.stubEnv('VITE_ENTRA_API_SCOPE', API_SCOPE)
})

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('App', () => {
  it.each(['/', '/some/route?tab=2'])('AC-1: sends an unauthenticated user from %s to /login with the sign-in card', async (path) => {
    const fetchMock = stubLoginApi()

    renderApp(path, createFakeMsal())

    expect(await screen.findByRole('dialog', { name: 'Anmelden.' })).toBeInTheDocument()
    expect(currentPath()).toBe('/login')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('AC-1: a stale session at start (no API token any more) ends on /login without an error', async () => {
    const fetchMock = stubLoginApi()
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    msal.mocks.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('interaction_required', 'test'))

    renderApp('/', msal)

    expect(await signInButton()).toBeInTheDocument()
    expect(currentPath()).toBe('/login')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(msal.mocks.clearCache).toHaveBeenCalledWith({ account: ACCOUNT })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('after signing in, returns the user to the route they first opened', async () => {
    stubLoginApi()

    renderRedirectReturn({ state: '/some/route?tab=2' })

    expect(await screen.findByRole('heading', { name: 'Ihr Konto.' })).toBeInTheDocument()
    expect(currentPath()).toBe('/some/route')
  })

  it('AC-2: clicking "Mit Microsoft anmelden" starts the Microsoft Entra redirect sign-in', async () => {
    const msal = createFakeMsal()
    renderApp('/some/route', msal)

    fireEvent.click(await signInButton())

    expect(msal.mocks.loginRedirect).toHaveBeenCalledTimes(1)
    expect(currentPath()).toBe('/login')
  })

  it('AC-2: while signing in, the button shows "Anmeldung läuft …" with aria-busy and ignores clicks', async () => {
    const msal = createFakeMsal()
    renderApp('/', msal)

    fireEvent.click(await signInButton())
    const busyButton = screen.getByRole('button', { name: 'Anmeldung läuft …' })
    fireEvent.click(busyButton)

    expect(busyButton).toHaveAttribute('aria-busy', 'true')
    expect(msal.mocks.loginRedirect).toHaveBeenCalledTimes(1)
  })

  it('AC-2: while the sign-in completes after the redirect, the button shows "Anmeldung läuft …" and ignores clicks', async () => {
    const response = deferred<Response>()
    stubLoginApi(() => response.promise)

    const msal = renderRedirectReturn({})
    const busyButton = await screen.findByRole('button', { name: 'Anmeldung läuft …' })
    fireEvent.click(busyButton)

    expect(busyButton).toHaveAttribute('aria-busy', 'true')
    expect(msal.mocks.loginRedirect).not.toHaveBeenCalled()
    response.resolve(Response.json(USER))
    expect(await screen.findByRole('heading', { name: 'Ihr Konto.' })).toBeInTheDocument()
  })

  it('AC-20: requests only the openid and profile scopes at sign-in', async () => {
    const msal = createFakeMsal()
    renderApp('/some/route', msal)

    fireEvent.click(await signInButton())

    // Exactly these two; MSAL appends offline_access itself.
    expect(msal.mocks.loginRedirect).toHaveBeenCalledWith({ scopes: ['openid', 'profile'], state: '/some/route' })
  })

  it('AC-5: after signing in, shows the protected screen with the user record from PUT /api/v1/login as formatted JSON', async () => {
    const fetchMock = stubLoginApi()

    const msal = renderRedirectReturn({})

    const record = await screen.findByRole('region', { name: 'Benutzerdatensatz' })
    expect(record.querySelector('pre')?.textContent).toBe(JSON.stringify(USER, null, 2))
    expect(currentPath()).toBe('/')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/login')
    expect(init?.method).toBe('PUT')
    expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer test-access-token')
    expect(msal.mocks.acquireTokenSilent).toHaveBeenCalledWith({
      scopes: [API_SCOPE],
      account: ACCOUNT,
      cacheLookupPolicy: CacheLookupPolicy.AccessTokenAndRefreshToken,
    })
  })

  it('AC-5: a user with a valid session who opens / sees their record without signing in again', async () => {
    const fetchMock = stubLoginApi()
    const msal = createFakeMsal({ accounts: [ACCOUNT] })

    renderApp('/', msal)

    const record = await screen.findByRole('region', { name: 'Benutzerdatensatz' })
    expect(record.querySelector('pre')?.textContent).toBe(JSON.stringify(USER, null, 2))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(msal.mocks.loginRedirect).not.toHaveBeenCalled()
  })

  it('AC-8: when Microsoft Entra returns an error, stays on /login and shows that the sign-in failed', async () => {
    const fetchMock = stubLoginApi()

    renderRedirectReturn({ error: new ServerError('invalid_request', 'test', 'AADSTS50011: The redirect URI does not match.') })

    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED)
    expect(currentPath()).toBe('/login')
    expect(await signInButton()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it.each([
    ['user_cancelled', new AuthError('user_cancelled', 'test', 'User cancelled the flow.')],
    ['access_denied', new ServerError('access_denied', 'test', 'The user has denied access to the scope requested.')],
    ['AADSTS65004', new ServerError('invalid_request', 'test', 'AADSTS65004: User declined to consent to access the app.')],
  ])('AC-8: when the user cancels at Microsoft (%s), stays on /login and shows that the sign-in was cancelled', async (_, error) => {
    stubLoginApi()

    renderRedirectReturn({ error })

    expect(await screen.findByRole('alert')).toHaveTextContent(CANCELLED)
    expect(currentPath()).toBe('/login')
  })

  it('AC-8: when the user comes back from Microsoft without signing in (browser Back), stays on /login and shows that the sign-in was cancelled', async () => {
    const fetchMock = stubLoginApi()

    renderRedirectReturn('noResult')

    expect(await screen.findByRole('alert')).toHaveTextContent(CANCELLED)
    expect(currentPath()).toBe('/login')
    expect(await signInButton()).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('shows no error while MSAL forwards the response from Microsoft to the page the sign-in started on', async () => {
    const msal = createFakeMsal({ redirect: 'noResult' })

    renderApp('/login', msal, true)

    await waitFor(() => expect(msal.mocks.handleRedirectPromise).toHaveBeenCalled())
    expect(await signInButton()).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each(['VITE_ENTRA_CLIENT_ID', 'VITE_ENTRA_API_SCOPE'])(
    'AC-8: when %s is not set, stays in the app on /login and shows that the sign-in failed',
    async (name) => {
      vi.stubEnv(name, '')
      const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
      const msal = createFakeMsal()
      renderApp('/', msal)

      fireEvent.click(await signInButton())

      expect(await screen.findByRole('alert')).toHaveTextContent(FAILED)
      expect(msal.mocks.loginRedirect).not.toHaveBeenCalled()
      expect(currentPath()).toBe('/login')
      expect(consoleError).toHaveBeenCalledWith(expect.stringContaining(name))
    },
  )

  it('AC-8: when the sign-in redirect cannot start, stays on /login and shows that the sign-in failed', async () => {
    const msal = createFakeMsal()
    msal.mocks.loginRedirect.mockRejectedValue(new AuthError('endpoints_resolution_error', 'test', 'Endpoints cannot be resolved.'))
    renderApp('/', msal)

    fireEvent.click(await signInButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED)
    expect(await signInButton()).toBeInTheDocument()
    expect(currentPath()).toBe('/login')
  })

  it('AC-8: when the backend rejects the sign-in with 401, stays on /login, shows the error and drops the account', async () => {
    stubLoginApi(() => new Response('Unauthorized', { status: 401 }))

    const msal = renderRedirectReturn({})

    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED)
    expect(currentPath()).toBe('/login')
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(msal.mocks.clearCache).toHaveBeenCalledWith({ account: ACCOUNT })
  })

  it('AC-8: when no API access token can be obtained after signing in, stays on /login and shows the error', async () => {
    const fetchMock = stubLoginApi()
    const msal = createFakeMsal({ redirect: {} })
    msal.mocks.acquireTokenSilent.mockRejectedValue(new InteractionRequiredAuthError('consent_required', 'test'))

    renderApp('/login', msal)

    expect(await screen.findByRole('alert')).toHaveTextContent(FAILED)
    expect(currentPath()).toBe('/login')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('AC-12: the sign-in card shows the Aicepeak logo', async () => {
    renderApp('/login', createFakeMsal())

    const card = await screen.findByRole('dialog', { name: 'Anmelden.' })
    const logo = within(card).getByRole('img', { name: 'Aicepeak' })
    expect(logo).toHaveClass('pg-signin__logo')
    expect(logo).toHaveAttribute('src', expect.stringContaining('aicepeak-mark'))
  })

  it('AC-12: the sign-in card has the "Mit Microsoft anmelden" button, the only button that can be reached', async () => {
    renderApp('/login', createFakeMsal())

    const card = await screen.findByRole('dialog', { name: 'Anmelden.' })
    const button = within(card).getByRole('button', { name: 'Mit Microsoft anmelden' })
    expect(button).toHaveClass('pg-signin__btn')
    expect(button).toHaveAttribute('type', 'submit')
    expect(screen.getAllByRole('button')).toEqual([button])
  })

  it('AC-12: the skeleton of the next page is rendered behind the card, inert and hidden from assistive technology', async () => {
    renderApp('/login', createFakeMsal())

    const card = await screen.findByRole('dialog', { name: 'Anmelden.' })
    const background = screen.getByTestId('sign-in-background')
    expect(background).toHaveAttribute('inert')
    expect(background).toHaveAttribute('aria-hidden', 'true')
    expect(within(background).getByTestId('home-skeleton')).toBeInTheDocument()
    expect(within(background).getByRole('banner', { hidden: true })).toHaveClass('pg-glass')
    expect(background).not.toContainElement(card)
  })

  it('AC-15: "Abmelden" in the menu bar clears the session and goes to /login', async () => {
    stubLoginApi()
    const msal = createFakeMsal({ accounts: [ACCOUNT] })
    renderApp('/', msal)
    await screen.findByRole('region', { name: 'Benutzerdatensatz' })
    expect(screen.getByTestId('user')).toHaveTextContent(USER.name)

    fireEvent.click(screen.getByRole('button', { name: 'Abmelden' }))

    expect(msal.mocks.clearCache).toHaveBeenCalledTimes(1)
    expect(await signInButton()).toBeInTheDocument()
    await waitFor(() => expect(currentPath()).toBe('/login'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')
    expect(screen.queryByRole('region', { name: 'Benutzerdatensatz' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
