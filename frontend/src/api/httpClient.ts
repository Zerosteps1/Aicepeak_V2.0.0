const API_BASE_PATH = '/api/v1'

/**
 * Single entry point for backend calls. Paths are relative to the API version root, e.g. `/health/alive`.
 * Microsoft Entra ID (later): acquire the access token with MSAL here and set `Authorization: Bearer <token>`.
 */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE_PATH}${path}`, init)
}
