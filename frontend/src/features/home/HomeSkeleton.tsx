import { AppFrame } from './AppFrame.tsx'
import styles from './HomeSkeleton.module.scss'

const LINE_WIDTHS = ['8%', '46%', '46%', '30%', '8%']

/** The home screen's layout with placeholders instead of content; shown behind the sign-in card. */
export function HomeSkeleton() {
  return (
    <AppFrame>
      <div className={`${styles.block} ${styles.title}`} data-testid="home-skeleton" />
      <div className={styles.panel}>
        {LINE_WIDTHS.map((width, index) => (
          <div key={index} className={`${styles.block} ${styles.line}`} style={{ width }} />
        ))}
      </div>
    </AppFrame>
  )
}
