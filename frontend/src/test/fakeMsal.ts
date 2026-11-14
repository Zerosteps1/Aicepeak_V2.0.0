import {
  EventType,
  InteractionType,
  Logger,
  type AccountInfo,
  type AuthenticationResult,
  type EventCallbackFunction,
  type EventError,
  type EventMessage,
  type EventPayload,
  type IPublicClientApplication,
  type RedirectRequest,
  type SilentRequest,
} from '@azure/msal-browser'
import { vi } from 'vitest'

export const ACCOUNT: AccountInfo = {
  homeAccountId: '7b4a5e1c-0000-4000-8000-000000000001.db760528-cb7c-455c-bd41-e50a38f6fd62',
  environment: 'login.microsoftonline.com',
  tenantId: 'db760528-cb7c-455c-bd41-e50a38f6fd62',
  localAccountId: '7b4a5e1c-0000-4000-8000-000000000001',
  username: 'erika.mustermann@example.com',
  name: 'Erika Mustermann',
}

/**
 * What MSAL finds when the app starts: no sign-in redirect of this app, a sign-in result, an error from Microsoft, or
 * `noResult`: a sign-in redirect is pending but brings no result (the user came back with the browser's Back button,
 * or MSAL forwards the response to the page the sign-in started on).
 */
export type RedirectOutcome = { state?: string } | { error: Error } | 'noResult' | null

type FakeMsalOptions = {
  /** Accounts already in the MSAL cache at start. */
  accounts?: AccountInfo[]
  redirect?: RedirectOutcome
}

/**
 * A stand-in for PublicClientApplication with what MsalProvider and AuthProvider use. It emits the same events as
 * msal-browser v5: handleRedirectPromise when returning from Microsoft, loginRedirect and acquireTokenSilent around
 * their outcome. `mocks.loginRedirect` and `mocks.acquireTokenSilent` decide that outcome; tests may replace them.
 */
export function createFakeMsal({ accounts = [], redirect = null }: FakeMsalOptions = {}) {
  let cached = [...accounts]
  let active: AccountInfo | null = null
  let nextCallbackId = 0
  const callbacks = new Map<string, EventCallbackFunction>()
  let redirectResponse: Promise<AuthenticationResult | null> | undefined

  function emit(eventType: EventType, interactionType: InteractionType, payload: EventPayload = null, error: EventError = null) {
    const message: EventMessage = {
      eventType,
      interactionType,
      payload,
      error,
      correlationId: 'test',
      timestamp: Date.now(),
    }
    callbacks.forEach((callback) => callback(message))
  }

  // As StandardController.handleRedirectPromise: no events unless this app's sign-in redirect is pending.
  async function handleRedirect(): Promise<AuthenticationResult | null> {
    if (!redirect) {
      return null
    }
    emit(EventType.HANDLE_REDIRECT_START, InteractionType.Redirect)
    await Promise.resolve()
    if (redirect === 'noResult') {
      emit(EventType.HANDLE_REDIRECT_END, InteractionType.Redirect)
      return null
    }
    if ('error' in redirect) {
      emit(EventType.ACQUIRE_TOKEN_FAILURE, InteractionType.Redirect, null, redirect.error)
      emit(EventType.HANDLE_REDIRECT_END, InteractionType.Redirect)
      throw redirect.error
    }
    const result = { account: ACCOUNT, state: redirect.state ?? '' } as AuthenticationResult
    cached = [ACCOUNT]
    emit(EventType.ACQUIRE_TOKEN_SUCCESS, InteractionType.Redirect, result)
    emit(EventType.LOGIN_SUCCESS, InteractionType.Redirect, ACCOUNT)
    emit(EventType.HANDLE_REDIRECT_END, InteractionType.Redirect)
    return result
  }

  const mocks = {
    initializeWrapperLibrary: vi.fn<IPublicClientApplication['initializeWrapperLibrary']>(),
    getLogger: vi.fn<IPublicClientApplication['getLogger']>(() => new Logger({})),
    initialize: vi.fn<IPublicClientApplication['initialize']>(async () => {}),
    addEventCallback: vi.fn<IPublicClientApplication['addEventCallback']>((callback) => {
      const id = `callback-${++nextCallbackId}`
      callbacks.set(id, callback)
      return id
    }),
    removeEventCallback: vi.fn<IPublicClientApplication['removeEventCallback']>((id) => {
      callbacks.delete(id)
    }),
    handleRedirectPromise: vi.fn<IPublicClientApplication['handleRedirectPromise']>(
      () => (redirectResponse ??= handleRedirect()),
    ),
    getAllAccounts: vi.fn<IPublicClientApplication['getAllAccounts']>(() => cached),
    getActiveAccount: vi.fn<IPublicClientApplication['getActiveAccount']>(() => active),
    setActiveAccount: vi.fn<IPublicClientApplication['setActiveAccount']>((account) => {
      active = account
    }),
    /** Resolves when the browser would leave for Microsoft; rejects when the redirect cannot start. */
    loginRedirect: vi.fn<IPublicClientApplication['loginRedirect']>(async () => {}),
    acquireTokenSilent: vi.fn<IPublicClientApplication['acquireTokenSilent']>(
      async (request) => ({ accessToken: 'test-access-token', account: request.account }) as AuthenticationResult,
    ),
    clearCache: vi.fn<IPublicClientApplication['clearCache']>(async () => {
      cached = []
      active = null
    }),
  }

  const instance = {
    ...mocks,
    // As StandardController.acquireTokenRedirect: ACQUIRE_TOKEN_START, and ACQUIRE_TOKEN_FAILURE if it rejects.
    loginRedirect: async (request?: RedirectRequest) => {
      emit(EventType.ACQUIRE_TOKEN_START, InteractionType.Redirect, request ?? null)
      try {
        await mocks.loginRedirect(request)
      } catch (error) {
        emit(EventType.ACQUIRE_TOKEN_FAILURE, InteractionType.Redirect, null, error as EventError)
        throw error
      }
    },
    // As StandardController.acquireTokenSilentAsync: ACQUIRE_TOKEN_START, then ACQUIRE_TOKEN_SUCCESS or _FAILURE.
    acquireTokenSilent: async (request: SilentRequest) => {
      emit(EventType.ACQUIRE_TOKEN_START, InteractionType.Silent, request)
      try {
        const result = await mocks.acquireTokenSilent(request)
        emit(EventType.ACQUIRE_TOKEN_SUCCESS, InteractionType.Silent, result)
        return result
      } catch (error) {
        emit(EventType.ACQUIRE_TOKEN_FAILURE, InteractionType.Silent, null, error as EventError)
        throw error
      }
    },
  }

  return { instance: instance as unknown as IPublicClientApplication, mocks, callbackCount: () => callbacks.size }
}
