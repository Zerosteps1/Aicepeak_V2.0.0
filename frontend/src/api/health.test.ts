import { describe, expect, it, vi } from 'vitest'
import { getHealthStatus } from './health.ts'

function stubFetch(implementation: () => Promise<Response>) {
  const fetchMock = vi.fn<typeof fetch>(implementation)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('getHealthStatus', () => {
  it('requests the health endpoint of the API without caching', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })))

    await getHealthStatus()

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/health/alive',
      expect.objectContaining({ cache: 'no-store' }),
    )
  })

  it('returns 204 when the backend is healthy', async () => {
    stubFetch(() => Promise.resolve(new Response(null, { status: 204 })))

    await expect(getHealthStatus()).resolves.toBe(204)
  })

  it('returns 503 instead of throwing when the backend is unhealthy', async () => {
    stubFetch(() => Promise.resolve(new Response('{"detail":"Failing components: database."}', { status: 503 })))

    await expect(getHealthStatus()).resolves.toBe(503)
  })

  it('rejects when the backend cannot be reached', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))

    await expect(getHealthStatus()).rejects.toThrow(TypeError)
  })

  it('forwards the abort signal', async () => {
    const fetchMock = stubFetch(() => Promise.resolve(new Response(null, { status: 204 })))
    const controller = new AbortController()

    await getHealthStatus(controller.signal)

    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal)
  })
})
