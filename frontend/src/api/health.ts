import { apiFetch } from './httpClient.ts'

/**
 * Returns the HTTP status of the backend health check: 204 when healthy, 503 when not.
 * Rejects only when the backend cannot be reached.
 */
export async function getHealthStatus(signal?: AbortSignal): Promise<number> {
  const response = await apiFetch('/health/alive', { signal, cache: 'no-store' })
  return response.status
}
