import {
  AuthError,
  BrowserAuthErrorCodes,
  CacheLookupPolicy,
  ClientAuthErrorCodes,
  EventType,
  InteractionStatus,
  InteractionType,
  type AuthenticationResult,
  type EventMessage,
} from '@azure/msal-browser'
import { useMsal } from '@azure/msal-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { setAccessTokenProvider } from '../api/httpClient.ts'
import { registerLogin } from '../api/login.ts'
import type { User } from '../api/types.ts'
import { AuthContext, type AuthStatus } from './authContext.ts'
import { apiScope, AUTH_RESPONSE_AT_START, LOGIN_SCOPES, missingSettings } from './msalConfig.ts'

const CANCELLED = 'Die Anmeldung wurde abgebrochen.'
const FAILED = 'Die Anmeldung ist fehlgeschlagen. Bitte versuchen Sie es erneut.'

type AuthState = {
  status: AuthStatus
  user: User | null
  error: string | null
  returnTo: string | null
}

const SIGNED_OUT: AuthState = { status: 'signedOut', user: null, error: null, returnTo: null }

function errorMessage(error: unknown): string {
  const code = error instanceof AuthError ? error.errorCode : ''
  const text = error instanceof Error ? error.message : ''
  const cancelled =
    code === BrowserAuthErrorCodes.userCancelled || code === 'access_denied' || /AADSTS65004|cancel/i.test(text)
  return cancelled ? CANCELLED : FAILED
}

/**
 * MSAL's codes for a token request that did not get through to Microsoft: the browser is offline, or the request
 * (e.g. renewing the access token with the refresh token) failed on the way.
 */
const NETWORK_ERROR_CODES: ReadonlySet<string> = new Set([
  BrowserAuthErrorCodes.noNetworkConnectivity,
  BrowserAuthErrorCodes.postRequestFailed,
  BrowserAuthErrorCodes.getRequestFailed,
  ClientAuthErrorCodes.networkError,
])

/** Whether MSAL failed to get a token because the network failed, not because Microsoft refused it. */
function isNetworkFailure(error: unknown): error is AuthError {
  return error instanceof AuthError && NETWORK_ERROR_CODES.has(error.errorCode)
}

/** Only paths inside the app, so the state carried through Microsoft cannot send the user elsewhere. */
function appPath(value: unknown): string | null {
  return typeof value === 'string' && /^\/(?![/\\])/.test(value) && !value.startsWith('/login') ? value : null
}

type AuthProviderProps = {
  children: ReactNode
  /** Whether the app was opened with a response from Microsoft in the URL; read before MSAL removes it. */
  authResponseAtStart?: boolean
}

/**
 * The auth context of the app, built on MSAL (`MsalProvider` in main.tsx handles the redirect response).
 * Once an account is present it gets an API access token silently and registers the user with `PUT /login`.
 */
export function AuthProvider({ children, authResponseAtStart = AUTH_RESPONSE_AT_START }: AuthProviderProps) {
  const { instance, inProgress, accounts } = useMsal()
  const [state, setState] = useState<AuthState>({ ...SIGNED_OUT, status: 'loading' })
  // The account whose registration has started; stops StrictMode and re-renders from sending PUT /login twice.
  const attemptRef = useRef<string | null>(null)
  // Set when a sign-in redirect completed in this page load: its failures are shown, a stale session's are not.
  const redirectedRef = useRef(false)
  // Set while MSAL handles this app's pending sign-in redirect and it has brought no result or error yet.
  const redirectPendingRef = useRef(false)

  useEffect(() => {
    setAccessTokenProvider(async () => {
      const account = instance.getActiveAccount()
      if (!account) {
        throw new Error('No signed-in account')
      }
      try {
        const result = await instance.acquireTokenSilent({
          scopes: [apiScope()],
          account,
          // Cached access token or refresh token only, no hidden iframe.
          cacheLookupPolicy: CacheLookupPolicy.AccessTokenAndRefreshToken,
        })
        return result.accessToken
      } catch (error) {
        // As the `AccessTokenProvider` contract asks: a network failure rejects like `fetch`, so a broken event stream
        // reconnects (`isStreamBreak`) also when it is the token renewal that finds the network down.
        if (isNetworkFailure(error)) {
          throw new TypeError(`The access token request failed: ${error.errorCode}`, { cause: error })
        }
        throw error
      }
    })
    return () => setAccessTokenProvider(null)
  }, [instance])

  // MsalProvider swallows errors of the redirect response; they arrive here as events.
  useEffect(() => {
    const callbackId = instance.addEventCallback((message: EventMessage) => {
      if (message.interactionType !== InteractionType.Redirect) {
        return
      }
      if (message.eventType === EventType.HANDLE_REDIRECT_START) {
        redirectPendingRef.current = true
      } else if (message.eventType === EventType.ACQUIRE_TOKEN_SUCCESS) {
        redirectPendingRef.current = false
        const result = message.payload as AuthenticationResult
        instance.setActiveAccount(result.account)
        redirectedRef.current = true
        setState((current) => ({ ...current, returnTo: appPath(result.state) }))
      } else if (message.eventType === EventType.ACQUIRE_TOKEN_FAILURE) {
        redirectPendingRef.current = false
        setState({ ...SIGNED_OUT, error: errorMessage(message.error) })
      } else if (message.eventType === EventType.HANDLE_REDIRECT_END) {
        // No result and no error: the user came back from Microsoft without a response (browser Back). With a
        // response in the URL, MSAL only forwards it to the page the sign-in started on, which handles it.
        if (redirectPendingRef.current && !authResponseAtStart) {
          setState({ ...SIGNED_OUT, error: CANCELLED })
        }
        redirectPendingRef.current = false
      }
    })
    return () => {
      if (callbackId) {
        instance.removeEventCallback(callbackId)
      }
    }
  }, [instance, authResponseAtStart])

  useEffect(() => {
    const account = instance.getActiveAccount() ?? accounts[0]
    if (inProgress !== InteractionStatus.None || !account || attemptRef.current === account.homeAccountId) {
      return
    }
    const key = account.homeAccountId
    attemptRef.current = key
    const afterRedirect = redirectedRef.current
    instance.setActiveAccount(account)
    registerLogin().then(
      (user) => {
        if (attemptRef.current === key) {
          setState((current) => ({ status: 'signedIn', user, error: null, returnTo: current.returnTo }))
        }
      },
      (error: unknown) => {
        if (attemptRef.current !== key) {
          return
        }
        // No retry and no interactive fallback: drop the account so the next sign-in starts clean.
        void instance.clearCache({ account })
        setState({ ...SIGNED_OUT, error: afterRedirect ? errorMessage(error) : null })
      },
    )
  }, [instance, inProgress, accounts])

  const signIn = useCallback(
    (from?: string) => {
      const missing = missingSettings()
      if (missing.length > 0) {
        // Do not leave the app: MSAL would send the user to Microsoft with an empty client ID, or the API token
        // after the sign-in could not be requested.
        console.error(
          `Microsoft Entra sign-in is not configured: ${missing.join(', ')} missing (set ENTRA_AUDIENCE and ENTRA_SCOPE for the backend).`,
        )
        setState({ ...SIGNED_OUT, error: FAILED })
        return
      }
      setState({ ...SIGNED_OUT, status: 'signingIn' })
      instance.loginRedirect({ scopes: [...LOGIN_SCOPES], state: from }).catch((error: unknown) => {
        setState({ ...SIGNED_OUT, error: errorMessage(error) })
      })
    },
    [instance],
  )

  // Local sign-out only: no Microsoft sign-out page.
  const signOut = useCallback(() => {
    attemptRef.current = null
    redirectedRef.current = false
    void instance.clearCache()
    setState(SIGNED_OUT)
  }, [instance])

  // Without an account the start ends signed out; with one it stays `loading` until the registration settles.
  const status =
    state.status === 'loading' && inProgress === InteractionStatus.None && accounts.length === 0
      ? 'signedOut'
      : state.status

  const value = useMemo(() => ({ ...state, status, signIn, signOut }), [state, status, signIn, signOut])
  return <AuthContext value={value}>{children}</AuthContext>
}
