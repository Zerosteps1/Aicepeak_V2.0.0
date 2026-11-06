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

Expected: Python **3.11 or newer** and exactly **`codex-cli 0.164.0`**. The `factory` command puts this pinned Codex directory in front of the `PATH` of its helper processes itself; reapply the `export PATH` line only in Terminals where you run `session.py` or `local_review.py` by hand. This separate installation does not replace a personal Codex installation. If the access-token UI requires a newer CLI, stop and request a reviewed factory version update; do not silently upgrade the pinned reviewer.

For isolated author runs, install and start [Docker Desktop for your Mac's processor](https://docs.docker.com/desktop/setup/install/mac-install/), complete its first-launch setup and check `docker info`. Claude Code is installed inside the factory image; no host Claude installation is required.

Sign in to GitHub and check your access:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh api user --jq .login
gh api repos/Zerosteps1/Aicepeak_V2.0.0 --jq '.permissions.push'
```

Expected: your active maintainer login and `true`; a public clone alone does not prove write access. The [GitHub browser login](https://cli.github.com/manual/gh_auth_login) handles authentication without pasting a GitHub token into the factory.

### Install the factory command

The installer creates your two checkouts and the global `factory` command ([details](factory-cli.md#install)). The relative paths are resolved from your current directory: run it from a folder whose parent should hold both checkouts, for example from an existing clone in `~/repos/`.

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../aicepeak-control-checkout && ../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh
```

The installer takes the initial configuration from the production branch GitHub protects (today `production`; with several it asks, or takes `--config-branch NAME`; before `settings.py apply` it falls back to the GitHub default branch `testing`), reads the config branch there, follows a finished config branch change once (it then prints a `note: … following it`), verifies itself against the config branch's copy and puts the control checkout on the config branch; `--branch <listed branch>` chooses another listed branch, which you can change later with `factory use branch`. It asks for the Git `user.name` and `user.email` for commits in the candidate if they are not set there (use your own name and verified GitHub email), and offers to store the author keys (step 4; answer no on a reviewer-only device). Then open a new Terminal if it added a PATH block to `~/.zshrc`. The device configuration `~/.config/aicepeak-factory/cli.json` records both paths and the control branch.

- **Control checkout** (`aicepeak-control-checkout`): trusted CLI code on its control branch, by default the config branch. `factory` verifies and fast-forwards it before every command; every rule and work order comes from the config branch tip. Never make changes in it: `factory` and the factory tools refuse to run if it differs from its branch by even one file, including ignored files such as `.DS_Store`, `__pycache__` or `.venv` ([why](software-factory.md#the-control-checkout)). Keep it out of Finder and your editor's workspace, and store patches, reports, PR descriptions and credentials outside all checkouts.
- **Candidate checkout** (`aicepeak-candidate`): the only place where you edit, apply, commit and push. `factory` creates a branch per task in it ([way of working](way-of-working.md#daily-use-step-by-step)).

If you already have older clones (for example `Aicepeak-factory` and `Aicepeak-candidate`), the installer reuses them. It runs only when its own copy is byte-identical to the one on the config branch, so first bring the control clone to the config branch (with no local changes): `git -C ../Aicepeak-factory fetch origin` and `git -C ../Aicepeak-factory switch production`. Then run `../Aicepeak-factory/tools/factory/cli/install-factory-cli.sh --control-dir ../Aicepeak-factory --candidate-dir ../Aicepeak-candidate`. Do not pull or switch over somebody's uncommitted work.

**Devices installed before the branch model.** A control checkout on `main` (factory 0.1.x) stops working once the repository owner renames `main` to `testing` ([ADR-0008 runbook](decisions/0008-branch-model.md#owner-runbook-after-the-merge)). Reinstall it the same way: `git -C ../aicepeak-control-checkout fetch origin`, `git -C ../aicepeak-control-checkout switch production`, then `../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh` with your earlier options. `factory --version` then prints `factory 0.2.0`.

### Check the tools

```sh
factory doctor
```

`factory doctor` prints `ok` or `FAIL` with the fix for each of its own checks (shim, checkouts, author keys, Docker, image, pinned Codex, `gh` maintainer login; it waits up to 2 minutes for Docker Desktop to start or wake up) and then summarises `doctor.py` from a disposable checkout of the config branch tip, including the native adapter check and the branch model: each blocked check of `doctor.py` on its own line with its fix. **`doctor.py` exit 2 is expected:** it always leaves live acceptance open and, at this stage, keys/image may also be missing. It sees only exported author keys, not keychain items, so `factory doctor` marks its two key checks as `expected` when the keychain holds the keys; its Docker checks use `FACTORY_DOCKER_HOST` only when exported. It also checks Docker, author keys and local verifier tools on reviewer-only devices. Read each named check instead of treating a blocked check as a failed installation. `actionlint` and `gitleaks` are only needed for full local verification. When they are missing, `factory doctor` prints one command that installs them: `factory/install_tools.py` downloads the exact releases pinned in `factory/tools.lock.json`, checks their SHA-256 and puts them next to the `factory` command (Linux and macOS; the factory image uses the same installer).

### Test changes in the sandbox

Test changes to the factory the way the pipeline does, in the author image (Docker running), with a read-only root filesystem, no network and a throwaway copy of your working tree, uncommitted changes included:

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

Expected: image build succeeds and container smoke reports `passed`. If `docker-credential-desktop` cannot be found, add the actual Docker app's `Contents/Resources/bin` directory to this Terminal's `PATH`, then repeat the build; keep credential-store settings intact. The Docker app's name can differ between Macs (for example `Docker 2.app`); use your own installation path.

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

Create a harmless smoke PR under the already approved [FACTORY-SMOKE](work/FACTORY-SMOKE.md). Coordinate with the other maintainers so **only your device watches this first smoke**; otherwise another device can win the review claim and two green checks would not test your key. Work in your candidate checkout. The branch name `<login>/FACTORY-SMOKE-<k>` ties it to the work order. The fixture change alters indentation only, leaving all numeric and text values correct:

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

`origin/testing` is the validation branch that `smoke` work orders are routed to (see the [branch diagram](factory-branches.md)). `factory submit --finished` commits the staged file, pushes the branch, then runs `session.py submit`: advisory preflight, PR into `testing`, and its watcher. If `testing` moved meanwhile, merge the new `origin/testing` into the candidate branch (`git merge origin/testing`), commit any resolution, push it with `factory submit`, then retry; do not bypass freshness checks or use `/bypass`. If you resume an existing PR, use `factory watch <number>`. Keep the Mac awake. Confirm both `factory/deterministic` and `factory/senior-review` from App **5510081** are successful for that PR's current head, the current `testing` tip and the current config branch policy (see [merge rules](way-of-working.md#merge-rules)). The watcher can keep polling after success; Ctrl-C stops it once both final checks are green. This is the publication test for your publisher key; a successful model smoke alone is insufficient. Record the head/base, run/check IDs and your executed probes in a reviewed evidence update ([factory/evidence.md](../factory/evidence.md)). Until then, your device remains unverified; already verified reviewer devices may review shared PRs.

Also inspect the final senior check receipt (`output.text` JSON) and confirm `claim.actor.login` is your active account. If another maintainer won the claim, this run is not acceptance of your device: coordinate again and create a fresh smoke PR or deliberate retry. The smoke fixture needs no merge. Product implementation still requires architecture decisions, implemented product checks and an approved product work order; the north-star approval alone does not remove that gate.
