# Aicepeak frontend

TypeScript + React, built with Vite. Styles use SCSS with CSS Modules; tests use Vitest and Testing Library.

## Scripts

| Command | Purpose |
|---|---|
| `npm ci` | Install the locked dependencies |
| `npm run dev` | Dev server with hot reload on http://localhost:5173 |
| `npm test` | Run the tests once (`npm run test:watch` to watch) |
| `npm run lint` | Lint with oxlint; warnings fail the check |
| `npm run build` | Type-check and build into `dist/` |

## Development

Run the backend and the dev server in two terminals:

```sh
cd backend && dotnet watch    # http://localhost:5043, C# hot reload
cd frontend && npm run dev    # http://localhost:5173
```

Open http://localhost:5173. Vite proxies `/api/*` to the backend, so the app calls the same relative paths as in production.

## Configuration

Sign-in uses Microsoft Entra ID. Copy `.env.example` to `.env` (git-ignored) and set:

| Variable | Value |
|---|---|
| `VITE_ENTRA_CLIENT_ID` | Client ID of the single-page application registration |
| `VITE_ENTRA_API_SCOPE` | Full API scope, e.g. `api://<api-client-id>/access_as_user` |

The redirect URI is `<origin>/login`, e.g. `http://localhost:5173/login`; it must be registered for the single-page application. Without both variables the sign-in button shows an error and the browser console names the missing variable.

## Production

`dotnet publish` of the backend runs `npm ci` and `npm run build` and copies `dist/` into the backend's `wwwroot`. The backend then serves the app at `/`.

## Structure

- `src/main.tsx`: entry point. Creates the MSAL `PublicClientApplication` and wraps `<App />` in `MsalProvider`, the router, `ThemeProvider` and `AuthProvider`.
- `src/auth/`: sign-in with Microsoft Entra ID (redirect, PKCE). `AuthProvider` and `useAuth()` are the only auth context components use: status, current user, error, `signIn`, `signOut`. `msalConfig.ts` reads the `VITE_ENTRA_*` settings; `RequireAuth` sends signed-out users to `/login`.
- `src/theme/`: `ThemeProvider` and `useTheme()` for light and dark mode (`?theme=light|dark`, kept for the browser tab so it survives the sign-in redirect; otherwise the system setting); sets `data-theme` on `<html>`.
- `src/api/`: backend calls. `httpClient.ts` is the single place that sends requests and attaches the access token as `Authorization: Bearer`.
- `src/design/`: snapshot of the approved design (`tokens.css`, `components.css`, the logo). Do not edit; update it from the design export.
- `src/features/<feature>/`: components with their `*.module.scss` and tests.
- `src/features/login/`: the sign-in page. `SignInTransition` holds the layers behind the card and is the one place for the sign-in animation.
- `src/features/home/`: the protected home screen, its frame (glass menu bar) and the skeleton shown behind the sign-in card.
- `src/styles/`: global styles.
