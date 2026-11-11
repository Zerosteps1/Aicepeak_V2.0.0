import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { App } from './App.tsx'

describe('App', () => {
  it('shows the heading and the backend health', () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>(() => new Promise<Response>(() => {})))

    render(<App />)

    expect(screen.getByRole('heading', { name: 'Aicepeak' })).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Backend health:')
  })
})
