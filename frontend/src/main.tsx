import '/src/design/tokens.css'
import '/src/design/components.css'
import './styles/global.scss'
import { MsalProvider } from '@azure/msal-react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { App } from './App.tsx'
import { AuthProvider } from './auth/AuthProvider.tsx'
import { createMsalInstance } from './auth/msalConfig.ts'
import { initialTheme } from './theme/themeContext.ts'
import { ThemeProvider } from './theme/ThemeProvider.tsx'

const rootElement = document.getElementById('root')
if (!rootElement) {
  throw new Error('Root element #root not found')
}

// Before MSAL initializes, so the page never shows the wrong theme.
document.documentElement.dataset.theme = initialTheme()

const msalInstance = createMsalInstance()
await msalInstance.initialize()

createRoot(rootElement).render(
  <StrictMode>
    <MsalProvider instance={msalInstance}>
      <BrowserRouter>
        <ThemeProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </MsalProvider>
  </StrictMode>,
)
