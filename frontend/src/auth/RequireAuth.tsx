import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { useAuth } from './useAuth.ts'

/** Renders its children only when signed in; otherwise sends the user to /login and remembers where they were. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'signedIn') {
    return children
  }
  if (status === 'loading') {
    return null
  }
  return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
}
