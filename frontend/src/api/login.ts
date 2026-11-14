import { apiFetch } from './httpClient.ts'
import type { User } from './types.ts'

/** Creates the signed-in user's record if it does not exist yet and returns it. */
export async function registerLogin(): Promise<User> {
  const response = await apiFetch('/login', { method: 'PUT' })
  if (!response.ok) {
    throw new Error(`PUT /login failed with HTTP ${response.status}`)
  }
  return (await response.json()) as User
}
