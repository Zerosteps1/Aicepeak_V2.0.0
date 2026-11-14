import { describe, expect, it, vi } from 'vitest'
import { registerLogin } from './login.ts'

const USER = { tid: 'db760528-cb7c-455c-bd41-e50a38f6fd62', oid: '7b4a5e1c-0000-4000-8000-000000000001', name: 'Erika' }

describe('registerLogin', () => {
  it('AC-5: sends PUT /api/v1/login and returns the user record', async () => {
    const fetchMock = vi.fn<typeof fetch>(async () => Response.json(USER))
    vi.stubGlobal('fetch', fetchMock)

    await expect(registerLogin()).resolves.toEqual(USER)
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/login', { method: 'PUT' })
  })

  it('AC-8: rejects when the backend answers 401', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(async () => new Response('Authentication header missing', { status: 401 })))

    await expect(registerLogin()).rejects.toThrow('HTTP 401')
  })
})
