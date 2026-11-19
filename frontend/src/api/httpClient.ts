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

/** The content type of the JSON bodies the API takes. */
export const JSON_HEADERS: Readonly<Record<string, string>> = { 'Content-Type': 'application/json' }

/**
 * A backend call that answered with an error status. For a 400 ValidationProblem, `errors` holds every failure the
 * backend listed, as short reasons per field (e.g. `documents[2].size`); otherwise it is empty.
 */
export class ApiError extends Error {
  readonly status: number
  readonly errors: Readonly<Record<string, readonly string[]>>

  constructor(request: string, status: number, errors: Readonly<Record<string, readonly string[]>> = {}) {
    super(`${request} failed with HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.errors = errors
  }
}

/** Reads the field errors of a ValidationProblem body; anything else gives none. */
async function problemErrors(response: Response): Promise<Record<string, string[]>> {
  if (!/json/i.test(response.headers.get('Content-Type') ?? '')) {
    return {}
  }
  try {
    const body: unknown = await response.json()
    const errors = typeof body === 'object' && body !== null ? (body as { errors?: unknown }).errors : undefined
    if (typeof errors !== 'object' || errors === null) {
      return {}
    }
    const result: Record<string, string[]> = {}
    for (const [field, reasons] of Object.entries(errors)) {
      result[field] = (Array.isArray(reasons) ? reasons : [reasons]).filter((reason) => typeof reason === 'string')
    }
    return result
  } catch {
    return {}
  }
}

/** Throws an `ApiError` for `request` (e.g. `PATCH /project/{id}`) unless the response has a success status. */
export async function ensureOk(response: Response, request: string): Promise<Response> {
  if (!response.ok) {
    throw new ApiError(request, response.status, await problemErrors(response))
  }
  return response
}
