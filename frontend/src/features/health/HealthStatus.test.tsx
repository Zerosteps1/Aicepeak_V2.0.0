import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { deferred } from '../../test/deferred.ts'
import { HealthStatus } from './HealthStatus.tsx'

function stubFetch(implementation: () => Promise<Response>) {
  const fetchMock = vi.fn<typeof fetch>(implementation)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('HealthStatus', () => {
  it('shows that it is checking, then the HTTP status 204', async () => {
    const response = deferred<Response>()
    stubFetch(() => response.promise)

    render(<HealthStatus />)

    expect(screen.getByRole('status')).toHaveTextContent('Backend health: checking…')
    response.resolve(new Response(null, { status: 204 }))
    expect(await screen.findByText('Backend health: 204')).toBeInTheDocument()
  })

  it('shows the HTTP status 503 when the backend is unhealthy', async () => {
    stubFetch(() => Promise.resolve(new Response('{}', { status: 503 })))

    render(<HealthStatus />)

    expect(await screen.findByText('Backend health: 503')).toBeInTheDocument()
  })

  it('shows that the backend is unreachable when the request fails', async () => {
    stubFetch(() => Promise.reject(new TypeError('Failed to fetch')))

    render(<HealthStatus />)

    expect(await screen.findByText('Backend health: unreachable')).toBeInTheDocument()
  })

  it('aborts the request when unmounted', () => {
    const fetchMock = stubFetch(() => new Promise<Response>(() => {}))

    const { unmount } = render(<HealthStatus />)
    unmount()

    expect(fetchMock.mock.calls[0]?.[1]?.signal?.aborted).toBe(true)
  })
})
