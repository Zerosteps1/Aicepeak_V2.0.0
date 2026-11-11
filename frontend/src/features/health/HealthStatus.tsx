import { useEffect, useState } from 'react'
import { getHealthStatus } from '../../api/health.ts'
import styles from './HealthStatus.module.scss'

/** A proxy in front of the backend (the Vite dev server) answers 502 when the backend is not running. */
const BAD_GATEWAY = 502

type HealthState =
  | { kind: 'checking' }
  | { kind: 'done'; status: number }
  | { kind: 'unreachable'; status?: number }

function describe(state: HealthState): string {
  switch (state.kind) {
    case 'checking':
      return 'checking…'
    case 'done':
      return String(state.status)
    case 'unreachable':
      return state.status === undefined ? 'unreachable' : `unreachable (${state.status})`
  }
}

/** Shows the HTTP status of the backend health check as plain text. */
export function HealthStatus() {
  const [state, setState] = useState<HealthState>({ kind: 'checking' })

  useEffect(() => {
    const controller = new AbortController()

    getHealthStatus(controller.signal)
      .then((status) => setState(status === BAD_GATEWAY ? { kind: 'unreachable', status } : { kind: 'done', status }))
      .catch(() => {
        if (!controller.signal.aborted) {
          setState({ kind: 'unreachable' })
        }
      })

    return () => controller.abort()
  }, [])

  return (
    <p role="status" className={styles.status}>
      Backend health: {describe(state)}
    </p>
  )
}
