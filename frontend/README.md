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
cd backend && dotnet watch --project src/Aicepeak.Api # http://localhost:5043, C# hot reload
cd frontend && npm run dev                            # http://localhost:5173
```

Open http://localhost:5173. Vite proxies `/api/*` to the backend, so the app calls the same relative paths as in production.

## Production

`dotnet publish` of the backend runs `npm ci` and `npm run build` and copies `dist/` into the backend's `wwwroot`. The backend then serves the app at `/`.

## Structure

- `src/api/`: backend calls. `httpClient.ts` is the single place that sends requests; the Microsoft Entra access token will be attached there.
- `src/features/<feature>/`: components with their `*.module.scss` and tests.
- `src/styles/`: global styles.
- `src/main.tsx`: entry point; `MsalProvider` will wrap `<App />` here.
