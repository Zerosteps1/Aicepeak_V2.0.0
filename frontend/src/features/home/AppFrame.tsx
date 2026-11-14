import type { ReactNode } from 'react'
import logoUrl from '/src/design/aicepeak-mark.png'
import styles from './AppFrame.module.scss'

type AppFrameProps = {
  onSignOut?: () => void
  children: ReactNode
}

/** The frame of every signed-in screen: glass menu bar over the blue glow, paper content below. */
export function AppFrame({ onSignOut, children }: AppFrameProps) {
  return (
    <div className={styles.frame}>
      <div className={styles.glow} aria-hidden="true" />
      <header className={`pg-glass pg-glass--airy pg-bar ${styles.bar}`}>
        <div className="pg-bar__start">
          <img className="pg-bar__logo" src={logoUrl} alt="Aicepeak" />
        </div>
        <div className="pg-bar__end">
          <button type="button" className="pg-icon-btn" aria-label="Abmelden" title="Abmelden" onClick={onSignOut}>
            <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}>
              <path d="M14 4h5v16h-5" />
              <path d="M10 8l-4 4 4 4M6 12h10" />
            </svg>
          </button>
        </div>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  )
}
