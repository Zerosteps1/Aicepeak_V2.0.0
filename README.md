# Aicepeak

This repository holds two things: the product north star for Aicepeak ([AICEPEAK_NORDSTERN.md](AICEPEAK_NORDSTERN.md), German, unchanged) and the **AI software factory** that builds the product. The factory turns an approved work order into a reviewed pull request. An isolated AI author writes the change, deterministic tests and an independent GPT-6 Astra reviewer check it, a bounded automatic correction loop fixes blocking findings, and a human decides the merge.

Only this repository, its work orders and review evidence, and official vendor documentation are project sources. Old projects, private chats, Workbrain content and personal agent memories are not.

## Status on 2026-10-29

| Area | State |
|---|---|
| Factory | Installed on `main`; rulesets, environment secrets and both Apps verified active. The review-fix loop passed live on PR #20 and again on PR #13 (2026-10-29: Astra finding F-006, automatic Claude correction, re-review `pass`). Ready for factory and documentation work. |
| Full operational acceptance | Open: a second maintainer's own reviewer device, two devices racing for one claim, a new head during a running review, a foreign App with the same check name, authenticated skill/MCP calls inside the author container. See [evidence](factory/evidence.md). |
| Product development | North star approved by the repository owner on 2026-10-29 ([decision](docs/decisions/0006-northstar-approval.md)); architecture decisions and implemented product checks remain open. `northstar_approved: true`, `product_checks_ready: false`: only `factory` and `smoke` work orders run. |
| Architecture | Non-binding draft proposal v0.4 (merged with PR #13): [specification sheet and target architecture](docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md). Its AD-01..AD-12 bind only after adoption through decision records. |

The start-readiness review with measured times, friction and recommendations is in [factory/review-2026-10-29.md](factory/review-2026-10-29.md).

## Development

All development runs through the software factory. This section gives the overview and the most common commands; run them from your control checkout (a clean clone on current `main`, see [way of working](docs/way-of-working.md)). The full details are in three documents:

| Document | Content |
|---|---|
| [docs/software-factory.md](docs/software-factory.md) | What the factory is, its pipeline, roles, limits and costs |
| [docs/way-of-working.md](docs/way-of-working.md) | Daily use: from work order to merge, stopping and cancelling, parallel PRs, merge rules |
| [docs/dev-setup.md](docs/dev-setup.md) | One-time macOS device setup for reviewer and author devices |

### The software factory

The software factory is the set of tools, rules and GitHub automation in this repository that turns an approved **work order** (a task description in `docs/work/`) into a reviewed pull request. In short:

1. A maintainer merges a work order with goal, acceptance criteria and allowed paths.
2. Claude Code implements it as an **isolated author** in a disposable container without personal configuration or credentials, and returns a patch.
3. The maintainer applies the patch on a branch and submits it with `session.py submit`, which opens the PR.
4. **Deterministic tests** run in GitHub Actions without secrets or network.
5. **GPT-6 Astra** reviews the PR on a maintainer's device. Blocking findings start a bounded **automatic correction**.
6. With both required checks green, a **maintainer merges** with `session.py merge`, one PR at a time. Agents and bots never push to `main` or merge.

How each step works is in [docs/software-factory.md](docs/software-factory.md). How you take part in each step is in [docs/way-of-working.md](docs/way-of-working.md).

### Set up your device

Every maintainer device needs GitHub access, the pinned Codex CLI, a personal ChatGPT workspace access token and its own publisher App key in the macOS keychain. With those it can run the senior review. A device that also runs isolated author sessions additionally needs Docker Desktop, the factory image and Anthropic and Context7 API keys. A new device counts as verified only after its first real smoke review. Step-by-step instructions are in [docs/dev-setup.md](docs/dev-setup.md).

### Define a new task

A task is a **work order** in `docs/work/<TASK-ID>.md`. It is created in two steps:

1. **Generate:** the `factory-start` skill drafts it from [docs/work/TEMPLATE.md](docs/work/TEMPLATE.md) with goal, non-goals, acceptance criteria and the exact `allowed_paths`. You review and correct the draft; its status stays `draft`.
2. **Activate:** set `"status":"approved"` in its `factory-task` block and merge it in a PR of its own. Only a merged, approved work order can be implemented, because the factory reads tasks only from protected `main`.

Details: [way of working, steps 1–2](docs/way-of-working.md#daily-use-step-by-step).

### Start a new task

From a clean control checkout on current `main`, launch the [isolated author](docs/software-factory.md#the-isolated-author-session) and ask it to use the `factory-change` skill for your work order:

```sh
python3 tools/factory/clients.py launch --root . --runner claude
```

Apply the returned patch on a feature branch in a separate candidate checkout, push it, check for collisions and submit:

```sh
python3 tools/factory/session.py collisions --candidate /path/to/candidate --task docs/work/TASK.md
python3 tools/factory/session.py submit --candidate /path/to/candidate \
  --task docs/work/TASK.md --runner claude \
  --title 'Concrete change' --body-file /path/to/pr-body.md
```

Details: [way of working, steps 3–5](docs/way-of-working.md#daily-use-step-by-step).

### Stop or cancel a task

- **Author session:** exit the client. Nothing reaches GitHub until you push a patch yourself.
- **Watcher or review:** press Ctrl-C. The PR waits until a device watches again.
- **Pause a PR:** convert it to draft with `gh pr ready <n> --undo`.
- **Cancel a PR:** close it with a reason: `gh pr close <n> --comment '<reason>'`.
- **Withdraw a work order:** change its `status` from `approved` in a PR of its own. Every PR that references it is then blocked.

Details and side effects: [way of working, stop or cancel a task](docs/way-of-working.md#stop-or-cancel-a-task).

### Other interactions

| Action | Command or place | Details |
|---|---|---|
| Run the binding review for a PR | `python3 tools/factory/session.py watch --pr <n>` | [Review](docs/way-of-working.md#review-all-waiting-prs) |
| Give feedback | Ordinary PR comments, reviews and inline comments; each starts a fresh review | [Step 8](docs/way-of-working.md#daily-use-step-by-step) |
| Ask a question about a PR | `python3 tools/factory/session.py response --pr <n> --question '…' --post` | [Step 8](docs/way-of-working.md#daily-use-step-by-step) |
| Fix findings marked `needs-author-action` | Launch the author with the `factory-fix-review` skill | [Fix findings](docs/way-of-working.md#fix-findings-yourself) |
| Merge | `python3 tools/factory/session.py merge --pr <n>` (`--dry-run` for the verdict only) | [Merge rules](docs/way-of-working.md#merge-rules) |
| Restart a stuck run | `gh workflow run factory.yml --ref main -f pr=<n> -f retry=true` | [Restart](docs/way-of-working.md#restart-a-stuck-run) |
| Work on several PRs at once | Collision sweep, then merge one PR at a time | [Working in parallel](docs/way-of-working.md#working-in-parallel) |
| Check your device | `python3 tools/factory/doctor.py --root . --runner claude` | [Device setup](docs/dev-setup.md#check-the-tools) |
| Verify the repository locally | `python3 tools/factory/verify.py --root .` | [Verify locally](docs/way-of-working.md#verify-locally) |

## Repository map

| Path | Content |
|---|---|
| [AICEPEAK_NORDSTERN.md](AICEPEAK_NORDSTERN.md) | Canonical product goal (German); never copied |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Shared agent rules and the contribution flow |
| [docs/software-factory.md](docs/software-factory.md), [docs/way-of-working.md](docs/way-of-working.md), [docs/dev-setup.md](docs/dev-setup.md) | Factory description, daily use and device setup |
| [factory/policy.md](factory/policy.md), [factory/config.json](factory/config.json) | Binding policy, models, maintainers, limits, protected paths |
| [factory/evidence.md](factory/evidence.md), [factory/review-2026-10-29.md](factory/review-2026-10-29.md) | Real verification evidence and the start-readiness review |
| [factory/github.md](factory/github.md), [factory/clients.md](factory/clients.md) | GitHub operation, rulesets, isolated clients and the local reviewer |
| `.agents/`, `.claude/`, `.codex/` | Canonical skills and roles; generated native adapters (`clients.py sync`, checked by `clients.py check`) |
| `.github/` | Trusted pipeline, dispatcher, feedback ingress, CODEOWNERS, templates |
| `tools/factory/` | Factory tools and their regression tests |
| [docs/work/](docs/work/TEMPLATE.md) | Approved work orders |
| [docs/decisions/](docs/decisions/0005-maintainer-local-senior-review.md) | Decision records |
| [docs/architecture/](docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md) | Non-binding architecture proposal and its validation |
