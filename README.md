# Aicepeak software factory

Shared factory for Codex and Claude Code in `Zerosteps1/Aicepeak_V2.0.0`: isolated authors, deterministic checks, an independent senior review and a human merge. The only central reviewer is **`gpt-6-astra` with effort `high`**. It runs on the maintainer's trusted Mac under a ChatGPT Business access token, not on GitHub-hosted runners, and no part of the factory uses `OPENAI_API_KEY`. Its configuration is in place; real operation has not yet been demonstrated.

**Status 2026-10-28:** the factory is on `main` but not activated. GitHub Apps, rulesets, the environment branch policy, secrets, a reachable Docker daemon and real smoke runs are still missing. `AICEPEAK_NORDSTERN.md` is in the repository but not configured or approved (`northstar_path: null`), so product development stays blocked while factory setup remains allowed. No product architecture is anticipated.

## Entry in a fresh checkout

Check out the reviewed revision. Required: Python >= 3.11, Git, GitHub CLI and Docker; the check tools are versioned in `factory/tools.lock.json`.

```sh
git clone git@github.com:Zerosteps1/Aicepeak_V2.0.0.git
cd Aicepeak_V2.0.0
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py check --root .
docker build -f factory/Dockerfile \
  -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
python3 tools/factory/verify.py --root .
```

The doctor reads local prerequisites, GitHub CLI authentication and the reviewer host (pinned `codex-cli 0.164.0`, access token and publisher key). It reports secret presence only, never values. Exit code 2 means open prerequisites or pending live acceptance; local presence is no proof of operation. `--runner` (default `claude`) selects which launcher key it looks for: `claude` checks `ANTHROPIC_API_KEY` for local launches, `codex` checks `OPENAI_API_KEY` for the optional API-billed Codex launcher. It also reports whether the Workload Identity Federation IDs for the pipeline author are configured. `smoke` checks the container boundary, an unmounted test file, the CLI versions and native discovery; authenticated model and MCP execution is a separate live acceptance. `verify.py` needs `actionlint` and `gitleaks` in the PATH; `--structure-only` does not replace the full check. Both tools are included in the image. On Linux, `python3 factory/install_tools.py --lock factory/tools.lock.json --destination /tmp/aicepeak-factory-tools` installs the verified binaries; then add that directory to the PATH. Other hosts need the matching official binaries of the same versions.

Supply author credentials only through the launcher environment's secret facility: locally `ANTHROPIC_API_KEY` and `CONTEXT7_API_KEY` for the Claude author. In the GitHub pipeline the author uses Workload Identity Federation instead of a stored key. Claude is configured as `claude-sonnet-5-5` with documented price assumptions; real API access still has to be verified. `OPENAI_API_KEY` is needed only for the optional, API-billed `--runner codex` launcher; the factory pipeline and the senior reviewer never use it. Set `FACTORY_DOCKER_HOST` for a non-default Docker endpoint.

```sh
python3 tools/factory/clients.py launch --root . --runner claude
# Optional and API-billed: --runner codex (needs OPENAI_API_KEY)
```

**Do not start with a plain `codex` call.** `FACTORY_PROXY_TOKEN` is created automatically inside the isolated launcher; it is not a personal key to enter. The MCPs need the broker started alongside the worker. Details and failure causes are in [Clients](factory/clients.md).

In the fresh client start with `factory-start` and name the versioned work order. `factory-change` implements, `factory-review` checks locally, `factory-fix-review` handles feedback. The launcher returns a patch and does not modify the original checkout. More details: [Clients](factory/clients.md), [Contributing](CONTRIBUTING.md), [Policy](factory/policy.md).

## Senior review on the maintainer's Mac

The GitHub pipeline runs snapshot, deterministic tests and publication. It then leaves `factory/senior-review` in progress ("Awaiting senior review") with an authenticated receipt of the snapshot and test evidence. The maintainer reviews that exact snapshot locally:

```sh
python3 tools/factory/local_review.py --smoke            # access token, model and tool-less session, no GitHub
python3 tools/factory/local_review.py --pr 123 --dry-run # review and print, publish nothing
python3 tools/factory/local_review.py --pr 123           # review and publish through the publisher App
```

Run it from a clean checkout of the policy revision recorded in the pending check (the default-branch commit that ran the pipeline); otherwise the script stops and names the commit to switch to. `--no-dispatch` never starts a correction run, even when automatic correction is enabled. `--dry-run` still reads GitHub through the publisher App and uses the Codex seat window. At most `limits.max_reviews_per_pr` published reviews are allowed per PR. How the session is isolated is described in [Clients](factory/clients.md#senior-reviewer-maintainer-local).

Credentials live only in the login keychain of that Mac, never in a file, the repository or a GitHub secret:

- `aicepeak-factory-codex-access-token`: a ChatGPT Business access token created at [chatgpt.com/admin/access-tokens](https://chatgpt.com/admin/access-tokens) with the Codex scope and a short validity window. Store it with `security add-generic-password -a "$USER" -s aicepeak-factory-codex-access-token -w` (the trailing `-w` prompts for the value, so it stays out of the shell history).
- `aicepeak-factory-publisher-key`: the publisher App's private key PEM, stored base64-encoded because `security` prints multi-line values as hex: `security add-generic-password -a "$USER" -s aicepeak-factory-publisher-key -w "$(base64 -i key.pem)"`. Delete `key.pem` afterwards.

Environment variables `CODEX_ACCESS_TOKEN` and `FACTORY_PUBLISHER_APP_PRIVATE_KEY` take precedence over the keychain; do not export them in shell profiles. To rotate the expiring token: create a replacement, update the item with `security add-generic-password -U ...`, run `--smoke`, then revoke the old token. GitHub-hosted runners never receive the Codex token: OpenAI intends access tokens for trusted machines and private runners, and the runners of this public repository are neither. [Access tokens](https://learn.chatgpt.com/docs/enterprise/access-tokens)

## Shadow phase

Until the senior review has proven precise on 10-20 real PRs:

- `required_checks` in `factory/config.json` and `factory/github-settings.json` is only `factory/deterministic`. `settings.py` accepts exactly this set or both factory checks.
- `factory/senior-review` is still published, and its PR comment is marked advisory.
- `automatic_correction` is `false`. A review that requests changes labels the PR `needs-author-action`; the author fixes it in the working session with `factory-fix-review`. The Correction gate refuses dispatched corrections.

A reviewed PR ends the shadow phase by adding `factory/senior-review` to both `required_checks` lists, followed by `settings.py apply`. Automatic correction is enabled later in a separate reviewed PR.

## One-time activation by the repository owner

The bootstrap of the empty remote is complete: the factory reached `main` with PR #1 on 2026-10-28. Humans review and merge every PR; no agent pushes to `main` or merges.

1. Authenticate to GitHub as Gabriel (`Zerosteps1`, ID `115100163`) and prove administration. [GitHub access](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
2. Add Felix as the second verified maintainer before `settings.py apply`: verify Felix's actual account login, numeric ID and permission, add the entry to `maintainers` in `factory/config.json` and regenerate CODEOWNERS. A PR Gabriel opens needs another authorized human reviewer because GitHub forbids self-approval; do not loosen the protection rules for that.
3. [Register two GitHub Apps](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) and install them only in the target repository. The exact permission split is in `factory/github-settings.json`: the publisher publishes checks and feedback, the writer writes correction branches. Enter the real IDs; no App gets a bypass. `python3 tools/factory/settings.py codeowners` verifies the human identities and writes CODEOWNERS. Commit both changes through a reviewed PR. [Setup and API checks](factory/github.md).
4. For the settings checks, provide short-lived `FACTORY_PUBLISHER_APP_JWT` and `FACTORY_WRITER_APP_JWT`.
5. Review `settings.py inspect`, then `settings.py diff`, and run `settings.py apply` deliberately. This installs two active rulesets (required checks without bypass, and default-branch updates only through human PR merges), keeps CODEOWNER approval and publisher-bound checks mandatory, and restricts the credential environment `factory-control` to the default branch. During the shadow phase the only required check is `factory/deterministic`.
6. Only after `apply` and a fresh `inspect` that shows the environment limited to the default branch, add the environment secrets `FACTORY_PUBLISHER_APP_PRIVATE_KEY` and `FACTORY_WRITER_APP_PRIVATE_KEY`. The environment was created by an earlier failed run without a branch policy; a secret stored before the policy would be readable by workflows on any branch. `CONTEXT7_API_KEY` is needed only for automatic correction. No `OPENAI_API_KEY`, no `ANTHROPIC_API_KEY` and no Codex token. Never store any of these as a repository secret or file. [Context7 access](https://context7.com/docs/resources/all-clients). Run `inspect` again; an empty diff and present secret names do not yet prove a working run.
7. On the reviewer Mac, create both keychain items and run `local_review.py --smoke`.
8. In the Claude Console organisation linked to the Team plan (the link has a 7-day waiting period), create the GitHub Actions workload under Workload identity with the rule values in [GitHub](factory/github.md), and record its IDs in `factory/config.json` `anthropic_federation` through a reviewed PR. The first author run must show a successful exchange in the Console's authentication history and appear as plan credit usage.
9. Run the image/client smoke, the authenticated model/MCP run and the [smoke PR](docs/work/FACTORY-SMOKE.md) with the deterministic gate enforced, the review advisory and no author automation. Record run and check IDs, head/base SHAs, the real correction and the new review. Release operation only then.

## Orientation

| Path | Content |
|---|---|
| `AGENTS.md`, `factory/policy.md`, `factory/config.json` | Binding limits, model, budgets and identities |
| `.agents/skills/`, `.agents/roles.json` | Shared sources of the four skills and roles |
| `.codex/`, `.claude/`, `CLAUDE.md`, `.mcp.json` | Native client adapters generated from them |
| `.github/workflows/`, `tools/factory/` | Dispatcher, checks, publication, bounded correction and settings |
| `tools/factory/local_review.py` | Maintainer-local senior review |
| `factory/review.schema.json`, `factory/github-settings.json` | Review contract and desired GitHub enforcement |
| `docs/work/` | Versioned work orders and acceptance criteria |

The only sources are this repository, the approved work order and public vendor documentation. Earlier projects, Workbrain, private chats, notes and personal agent configuration are excluded.
