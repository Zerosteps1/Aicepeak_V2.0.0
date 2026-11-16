import { BrowserCacheLocation, PublicClientApplication } from '@azure/msal-browser'

/**
 * Scopes requested at sign-in (AC-20). MSAL appends `offline_access` itself; that is accepted, as decided by the
 * maintainer. The API scope is requested separately, silently, after sign-in.
 */
export const LOGIN_SCOPES = ['openid', 'profile']

/**
 * The Entra config of this environment. The backend fills it into index.html once at startup from its `ENTRA_*`
 * settings (in development the Vite dev server does, from backend/.env), so one build runs everywhere.
 */
export function appConfig(): AppConfig | null {
  return window.__AICEPEAK_CONFIG__ ?? null
}

/** The API scope, e.g. `api://<client-id>/access_as_user`. */
export function apiScope(): string {
  return appConfig()?.apiScope ?? ''
}

/** The config values that are missing; without them sign-in cannot work. */
export function missingSettings(): string[] {
  const config = appConfig()
  return (['clientId', 'apiScope'] as const).filter((name) => !config?.[name])
}

/** Whether a URL fragment holds a response from Microsoft (`#code=…` or `#error=…`). */
export function hasAuthResponse(hash: string): boolean {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  return params.has('code') || params.has('error')
}

/**
 * Whether the app was opened with a response from Microsoft in the URL. Read when this module loads, before MSAL
 * handles the redirect and removes the response from the URL.
 */
export const AUTH_RESPONSE_AT_START = hasAuthResponse(window.location.hash)

export function createMsalInstance(): PublicClientApplication {
  return new PublicClientApplication({
    auth: {
      clientId: appConfig()?.clientId ?? '',
      authority: 'https://login.microsoftonline.com/organizations',
      redirectUri: `${window.location.origin}/login`,
    },
    cache: {
      cacheLocation: BrowserCacheLocation.SessionStorage,
    },
  })
}
