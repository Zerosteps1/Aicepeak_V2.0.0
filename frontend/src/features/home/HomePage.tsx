import { useNavigate } from 'react-router'
import { useAuth } from '../../auth/useAuth.ts'
import { AppFrame } from './AppFrame.tsx'
import styles from './HomePage.module.scss'

/** The protected home screen: the signed-in user's record as formatted JSON. */
export function HomePage() {
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  function handleSignOut() {
    signOut()
    void navigate('/login', { replace: true })
  }

  return (
    <div className={styles.page}>
      <AppFrame onSignOut={handleSignOut}>
        <div className="pg-head">
          <div className="pg-head__main">
            <h1 className="pg-head__title page-title">
              Ihr Konto<span className="pg-stop">.</span>
            </h1>
          </div>
        </div>
        <section className={styles.panel} aria-label="Benutzerdatensatz">
          <pre className={styles.json}>{JSON.stringify(user, null, 2)}</pre>
        </section>
      </AppFrame>
    </div>
  )
}
