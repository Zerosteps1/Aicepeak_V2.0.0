import { useContext } from 'react'
import { AuthContext, type AuthContextValue } from './authContext.ts'

/** The current user and the sign-in state. The only auth API that app components use. */
export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return value
}
