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
cd backend && dotnet watch    # http://localhost:8080, C# hot reload
cd frontend && npm run dev    # http://localhost:5173
```

Open http://localhost:5173. Vite proxies `/api/*` to the backend, so the app calls the same relative paths as in production.

## Configuration

Sign-in uses Microsoft Entra ID. The frontend has no settings of its own: the backend fills `window.__AICEPEAK_CONFIG__` in `index.html` at startup from its `ENTRA_AUDIENCE` and `ENTRA_SCOPE`, so one build runs in every environment. The dev server does the same from `backend/.env` (`vite.config.ts`); restart `npm run dev` after changing it.

The redirect URI is `<origin>/login`, e.g. `http://localhost:5173/login`; it must be registered for the single-page application. Without the config the sign-in button shows an error and the browser console says which value is missing.

## Production

`dotnet publish` of the backend runs `npm ci` and `npm run build` and copies `dist/` into the backend's `wwwroot`. The backend then serves the app at `/`.

## Structure

- `src/main.tsx`: entry point. Creates the MSAL `PublicClientApplication` and wraps `<App />` in `MsalProvider`, the router, `ThemeProvider` and `AuthProvider`.
- `src/auth/`: sign-in with Microsoft Entra ID (redirect, PKCE). `AuthProvider` and `useAuth()` are the only auth context components use: status, current user, error, `signIn`, `signOut`. `msalConfig.ts` reads the config the backend injected into `index.html`; `RequireAuth` sends signed-out users to `/login`.
- `src/theme/`: `ThemeProvider` and `useTheme()` for light and dark mode (`?theme=light|dark`, kept for the browser tab so it survives the sign-in redirect; otherwise the system setting); sets `data-theme` on `<html>`.
- `src/api/`: backend calls. `httpClient.ts` is the single place that sends requests and attaches the access token as `Authorization: Bearer`; failed calls reject with `ApiError` (status, and for a 400 every field error of the ValidationProblem). `projects.ts` creates, loads and patches projects (documents are embedded as `DocumentRef`); `documents.ts` asks for upload URLs (or gets the duplicate the tenant already has) and removes documents. `eventStream.ts` reads server-sent events through `apiFetch`, since `EventSource` cannot send the token; `documentStreams.ts` types and checks the validation and extraction events and reads a run until its final event: after a network error, a 5xx or a stream that closes before its last event it reconnects up to 3 times (after 1 s, 3 s and 10 s, each time with a fresh token; a token renewal that fails because the network is down counts as a network error too); a 4xx or an error of the whole run ends it at once.
- `src/api/blobStorage/`: uploads straight to blob storage behind a provider-neutral `BlobUploader`. `index.ts` is the only place that picks the provider (Azure today, matching the backend's `BLOB_PROVIDER`); `azureBlobUploader.ts` PUTs with the SAS URL and never sends the app's token.
- `src/design/`: the approved design (`tokens.css`, `components.css`, the logo), derived from `design/`. `tokens.css` orders the greys on a scale `l0`–`l8` (background side to text side) and names the colours `primary`, `secondary` (alias `primary-negative`), `warning` and `positive`, with the modifiers `-ink`, `-dim`, `on-` and `-muted`; its header explains them.
- `src/features/<feature>/`: components with their `*.module.scss` and tests.
- `src/features/login/`: the sign-in page. `SignInTransition` (`.tsx` + `.module.scss`) holds the layers behind the card and the whole sign-in animation: zoom, blur, veil and card timings live only in its SCSS, and the component waits for that transition before showing the next page. With reduced motion turned on, there is no transition.
- `src/features/home/`: the protected home screen, its frame (glass menu bar) and the skeleton shown behind the sign-in card. `newProject.ts` holds the defaults of a new project.
- `src/features/documentUpload/`: the logic of the "Neues Projekt" flow (add and check documents, then extract), without UI so far. `ProjectFlowProvider` holds its state once in one `useState`; components read it with `useProjectFlowState()`, derive everything they show with the pure functions of `selectors.ts` and call the plain functions of `useProjectFlowActions()` (`addFiles`, `removeDocument`, `advance`, `retryValidation`, `retryExtraction`). When a stream has given up, documents without a result stay failed and block `advance`; `retryValidation` and `retryExtraction` start the run again (`selectCanRetryValidation`, `selectCanRetryExtraction`). There is no store, reducer or dispatch: `flowState.ts` holds the state changes as plain functions for `setState((prev) => …)`. `uploadDocument.ts` hashes, gets an upload URL and uploads one file; `files.ts` holds the accepted kinds, limits and name rules, the same as the backend's.
- `src/styles/`: global styles.
- `lint/aicepeak-state.js`: an oxlint JS plugin (registered in `.oxlintrc.json`) that keeps state in one place: no state initialised from props, state, context or a hook call (`no-state-copy-init`), no setter called synchronously while an effect runs, also not from an inline callback or a function the effect calls (`no-sync-state-effect`), no `ref.current =` that mirrors props, state or context, also not through a plain alias (`no-ref-mirror`), no router state, also not through a spread or an options variable (`no-router-state`) and `createContext` only in `*Context.ts` files, under any import name (`context-files-only`). The rules are static checks with limits: each rule's `meta.docs` says exactly what it reports (e.g. values computed from props and useRef's initial value are not reported); `aicepeak-state.test.ts` tests them, and `aicepeak-state.d.ts` types the plugin so `tsc -b` checks that test (`tsconfig.lint.json`). A justified exception is marked with `// oxlint-disable-next-line <rule> -- <reason>`.
