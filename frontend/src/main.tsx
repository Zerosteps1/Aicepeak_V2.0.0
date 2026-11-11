import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App.tsx'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found')
}

// Microsoft Entra ID (later): create the MSAL PublicClientApplication here and wrap <App /> in <MsalProvider>.
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
