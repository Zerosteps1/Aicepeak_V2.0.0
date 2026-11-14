# Development setup (macOS)

One-time setup of a maintainer device for the [software factory](software-factory.md). After it, follow [way-of-working.md](way-of-working.md) for daily use; every `factory` command is described in [factory-cli.md](factory-cli.md).

A device can take two roles:

- **Reviewer device:** runs the binding senior review (`factory watch`). Needs steps 1–3 and 5.
- **Author device:** additionally runs isolated author runs (`factory start`, `fix`, `hotfix`, `review`). Needs steps 1–5.

This runbook assumes the repository owner has completed the access handoff in step 1. It cannot grant account permissions or generate an owner-only App key. Use your own Terminal for the credential steps; never paste a secret into an agent session.

## 1. Access handoff — repository owner and new maintainer, once

- **GitHub:** accept the repository invitation and sign in with your maintainer account, the one listed in `maintainers` in [factory/config.json](../factory/config.json). If you have more than one listed account, pick one as your active account; use your own identity.
- **ChatGPT:** the new maintainer needs their own Business workspace seat, local Codex permission and permission to create access tokens. A workspace owner enables these if the token page is unavailable. Follow the [official access-token instructions](https://learn.chatgpt.com/docs/enterprise/access-tokens).
- **Publisher App:** the repository owner opens the publisher App's settings (App ID 5510081, in the owner's GitHub App developer settings), creates a separate key for the new maintainer's device and transfers the PEM through an agreed secure secret-sharing channel. Record which device owns it so it can be revoked separately. GitHub repository write access alone does not grant App-key administration. Follow [GitHub's private-key instructions](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/managing-private-keys-for-github-apps). A maintainer device never needs the writer key.
- **Local author sessions:** agree which Anthropic Console workspace pays for API calls and grant access to its API key plus a Context7 API key. These are separate from the Claude subscription and the WIF credentials used by GitHub Actions. They are not needed for a reviewer-only device.

## 2. Install tools and sign in

Install [Homebrew](https://brew.sh/) if it is not already available. In a normal Terminal:

```sh
brew install python git gh node
npm install --prefix "$HOME/.local/share/aicepeak-factory-cli" @openai/codex@0.164.0
export PATH="$HOME/.local/share/aicepeak-factory-cli/node_modules/.bin:$PATH"
python3 --version
git --version
gh --version
codex --version
```

Expected: Python **3.11 or newer** and exactly the Codex version that [factory/package.json](../factory/package.json) pins (`@openai/codex`, today **`codex-cli 0.164.0`**; install that version in the command above). The `factory` command puts this pinned Codex directory in front of the `PATH` of its helper processes itself; reapply the `export PATH` line only in Terminals where you run `session.py` or `local_review.py` by hand. This separate installation does not replace a personal Codex installation. If the access-token UI requires a newer CLI, stop and request a reviewed factory version update; do not silently upgrade the pinned reviewer.

For isolated author runs, install and start Docker Desktop as described in [Docker](#docker) at the end of this runbook. Claude Code is installed inside the factory image; no host Claude installation is required.

Sign in to GitHub and check your access:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh api user --jq .login
gh api repos/Zerosteps1/Aicepeak_V2.0.0 --jq '.permissions.push'
```

Expected: your active maintainer login and `true`; a public clone alone does not prove write access. The [GitHub browser login](https://cli.github.com/manual/gh_auth_login) handles authentication without pasting a GitHub token into the factory.

### Install the factory command

The installer creates your two checkouts and the global `factory` command ([details](factory-cli.md#install)). The clone path is relative to your current directory, and the installer puts the candidate checkout next to that clone: run it from a folder whose parent should hold both checkouts, for example from an existing clone in `~/repos/`.

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../aicepeak-control-checkout && ../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh
```

The installer takes the initial configuration from the production branch GitHub protects (today `production`; with several it asks, or takes `--config-branch NAME`; when `gh` cannot read GitHub's rulesets it falls back to the GitHub default branch `testing`), reads the config branch there, follows a finished config branch change once (it then prints a `note: … following it`), verifies itself against the config branch's copy and puts the control checkout on the config branch; `--branch <listed branch>` chooses another listed branch, which you can change later with `factory use branch`. It asks for the Git `user.name` and `user.email` for commits in the candidate if they are not set there (use your own name and verified GitHub email), and offers to store the author keys (step 4; answer no on a reviewer-only device). Then open a new Terminal if it added a PATH block to `~/.zshrc`. The device configuration `~/.config/aicepeak-factory/cli.json` records both paths and the control branch.

- **Control checkout** (`aicepeak-control-checkout`): trusted CLI code on its control branch, by default the config branch. `factory` verifies and fast-forwards it before every command; every rule comes from the config branch tip. Never make changes in it: `factory` and the factory tools refuse to run if it differs from its branch by even one file, including ignored files such as `__pycache__` or `.venv`; only Finder's `.DS_Store` files are tolerated ([why](software-factory.md#the-control-checkout)). Keep it out of Finder and your editor's workspace, and store patches, reports, PR descriptions and credentials outside all checkouts.
- **Candidate checkout** (`aicepeak-candidate`): the only place where you edit, apply, commit and push. `factory` creates one branch per work order in it, named as GitHub names an issue's branch (`57-<issue title>`; [way of working](way-of-working.md#daily-use-step-by-step)).

### Check the tools

```sh
factory doctor
```

`factory doctor` prints `ok` or `FAIL` with the fix for each of its own checks (shim, checkouts, author keys, Docker, image, pinned Codex, `gh` maintainer login; it starts a stopped Docker Desktop, wakes it from its resource saver and waits up to 2 minutes, as every author run does) and then summarises `doctor.py` from a disposable checkout of the config branch tip, including the native adapter check and the branch model: each blocked check of `doctor.py` on its own line with its fix. **`doctor.py` exit 2 is expected:** it always leaves live acceptance open and, at this stage, keys/image may also be missing. Under `factory doctor` it never sees the author keys (only author runs get them), so `factory doctor` marks its two key checks as `expected` whenever its own check found the key, exported or in the keychain; its Docker checks use `FACTORY_DOCKER_HOST` only when exported. It also checks Docker, author keys and local verifier tools on reviewer-only devices. Read each named check instead of treating a blocked check as a failed installation. `actionlint` and `gitleaks` are only needed for full local verification. When they are missing, `factory doctor` prints one command that installs them: `factory/install_tools.py` downloads the exact releases pinned in `factory/tools.lock.json`, checks their SHA-256 and puts them next to the `factory` command (Linux and macOS; the factory image uses the same installer).

### Test changes in the sandbox

Test changes to the factory the way the pipeline does, in the trusted test image ([factory/test.Dockerfile](../factory/test.Dockerfile), Docker running), with a read-only root filesystem, no network and a throwaway copy of the files Git sees in your working tree (uncommitted and untracked changes included, ignored files such as `node_modules` left out). The first run builds the test image, which takes a few minutes; later runs reuse it until `factory/test.Dockerfile` or a file it copies changes ([test image](../factory/clients.md#test-image)):

```sh
tools/factory/sandbox-verify.sh                  # full verify.py --ci: ends with four PASS lines
tools/factory/sandbox-verify.sh 'test_cli*.py'   # only the unit tests whose file names match the pattern
```

Run it from the checkout you changed; it never writes into the repository. To try a change with the `factory` command itself, push it to `testing` (maintainers may push there directly), run `factory use branch testing`, and switch back with `factory use branch production`: the command runs only listed branches, while the rules always come from the config branch.

## 3. Configure and test the reviewer

In the correct Business workspace, open [Access tokens](https://chatgpt.com/admin/access-tokens), create a token for your device with **Codex** scope and a finite expiration, and copy it once. This is a personal workspace access token, not a browser session token or a Platform API key. Store it using the password prompt; `-U` also supports rotation. Run the smoke from the control checkout, with the pinned Codex directory on `PATH` (step 2):

```sh
security add-generic-password -U -a "$USER" -s aicepeak-factory-codex-access-token -w
cd ../aicepeak-control-checkout    # your control checkout; read-only use
python3 tools/factory/local_review.py --smoke
```

Expected: `"status": "passed"`, `gpt-6-astra`, effort `high`. The smoke uses the personal Codex quota and does not test GitHub publication. On expiry, create a replacement, repeat the keychain command and smoke, then revoke the old token. A 404/forbidden token page requires the workspace owner's permission change; repeatedly logging into GitHub will not fix it.

Store the publisher PEM you received from the repository owner separately. This **zsh** block asks for an absolute path and validates the file before changing the keychain entry:

```sh
read -r "FACTORY_PEM?Absolute path to your publisher PEM: "
if [[ "$FACTORY_PEM" = /* && -s "$FACTORY_PEM" ]] && openssl rsa -in "$FACTORY_PEM" -check -noout; then
  security add-generic-password -U -a "$USER" -s aicepeak-factory-publisher-key \
    -w "$(base64 < "$FACTORY_PEM" | tr -d '\n')"
else
  printf 'No key stored: provide an existing, valid publisher PEM using an absolute path.\n'
fi
unset FACTORY_PEM
```

Never put tokens or PEM contents into chat, Git or PR text. An environment variable `CODEX_ACCESS_TOKEN` or `FACTORY_PUBLISHER_APP_PRIVATE_KEY` overrides the keychain; remove a stale override in your Terminal if rotation appears ineffective. Details: [reviewer credentials](../factory/clients.md#senior-reviewer-maintainer-local).

## 4. Configure the isolated author (skip on reviewer-only devices)

Create or obtain an API key for the agreed [Anthropic Console](https://platform.claude.com/) workspace and an API key from the [Context7 dashboard](https://context7.com/dashboard). Store both in your login keychain with the installer, which asks before each key and reads it at a hidden prompt (enter it twice); `--author-keys` also rotates existing items. Use the same options as at installation:

```sh
../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh --author-keys
```

The keychain items are `aicepeak-factory-anthropic-api-key` and `aicepeak-factory-context7-api-key`. `factory` reads them for each author run and hands them only to the isolated launcher; exported `ANTHROPIC_API_KEY` and `CONTEXT7_API_KEY` win over the keychain. No per-Terminal export is needed for `factory`.

Build the factory image and run the container smoke from the control checkout. `factory` derives `FACTORY_DOCKER_HOST` from the active Docker context itself; for these manual commands export it:

```sh
cd ../aicepeak-control-checkout    # your control checkout; read-only use
export FACTORY_DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
docker build -f factory/Dockerfile -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
```

The image tag carries the two CLI versions that [factory/package.json](../factory/package.json) pins (today Codex 0.164.0 and Claude Code 2.1.311); `factory doctor` prints the build command with the current tag. Expected: image build succeeds and container smoke reports `passed`. If `docker-credential-desktop` cannot be found, add the actual Docker app's `Contents/Resources/bin` directory to this Terminal's `PATH`, then repeat the build; keep credential-store settings intact. The Docker app's name can differ between Macs (for example `Docker 2.app`); use your own installation path.

The container smoke does **not** prove authenticated skill or native MCP execution. The interactive launcher reads the keys only from its environment, so export them from the keychain for this one session, from the control checkout:

```sh
export ANTHROPIC_API_KEY="$(security find-generic-password -s aicepeak-factory-anthropic-api-key -w)"
export CONTEXT7_API_KEY="$(security find-generic-password -s aicepeak-factory-context7-api-key -w)"
python3 tools/factory/clients.py launch --root . --runner claude
unset ANTHROPIC_API_KEY CONTEXT7_API_KEY
```

In the session request: “Use factory-start for docs/work/FACTORY-SMOKE.md. Read the approved order, make a generic Context7 documentation lookup and an OpenAI Docs lookup, and report both outcomes without changing files.” Verify actual tool outcomes in that interactive session. This consumes Anthropic API usage; the local launcher needs the two keys even though Actions uses WIF.

## 5. Complete the first real review on a new device

Run `factory doctor` again and inspect the relevant checks. A reviewer needs the correct clean checkouts, GitHub identity/access, pinned Codex, personal-token smoke and publisher key. An author additionally needs Docker/image, both API keys, boundary smoke and the authenticated skill/MCP probe. A clean `factory doctor` still does not certify live acceptance (`doctor.py` keeps exiting 2).

Create a harmless smoke PR under the already approved [FACTORY-SMOKE](work/FACTORY-SMOKE.md). The device smoke is the one deliberate exception to "one work order is one GitHub issue and one PR": FACTORY-SMOKE is a work-order file on the config branch, and every new maintainer device opens its own smoke PR under it, to test that the system works for that maintainer. Coordinate with the other maintainers so **only your device watches this first smoke**; otherwise another device can win the review claim and two green checks would not test your key. Work in your candidate checkout. The branch name `<login>/FACTORY-SMOKE-<k>` ties it to the work order. The fixture change alters indentation only, leaving all numeric and text values correct:

```sh
cd ../aicepeak-candidate           # your candidate checkout
git fetch origin
git switch -c "$(gh api user --jq .login)/FACTORY-SMOKE-$(date +%Y%m%d%H%M%S)" origin/testing
python3 - <<'PY'
import json
from pathlib import Path
path = Path('factory-smoke.json')
value = json.loads(path.read_text())
assert value['quantity'] * value['unit_price'] == value['total']
path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + '\n')
PY
git diff -- factory-smoke.json
git add factory-smoke.json
factory submit --finished --title 'test(factory): reviewer device smoke' \
  --desc 'Verify a new reviewer device using the approved FACTORY-SMOKE fixture; formatting only.'
```

`origin/testing` is the validation branch that `smoke` work orders are routed to (see the [branch diagram](factory-branches.md)). `factory submit --finished` commits the staged file, pushes the branch, then runs `session.py submit`: advisory preflight, PR into `testing`, and its watcher. If `testing` moved meanwhile, merge the new `origin/testing` into the candidate branch (`git merge origin/testing`), commit any resolution, push it with `factory submit`, then retry; do not bypass freshness checks or use `/bypass`. If you resume an existing PR, use `factory watch <number>`. `factory` keeps the Mac from idle-sleeping while it watches; keep the lid open. Confirm both `factory/deterministic` and `factory/senior-review` from App **5510081** are successful for that PR's current head, the current `testing` tip and the current config branch policy (see [merge rules](way-of-working.md#merge-rules)). The watcher can keep polling after success; Ctrl-C stops it once both final checks are green. This is the publication test for your publisher key; a successful model smoke alone is insufficient. Record the head/base, run/check IDs and your executed probes in a reviewed evidence update ([factory/evidence.md](../factory/evidence.md)). Until then, your device remains unverified; already verified reviewer devices may review shared PRs.

Also inspect the final senior check receipt (`output.text` JSON) and confirm `claim.actor.login` is your active account. If another maintainer won the claim, this run is not acceptance of your device: coordinate again and create a fresh smoke PR or deliberate retry. The smoke fixture needs no merge. Product implementation still requires architecture decisions, implemented product checks and an approved product work order; the north-star approval alone does not remove that gate.

## PostgreSQL for development

The product uses PostgreSQL ([ADR-0010](decisions/0010-product-stack.md), decision 11). For local development, run it in a Docker container instead of installing it on the Mac. This needs Docker Desktop running (see [Docker](#docker)).

**Shortcut:** once `backend/.env` exists (see [Running Aicepeak locally](#running-aicepeak-locally)), `cd backend && ./start` does the steps below: it starts Docker Desktop if needed and creates or starts the container `aicepeak-pg` with the version (`DB_PG_VERSION`), port, database, user and password from `.env`. If an existing container has another version, port or password, it stops with a message and changes nothing. `./start --migrate` also applies the EF Core migrations. It needs only `python3` (standard library).

Manual steps:

Start a container named `aicepeak-pg`:

```sh
docker run -d --name aicepeak-pg \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 \
  postgres:17
```

This pulls the [official `postgres` image](https://hub.docker.com/_/postgres) on first use. It starts the server in the background on `localhost:5432` with the superuser `postgres` and the password `postgres`. These credentials are for local development only; never use them anywhere else. `-p 5432:5432` makes the port reachable from other machines on your network as well; on untrusted networks use `-p 127.0.0.1:5432:5432` instead. If the port is already taken, for example by a Homebrew PostgreSQL, stop that server or publish another host port (`-p 5433:5432`) and use that port below. The production major version is not chosen yet; it will be chosen with the hosting (ADR-0010).

Check that the server answers:

```sh
docker exec -it aicepeak-pg psql -U postgres -c 'select version();'
```

Expected: one row that starts with `PostgreSQL 17`. The backend reads the connection settings from environment variables; in development they come from a git-ignored `.env` file (see [Running Aicepeak locally](#running-aicepeak-locally)). Never commit connection strings or passwords.

Daily handling:

```sh
docker stop aicepeak-pg       # stop the server; data is kept
docker start aicepeak-pg      # start it again
docker logs aicepeak-pg       # server log, for example after a failed start
docker rm -f -v aicepeak-pg   # delete the container and its data volume for a fresh database
```

The container does not start on its own after a reboot or after Docker Desktop restarts; run `docker start aicepeak-pg`.

## Running Aicepeak locally

The backend (`backend/`, ASP.NET Core on .NET 10 with EF Core) and the frontend (`frontend/`, React with Vite) are described in the [architecture](architecture/AICEPEAK_ARCHITECTURE.md). Commands below run from the repository root unless a `cd` says otherwise.

**Tools, once:** the .NET 10 SDK from the [official download page](https://dotnet.microsoft.com/download/dotnet/10.0) (`global.json` requires a 10.0 SDK; a newer major SDK alone is not enough) and Node.js 22.22.2+, 24.15+ or 26+ (installed in step 2; the range is `engines` in `frontend/package.json`). Then restore the pinned EF Core tool:

```sh
dotnet tool restore
```

**Configuration.** The backend reads `DB_CON_STR` (connection string without credentials), `DB_USR` and `DB_PWD` from environment variables. In the `Development` environment it also reads `backend/.env`; real environment variables win. Create it from the example, which matches the `aicepeak-pg` container above:

```sh
cp backend/.env.example backend/.env
```

`.env` is git-ignored and never published; other environments set the variables directly. If a setting is missing or invalid the backend still starts, and its health endpoint reports the problem.

Sign-in additionally needs the `ENTRA_*` settings in `backend/.env` and the `VITE_ENTRA_*` settings in `frontend/.env` (`cp frontend/.env.example frontend/.env`); see [Microsoft Entra sign-in](#microsoft-entra-sign-in). Without them the backend still starts, but every protected API request answers `401`.

**Database.** Start Docker and the Postgres container and create or update the database schema with the EF Core migrations:

```sh
cd backend && ./start --migrate
```

`./start` alone only makes sure Docker and the container run. Without the script, start the container as described in [PostgreSQL for development](#postgresql-for-development) and run `cd backend && dotnet ef database update`.

After changing the EF model, add a migration with `dotnet ef migrations add <Name> --output-dir Data/Migrations` (from `backend/`).

**Dependencies and lock files.** The pipeline restores packages only from committed lock files, offline in the sandbox ([ADR-0011](decisions/0011-product-checks.md)). After adding or updating a NuGet package, run `dotnet restore backend/Aicepeak.slnx --force-evaluate` and commit the changed `packages.lock.json` files with it. npm packages come only from registry.npmjs.org through `frontend/package-lock.json`: git, file or URL dependencies are refused, a project `.npmrc` is not used, and install scripts never run.

**Development, two terminals:**

```sh
cd backend && dotnet watch     # API on http://localhost:5043 with C# hot reload (or dotnet run)
cd frontend && npm ci && npm run dev   # app with hot reload on http://localhost:5173
```

Open http://localhost:5173. Vite proxies `/api/*` to the backend. Without a session the app redirects to `/login`; after signing in with Microsoft it shows your user record (tenant ID, object ID and name) as JSON. The sign-out icon at the right of the menu bar returns to `/login`.

The backend health endpoint answers without sign-in: `curl -i http://localhost:5043/api/v1/health/alive` returns `204` when the database is reachable and `503` when it is not or the configuration is missing or invalid. In `Development`, the 503 body includes exception traces; in any other environment it only names the failing components.

**Checks:**

```sh
dotnet build backend/Aicepeak.slnx -warnaserror   # 0 warnings, 0 errors; also fails on formatting violations
dotnet format backend/Aicepeak.slnx               # fixes formatting (--verify-no-changes only checks)
dotnet test backend/Aicepeak.slnx                 # needs Docker: database tests start a throwaway postgres:17 container
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

**Code style.** The repository's [`.editorconfig`](../.editorconfig) defines the formatting: UTF-8, LF, final newline, two-space indentation (four for C# and Python) and Java-style braces in C# (`{` at the end of the line; `else`, `catch` and `finally` after `}`). Rider and Visual Studio read it directly; in VS Code install the C# Dev Kit and the EditorConfig extension. The .NET build enforces the C# formatting (`EnforceCodeStyleInBuild`, rule IDE0055), so run `dotnet format backend/Aicepeak.slnx` before committing. EF Core migrations are generated code and are not formatted. TypeScript already uses braces on the same line; the frontend has no formatter besides `.editorconfig`.

Without Docker, skip the database tests with `dotnet test backend/Aicepeak.slnx --filter "Category!=Database"`. `backend/` holds both the API project and the solution, so `dotnet build` and `dotnet test` need the solution file named; inside `backend/`, `dotnet run`, `dotnet watch` and `dotnet ef` use the API project.

**Production build:** `dotnet publish backend/Aicepeak.Api.csproj -c Release -o <dir>` also runs `npm ci` and `npm run build` in `frontend/` and copies `frontend/dist` into `<dir>/wwwroot`; the backend then serves the app at `/`. Add `-p:SkipFrontendBuild=true` to skip the frontend. Vite writes the `VITE_ENTRA_*` values into the build, so set them (environment or `frontend/.env`) before publishing.

## Microsoft Entra sign-in

Users sign in with Microsoft Entra ID (AIC-12). The browser signs in with MSAL React (authorization code flow with PKCE, full-page redirect) and asks only for `openid profile`; MSAL adds `offline_access` itself. It then gets an Entra v2 access token for the API and calls `PUT /api/v1/login`, which creates the user record on the first sign-in, keyed by tenant ID (`tid`) and object ID (`oid`). The backend validates every token itself: signature, `aud`, `iss` (`https://login.microsoftonline.com/{tid}/v2.0`), `ver` 2.0, `azp`, lifetime with 5 minutes of clock skew, the required scope for users or app role plus `idtyp=app` for apps, and the tenant allowlist. Personal Microsoft accounts are always rejected. Sign-out clears only the app's local session; the browser's Microsoft session stays, so the next sign-in may not ask for a password.

**App registration, once per environment.** In the [Microsoft Entra admin center](https://entra.microsoft.com), under **App registrations**, create one registration for the SPA and its API:

1. **Supported account types:** accounts in any organizational directory (multitenant). Which tenants may use Aicepeak is decided by the allowlist below, not by the registration.
2. **Authentication:** add the platform **Single-page application** with the redirect URIs `http://localhost:5173/login` and `https://<production host>/login`.
3. **Manifest:** set `requestedAccessTokenVersion` (under `api`) to `2`. Without it Entra issues v1 tokens, and the backend rejects every sign-in.
4. **Expose an API:** keep the Application ID URI `api://<client-id>` and add the scope `access_as_user` (who can consent: admins and users).
5. **API permissions:** add **My APIs** › this registration › `access_as_user`.
6. **App roles** (only for services that call the API without a user): add a role with allowed member type **Applications**, e.g. `Api.Access`.
7. **Token configuration:** add the optional claim `idtyp` to the access token.
8. **Consent:** an admin of every allowed tenant grants admin consent once: in the home tenant with **API permissions** › **Grant admin consent**, in other tenants by opening `https://login.microsoftonline.com/<tenant-id>/adminconsent?client_id=<client-id>`. Without consent the app cannot get the API token after sign-in, and the sign-in page shows an error.

A separate registration for the API also works: then `ENTRA_AUDIENCE` is the API's client ID, `ENTRA_CLIENT_IDS` lists the SPA's client ID, and `VITE_ENTRA_API_SCOPE` names the API's scope.

**Backend settings** (`backend/.env` in Development, environment variables elsewhere):

| Setting | Value |
| --- | --- |
| `ENTRA_AUDIENCE` | The client ID (GUID) of the registration that exposes the API; v2 tokens carry it as `aud` |
| `ENTRA_CLIENT_IDS` | Comma-separated client IDs allowed to call the API (`azp`): the SPA, plus any service apps |
| `ENTRA_SCOPE` | The required delegated scope, `access_as_user` |
| `ENTRA_APP_ROLE` | The app role required from service apps, e.g. `Api.Access` |
| `ENTRA_METADATA_ADDRESS` | Optional; defaults to `https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration`. Must be `https` |

**Frontend settings** (`frontend/.env`, from `frontend/.env.example`):

| Setting | Value |
| --- | --- |
| `VITE_ENTRA_CLIENT_ID` | The SPA's client ID |
| `VITE_ENTRA_API_SCOPE` | The full scope, `api://<client-id>/access_as_user`; a bare scope name would be read as a Microsoft Graph scope |

**Tenant allowlist.** The table `allowed_tenants` (column `tid`) lists the tenant IDs whose users may sign in; the migration seeds `db760528-cb7c-455c-bd41-e50a38f6fd62`. Tokens from any other tenant get `401`. To allow another tenant in the local database:

```sh
docker exec -it aicepeak-pg psql -U postgres -d aicepeak -c "INSERT INTO allowed_tenants (tid) VALUES ('<tenant-id>');"
```

The backend tests never contact Microsoft: they sign tokens with a key generated at test time and serve the OIDC metadata from a local stub.

## Docker

Docker Desktop is needed for isolated author runs (step 2) and for local development services such as [PostgreSQL](#postgresql-for-development). A reviewer-only device does not need it for reviews, but `factory doctor` still checks it.

1. **Choose the installer.** Run `uname -m`: `arm64` means Apple silicon, `x86_64` means an Intel Mac. Download the matching Docker Desktop installer from the [official Mac install page](https://docs.docker.com/desktop/setup/install/mac-install/), which also lists the supported macOS versions.
2. **Install.** Open `Docker.dmg` and drag Docker to Applications. The page above also describes a command-line install with `installer` if you need one.
3. **First launch.** Open Docker from Applications, accept the [Docker Subscription Service Agreement](https://www.docker.com/legal/docker-subscription-service-agreement/) and use the recommended settings; macOS asks for your password once. Sign-in to a Docker account is optional. Docker Desktop is free for small businesses (fewer than 250 employees and less than USD 10 million annual revenue), personal use and education; larger organisations need a paid subscription.
4. **Check it.** In a new Terminal:

   ```sh
   docker --version
   docker info
   docker run --rm hello-world
   ```

   Expected: a version, server details from `docker info` without an error, and the `Hello from Docker!` message.

Under **Settings › General** you can turn on "Start Docker Desktop when you sign in to your computer" so that author runs and the PostgreSQL container are available after a reboot. Docker Desktop's resource saver pauses it when idle; `factory` and `factory doctor` start a stopped Docker Desktop and wake it themselves. If you change the allocated CPU or memory (**Settings › Resources**), leave enough for the factory image build in step 4. For the `docker-credential-desktop` error during the image build, see step 4.
