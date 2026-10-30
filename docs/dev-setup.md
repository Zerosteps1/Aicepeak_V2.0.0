# Development setup (macOS)

One-time setup of a maintainer device for the [software factory](software-factory.md). After it, follow [way-of-working.md](way-of-working.md) for daily use.

A device can take two roles:

- **Reviewer device:** runs the binding senior review (`session.py watch`). Needs steps 1–3 and 5.
- **Author device:** additionally runs isolated author sessions (`clients.py launch`). Needs steps 1–5.

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

Expected: Python **3.11 or newer** and exactly **`codex-cli 0.164.0`**. Reapply the `export PATH` line in each Terminal used for factory commands. This separate installation does not replace a personal Codex installation. If the access-token UI requires a newer CLI, stop and request a reviewed factory version update; do not silently upgrade the pinned reviewer.

For isolated author sessions, install and start [Docker Desktop for your Mac's processor](https://docs.docker.com/desktop/setup/install/mac-install/), complete its first-launch setup and check `docker info`. Claude Code is installed inside the factory image; no host Claude installation is required.

Sign in to GitHub and check your access:

```sh
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
gh api user --jq .login
gh api repos/Zerosteps1/Aicepeak_V2.0.0 --jq '.permissions.push'
```

Expected: your active maintainer login and `true`; a public clone alone does not prove write access. The [GitHub browser login](https://cli.github.com/manual/gh_auth_login) handles authentication without pasting a GitHub token into the factory.

### Create the control checkout

> **This creates your control checkout `Aicepeak-factory`.** Run every factory command from this folder, and never make changes in it: the tools refuse to run if it differs from current `main` ([why](software-factory.md#the-control-checkout)). Changes go into the separate candidate checkout, created [below](#create-the-candidate-checkout).

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git Aicepeak-factory
cd Aicepeak-factory
git switch main
```

Store patches, reports, PR descriptions and credentials outside all checkouts. `session.py` rejects ignored extra files too (including `.DS_Store`, `__pycache__` or `.venv`). Before use, inspect `git status --short --untracked-files=all --ignored`; do not pull or switch over somebody's uncommitted work.

### Create the candidate checkout

> **This creates your candidate checkout `Aicepeak-candidate`, next to the control checkout.** This is the only place where you apply, commit and push changes. For each task you create a new branch in it ([way of working, step 4](way-of-working.md#daily-use-step-by-step)). Never run factory commands from here.

Run from the control checkout, and replace the Git author placeholders with your own name and verified GitHub email:

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../Aicepeak-candidate
git -C ../Aicepeak-candidate config --local user.name 'YOUR NAME'
git -C ../Aicepeak-candidate config --local user.email 'YOUR VERIFIED GITHUB EMAIL'
```

### Check the tools

From the control checkout:

```sh
python3 tools/factory/clients.py check --root .
python3 tools/factory/doctor.py --root . --runner claude
```

Adapter `check` must pass. **Doctor exit 2 is expected:** it always leaves live acceptance open and, at this stage, keys/image may also be missing. It also checks Docker, author keys and local verifier tools on reviewer-only devices. Read each named check instead of treating exit 2 as a failed installation. `actionlint` and `gitleaks` are only needed for full local verification; the Linux-only `factory/install_tools.py` is not a macOS installer.

## 3. Configure and test the reviewer

In the correct Business workspace, open [Access tokens](https://chatgpt.com/admin/access-tokens), create a token for your device with **Codex** scope and a finite expiration, and copy it once. This is a personal workspace access token, not a browser session token or a Platform API key. Store it using the password prompt; `-U` also supports rotation:

```sh
security add-generic-password -U -a "$USER" -s aicepeak-factory-codex-access-token -w
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

Create or obtain an API key for the agreed [Anthropic Console](https://platform.claude.com/) workspace and an API key from the [Context7 dashboard](https://context7.com/dashboard). Enter them at hidden prompts in your own **zsh** Terminal; these lines contain no secret values in shell history:

```sh
read -rs "ANTHROPIC_API_KEY?Anthropic API key: "
printf '\n'
read -rs "CONTEXT7_API_KEY?Context7 API key: "
printf '\n'
export ANTHROPIC_API_KEY CONTEXT7_API_KEY
export FACTORY_DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
docker build -f factory/Dockerfile -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
```

Expected: image build succeeds and container smoke reports `passed`. If `docker-credential-desktop` cannot be found, add the actual Docker app's `Contents/Resources/bin` directory to this Terminal's `PATH`, then repeat the build; keep credential-store settings intact. The Docker app's name can differ between Macs (for example `Docker 2.app`); use your own installation path.

The container smoke does **not** prove authenticated skill or native MCP execution. From the control checkout, run `python3 tools/factory/clients.py launch --root . --runner claude` and request: “Use factory-start for docs/work/FACTORY-SMOKE.md. Read the approved order, make a generic Context7 documentation lookup and an OpenAI Docs lookup, and report both outcomes without changing files.” Verify actual tool outcomes in that interactive session. This consumes Anthropic API usage; the local launcher needs the two keys even though Actions uses WIF. After the session, remove the author keys from this Terminal with `unset ANTHROPIC_API_KEY CONTEXT7_API_KEY`.

## 5. Complete the first real review on a new device

Repeat the doctor and inspect relevant checks. A reviewer needs the correct clean checkout, GitHub identity/access, pinned Codex, personal-token smoke and publisher key. An author additionally needs Docker/image, both API keys, boundary smoke and the authenticated skill/MCP probe. Doctor exit 2 still does not certify live acceptance.

Create a harmless smoke PR under the already approved [FACTORY-SMOKE](work/FACTORY-SMOKE.md). Coordinate with the other maintainers so **only your device watches this first smoke**; otherwise another device can win the review claim and two green checks would not test your key. The following runs from the control checkout and makes the change in your candidate checkout. The fixture change alters indentation only, leaving all numeric and text values correct:

```sh
git pull --ff-only
cd ../Aicepeak-candidate
git fetch origin
git switch -c "smoke/device-$(date +%Y%m%d-%H%M%S)" origin/main
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
git commit -m 'test(factory): verify reviewer device with unchanged smoke values'
git push -u origin HEAD
cd ../Aicepeak-factory
printf '%s\n' 'Verify a new reviewer device using the approved FACTORY-SMOKE fixture; formatting only.' > ../device-smoke-pr.md
python3 tools/factory/session.py submit --candidate ../Aicepeak-candidate \
  --task docs/work/FACTORY-SMOKE.md --runner claude \
  --title 'test(factory): reviewer device smoke' --body-file ../device-smoke-pr.md
```

`submit` starts an advisory preflight, opens the PR and runs its watcher. If `main` moved meanwhile, update the clean control checkout and merge the new `origin/main` into the candidate, commit any resolution, push, then retry; do not bypass freshness checks. If you resume an existing PR, use `python3 tools/factory/session.py watch --pr <number>` from the updated control checkout. Keep the Mac awake. Confirm both `factory/deterministic` and `factory/senior-review` from App **5510081** are successful for that PR's current head and current `main` policy (see [merge rules](way-of-working.md#merge-rules)). The watcher can keep polling after success; Ctrl-C stops it once both final checks are green. This is the publication test for your publisher key; a successful model smoke alone is insufficient. Record the head/base, run/check IDs and your executed probes in a reviewed evidence update ([factory/evidence.md](../factory/evidence.md)). Until then, your device remains unverified; already verified reviewer devices may review shared PRs.

Also inspect the final senior check receipt (`output.text` JSON) and confirm `claim.actor.login` is your active account. If another maintainer won the claim, this run is not acceptance of your device: coordinate again and create a fresh smoke PR or deliberate retry. The smoke fixture needs no merge. Product implementation still requires architecture decisions, implemented product checks and an approved product work order; the north-star approval alone does not remove that gate.
