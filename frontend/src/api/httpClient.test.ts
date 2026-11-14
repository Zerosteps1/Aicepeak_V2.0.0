import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, setAccessTokenProvider } from './httpClient.ts'

function stubFetch() {
  const fetchMock = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  setAccessTokenProvider(null)
})

describe('apiFetch', () => {
  it('AC-5: sets Authorization: Bearer with the token of the registered provider', async () => {
    const fetchMock = stubFetch()
    setAccessTokenProvider(async () => 'token-123')

    await apiFetch('/login', { method: 'PUT', headers: { Accept: 'application/json' } })

    const [url, init] = fetchMock.mock.calls[0] ?? []
    expect(url).toBe('/api/v1/login')
    expect(init?.method).toBe('PUT')
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer token-123')
    expect(headers.get('Accept')).toBe('application/json')
  })

  it('sends no Authorization header when no provider is registered', async () => {
    const fetchMock = stubFetch()

    await apiFetch('/login')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/login', {})
  })

  it('AC-8: rejects without calling the backend when no token can be obtained', async () => {
    const fetchMock = stubFetch()
    setAccessTokenProvider(() => Promise.reject(new Error('no token')))

    await expect(apiFetch('/login')).rejects.toThrow('no token')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
