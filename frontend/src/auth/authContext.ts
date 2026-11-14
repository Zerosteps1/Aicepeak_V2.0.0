import { createContext } from 'react'
import type { User } from '../api/types.ts'

export type AuthStatus = 'loading' | 'signedOut' | 'signingIn' | 'signedIn'

export type AuthContextValue = {
  status: AuthStatus
  user: User | null
  /** Why the last sign-in attempt failed, ready to show. */
  error: string | null
  /** The path the user wanted before signing in, carried through the Microsoft redirect. */
  returnTo: string | null
  /** Starts the Microsoft Entra sign-in; `from` is returned as `returnTo` afterwards. */
  signIn: (from?: string) => void
  /** Clears the local session only; the caller navigates to `/login`. */
  signOut: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
