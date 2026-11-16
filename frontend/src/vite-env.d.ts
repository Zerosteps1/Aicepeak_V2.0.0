/// <reference types="vite/client" />

/** The Entra config filled into index.html by the backend (see backend/Frontend/FrontendHosting.cs). */
type AppConfig = { clientId: string; apiScope: string }

interface Window {
  /** `null` when the backend's ENTRA_AUDIENCE or ENTRA_SCOPE is not set. */
  __AICEPEAK_CONFIG__?: AppConfig | null
}
