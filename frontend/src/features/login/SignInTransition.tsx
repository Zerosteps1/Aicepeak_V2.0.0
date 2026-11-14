import { useEffect, type ReactNode } from 'react'
import styles from './SignInTransition.module.scss'

type SignInTransitionProps = {
  /** `out` signed out, `auth` signing in, `in` signed in. */
  phase: 'out' | 'auth' | 'in'
  /** The app behind the card, zoomed out and blurred until signed in. */
  background: ReactNode
  /** The sign-in card. */
  children: ReactNode
  /** Called once the change to `in` has finished. */
  onDone: () => void
}

/** The layers of the sign-in screen and, later, their animation: app behind, veil, card. */
export function SignInTransition({ phase, background, children, onDone }: SignInTransitionProps) {
  const signedIn = phase === 'in'

  // No animation yet, so the change to `in` is done at once.
  useEffect(() => {
    if (signedIn) {
      onDone()
    }
  }, [signedIn, onDone])

  return (
    <div className={styles.root} data-phase={phase}>
      <div className={styles.background} data-testid="sign-in-background" inert={!signedIn} aria-hidden={!signedIn || undefined}>
        {background}
      </div>
      <div className={`pg-veil ${styles.veil}`} aria-hidden="true" />
      <div className={styles.card} inert={signedIn}>
        {children}
      </div>
    </div>
  )
}
