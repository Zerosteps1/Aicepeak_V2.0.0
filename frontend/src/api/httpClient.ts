const API_BASE_PATH = '/api/v1'

/** Returns the Microsoft Entra access token for the API. */
export type AccessTokenProvider = () => Promise<string>

let accessTokenProvider: AccessTokenProvider | null = null

/** Registers how requests get their access token; `null` sends requests without one. */
export function setAccessTokenProvider(provider: AccessTokenProvider | null): void {
  accessTokenProvider = provider
}

/**
 * Single entry point for backend calls. Paths are relative to the API version root, e.g. `/login`.
 * Sets `Authorization: Bearer <token>` when an access token provider is registered.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const provider = accessTokenProvider
  if (!provider) {
    return fetch(`${API_BASE_PATH}${path}`, init)
  }
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${await provider()}`)
  return fetch(`${API_BASE_PATH}${path}`, { ...init, headers })
}
