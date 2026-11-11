import { useEffect, useState } from 'react'
import { getHealthStatus } from '../../api/health.ts'
import styles from './HealthStatus.module.scss'

type HealthState =
  | { kind: 'checking' }
  | { kind: 'done'; status: number }
  | { kind: 'unreachable' }

function describe(state: HealthState): string {
  switch (state.kind) {
    case 'checking':
      return 'checking…'
    case 'done':
      return String(state.status)
    case 'unreachable':
      return 'unreachable'
  }
}

/** Shows the HTTP status of the backend health check as plain text. */
export function HealthStatus() {
  const [state, setState] = useState<HealthState>({ kind: 'checking' })

  useEffect(() => {
    const controller = new AbortController()

    getHealthStatus(controller.signal)
      .then((status) => setState({ kind: 'done', status }))
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
