/// <reference types="vitest/config" />
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

// Development: the backend runs separately (`dotnet run`, http profile on port 8080, the port of
// the ASP.NET container image) and Vite proxies API calls to it, so the app uses the same relative
// /api paths as in production, where the backend serves the built app itself.
const backendUrl = 'http://localhost:8080'

// The placeholder in index.html that the backend fills at startup (backend/Frontend/FrontendHosting.cs).
const CONFIG_MARKER = 'null /* aicepeak-config */'
const backendEnvFile = fileURLToPath(new URL('../backend/.env', import.meta.url))

/** KEY=VALUE lines of backend/.env, read like backend/start does: comments skipped, one pair of quotes stripped. */
function readBackendEnv(): Record<string, string> {
  if (!existsSync(backendEnvFile)) {
    return {}
  }
  const values: Record<string, string> = {}
  for (const raw of readFileSync(backendEnvFile, 'utf8').split(/\r?\n/)) {
    const line = raw.trim().replace(/^export\s+/, '')
    const separator = line.indexOf('=')
    if (!line || line.startsWith('#') || separator < 0) {
      continue
    }
    let value = line.slice(separator + 1).trim()
    if (value.length >= 2 && value[0] === value[value.length - 1] && `'"`.includes(value[0])) {
      value = value.slice(1, -1)
    }
    values[line.slice(0, separator).trim()] = value
  }
  return values
}

/**
 * Development only: fills the Entra config into index.html the way the backend does in production, from ENTRA_AUDIENCE
 * and ENTRA_SCOPE (real environment variables win over backend/.env). The build keeps the placeholder.
 */
function entraConfig(): Plugin {
  return {
    name: 'aicepeak-entra-config',
    apply: 'serve',
    transformIndexHtml(html) {
      const env = readBackendEnv()
      const audience = (process.env.ENTRA_AUDIENCE ?? env.ENTRA_AUDIENCE ?? '').trim()
      const scope = (process.env.ENTRA_SCOPE ?? env.ENTRA_SCOPE ?? '').trim()
      const config = audience && scope ? JSON.stringify({ clientId: audience, apiScope: `api://${audience}/${scope}` }) : 'null'
      // Escaped like the backend's JSON, so a value can never close the script element.
      const escaped = config.replace(/</g, '\\u003C').replace(/>/g, '\\u003E').replace(/&/g, '\\u0026')
      // A function, so `$` in a value is not read as a replacement pattern.
      return html.replace(CONFIG_MARKER, () => escaped)
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), entraConfig()],
  server: {
    proxy: {
      '/api/': backendUrl,
    },
  },
  preview: {
    proxy: {
      '/api/': backendUrl,
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    unstubGlobals: true,
    restoreMocks: true,
  },
})
