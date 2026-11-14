import { useEffect, useRef, type ReactNode } from 'react'
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

/** Milliseconds of a CSS time list such as `1.2s, 520ms`. */
function times(value: string): number[] {
  return value.split(',').map((part) => {
    const time = part.trim()
    const number = Number.parseFloat(time)
    if (Number.isNaN(number)) {
      return 0
    }
    return time.endsWith('ms') ? number : number * 1000
  })
}

/** How long the element's transitions run, delays included; 0 when none runs (e.g. reduced motion). */
function transitionMs(element: Element): number {
  const style = getComputedStyle(element)
  const durations = times(style.transitionDuration)
  const delays = times(style.transitionDelay)
  return Math.max(0, ...durations.map((duration, index) => duration + (delays[index % delays.length] ?? 0)))
}

/**
 * The layers of the sign-in screen and their animation: app behind, veil, card. Every look and timing lives in
 * SignInTransition.module.scss; this component only waits for the app layer's transition before calling `onDone`.
 */
export function SignInTransition({ phase, background, children, onDone }: SignInTransitionProps) {
  const signedIn = phase === 'in'
  const backgroundRef = useRef<HTMLDivElement>(null)
  // Already signed in when shown: nothing changes, so there is nothing to wait for.
  const startedSignedIn = useRef(signedIn)
  const onDoneRef = useRef(onDone)

  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    const element = backgroundRef.current
    if (!signedIn || !element) {
      return
    }
    const duration = startedSignedIn.current ? 0 : transitionMs(element)
    if (duration === 0) {
      onDoneRef.current()
      return
    }

    let done = false
    const finish = () => {
      if (!done) {
        done = true
        onDoneRef.current()
      }
    }
    const handleEnd = (event: TransitionEvent) => {
      if (event.target === element && event.propertyName === 'transform') {
        finish()
      }
    }
    element.addEventListener('transitionend', handleEnd)
    // In case transitionend never arrives (e.g. a hidden tab).
    const timer = window.setTimeout(finish, duration + 100)
    return () => {
      element.removeEventListener('transitionend', handleEnd)
      window.clearTimeout(timer)
    }
  }, [signedIn])

  return (
    <div className={styles.root} data-phase={phase}>
      <div
        ref={backgroundRef}
        className={styles.background}
        data-testid="sign-in-background"
        inert={!signedIn}
        aria-hidden={!signedIn || undefined}
      >
        {background}
      </div>
      <div className={`pg-veil ${styles.veil}`} aria-hidden="true" />
      <div className={styles.card} inert={signedIn}>
        {children}
      </div>
    </div>
  )
}
