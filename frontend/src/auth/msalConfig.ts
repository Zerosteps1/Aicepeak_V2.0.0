import { BrowserCacheLocation, PublicClientApplication } from '@azure/msal-browser'

/**
 * Scopes requested at sign-in (AC-20). MSAL appends `offline_access` itself; that is accepted, as decided by the
 * maintainer. The API scope is requested separately, silently, after sign-in.
 */
export const LOGIN_SCOPES = ['openid', 'profile']

/** The API scope, e.g. `api://<api-client-id>/access_as_user`. */
export function apiScope(): string {
  return import.meta.env.VITE_ENTRA_API_SCOPE ?? ''
}

/** The `VITE_ENTRA_*` settings that are not set; without them sign-in cannot work. */
export function missingSettings(): string[] {
  const settings = {
    VITE_ENTRA_CLIENT_ID: import.meta.env.VITE_ENTRA_CLIENT_ID,
    VITE_ENTRA_API_SCOPE: import.meta.env.VITE_ENTRA_API_SCOPE,
  }
  return Object.entries(settings)
    .filter(([, value]) => !value)
    .map(([name]) => name)
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
      clientId: import.meta.env.VITE_ENTRA_CLIENT_ID ?? '',
      authority: 'https://login.microsoftonline.com/organizations',
      redirectUri: `${window.location.origin}/login`,
    },
    cache: {
      cacheLocation: BrowserCacheLocation.SessionStorage,
    },
  })
}
