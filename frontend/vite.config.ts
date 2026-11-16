/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Development: the backend runs separately (`dotnet run`, http profile on port 8080, the port of
// the ASP.NET container image) and Vite proxies API calls to it, so the app uses the same relative
// /api paths as in production, where the backend serves the built app itself.
const backendUrl = 'http://localhost:8080'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
