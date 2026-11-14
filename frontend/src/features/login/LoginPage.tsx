import { useCallback, useId, type ReactNode, type SubmitEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import logoUrl from '/src/design/aicepeak-mark.png'
import { useAuth } from '../../auth/useAuth.ts'
import styles from './LoginPage.module.scss'
import { SignInTransition } from './SignInTransition.tsx'

type LoginPageProps = {
  /** The page the user lands on after signing in, shown behind the card. */
  background: ReactNode
}

/** The sign-in card of the approved design over the blurred next page. */
export function LoginPage({ background }: LoginPageProps) {
  const { status, error, returnTo, signIn } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const titleId = useId()

  const phase = status === 'signedIn' ? 'in' : status === 'signedOut' ? 'out' : 'auth'
  const busy = phase === 'auth'
  const from = (location.state as { from?: unknown } | null)?.from
  const target = returnTo ?? (typeof from === 'string' ? from : '/')

  const handleDone = useCallback(() => {
    void navigate(target, { replace: true })
  }, [navigate, target])

  function handleSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault()
    if (phase === 'out') {
      signIn(typeof from === 'string' ? from : undefined)
    }
  }

  return (
    <SignInTransition phase={phase} background={background} onDone={handleDone}>
      <form className="pg-signin" role="dialog" aria-modal="true" aria-labelledby={titleId} onSubmit={handleSubmit}>
        <img className="pg-signin__logo" src={logoUrl} alt="Aicepeak" />
        <h1 id={titleId} className="pg-signin__title sign-in-title">
          Anmelden<span className="pg-stop">.</span>
        </h1>
        <button type="submit" className="pg-signin__btn" aria-busy={busy || undefined}>
          <span>{busy ? 'Anmeldung läuft …' : 'Mit Microsoft anmelden'}</span>
          <span className="pg-signin__arrow" aria-hidden="true">
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h14" />
              <path d="M13 6l6 6-6 6" />
            </svg>
          </span>
        </button>
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
        <p className="pg-signin__note">Kein Zugang? Ihre IT-Administration schaltet Sie in Microsoft Entra ID frei.</p>
      </form>
    </SignInTransition>
  )
}
