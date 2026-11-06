# Aicepeak

This repository holds two things: the product north star for Aicepeak ([AICEPEAK_NORDSTERN.md](AICEPEAK_NORDSTERN.md), German, unchanged) and the **AI software factory** that builds the product. The factory turns an approved work order into a reviewed pull request. An isolated AI author writes the change, deterministic tests and an independent GPT-6 Astra reviewer check it, a bounded automatic correction loop fixes blocking findings, and a human decides the merge.

Only this repository, its work orders and review evidence, and official vendor documentation are project sources. Old projects, private chats, Workbrain content and personal agent memories are not.

## Status on 2026-10-29

| Area | State |
|---|---|
| Factory | Installed on `main`; rulesets, environment secrets and both Apps verified active. The review-fix loop passed live on PR #20 and again on PR #13 (2026-10-29: Astra finding F-006, automatic Claude correction, re-review `pass`). Ready for factory and documentation work. |
| Branch model | Validation branch `testing` (today's `main`, renamed) and production and config branch `production` ([ADR-0008](docs/decisions/0008-branch-model.md), 2026-11-02). It takes effect with the owner runbook in that record; its live acceptance is open until recorded in the [evidence](factory/evidence.md). |
| Full operational acceptance | Open: a second maintainer's own reviewer device, two devices racing for one claim, a new head during a running review, a foreign App with the same check name, authenticated skill/MCP calls inside the author container. See [evidence](factory/evidence.md). |
| Product development | North star approved by the repository owner on 2026-10-29 ([decision](docs/decisions/0006-northstar-approval.md)); architecture decisions and implemented product checks remain open. `northstar_approved: true`, `product_checks_ready: false`: only `factory` and `smoke` work orders run. |
| Architecture | Non-binding draft proposal v0.4 (merged with PR #13): [specification sheet and target architecture](docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md). Its AD-01..AD-12 bind only after adoption through decision records. |

The start-readiness review with measured times, friction and recommendations is in [factory/review-2026-10-29.md](factory/review-2026-10-29.md).

## Development

All development runs through the software factory, driven by the global **`factory`** command. It manages your control checkout (a clean clone on a listed branch, by default the config branch `production`, from which trusted code runs) and your candidate checkout (where changes land), so you run it from any directory. Every rule comes from the config branch; work orders are approved GitHub issues. This section gives the overview and the most common commands; the full details are in four documents:

| Document | Content |
|---|---|
| [docs/software-factory.md](docs/software-factory.md) | What the factory is, its pipeline, roles, limits and costs |
| [docs/way-of-working.md](docs/way-of-working.md) | Daily use: from work order to merge, stopping and cancelling, parallel PRs, merge rules |
| [docs/factory-cli.md](docs/factory-cli.md) | Command reference of `factory`: install, every command, runs, trust boundary, troubleshooting |
| [docs/factory-branches.md](docs/factory-branches.md) | Generated diagram of the validation and production branches, gates and review modes |
| [docs/dev-setup.md](docs/dev-setup.md) | One-time macOS device setup for reviewer and author devices |

### The software factory

The software factory is the set of tools, rules and GitHub automation in this repository that turns an approved **work order** (a task description in a GitHub issue) into a reviewed pull request. In short:

1. A maintainer writes a work order as a GitHub issue with goal, acceptance criteria and verification. On `/review` the factory proposes the allowed paths and fixes for weak sections; `/accept` from as many maintainer accounts as `work_order_approvals` in `factory/config.json` names (today 1) writes the paths into the issue and approves it.
2. Claude Code implements it as an **isolated author** in a disposable container without personal configuration or credentials; `factory` applies the result, unstaged, to a branch in the candidate checkout.
3. The maintainer reviews and stages the change and submits it with `factory submit --finished`, which opens the PR into the validation branch `testing` through `session.py submit`.
4. **Deterministic tests** run in GitHub Actions without secrets or network.
5. **GPT-6 Astra** reviews the PR on a maintainer's device. Blocking findings start a bounded **automatic correction**.
6. With both required checks green, a **maintainer merges** into `testing` with `factory merge`, one PR at a time.
7. When `testing` should go to production, `factory promote testing` opens the **promotion PR** into `production`; a maintainer starts its AI review with the comment `/review`, the production check passes once that review of the PR's head passed, and a maintainer merges it on GitHub with a merge commit. Then `factory update testing` fast-forwards `testing` to `production` in the candidate, and the maintainer pushes it. Nobody pushes to `production`; agents and bots never push to a listed branch or merge.

How each step works is in [docs/software-factory.md](docs/software-factory.md). How you take part in each step is in [docs/way-of-working.md](docs/way-of-working.md).

### Set up your device

Every maintainer device needs GitHub access, the pinned Codex CLI, a personal ChatGPT workspace access token and its own publisher App key in the macOS keychain, plus the `factory` command, installed with one script that also creates both checkouts. With those it can run the senior review. A device that also runs isolated author runs additionally needs Docker Desktop, the factory image and Anthropic and Context7 API keys (stored in the keychain by the installer). A new device counts as verified only after its first real smoke review. Step-by-step instructions are in [docs/dev-setup.md](docs/dev-setup.md).

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../aicepeak-control-checkout && ../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh
factory doctor
```

### Define a new task

A task is a **work order**: a GitHub issue opened by a maintainer; the issue number is its ID ([ADR-0009](docs/decisions/0009-issues-as-work-orders.md)). It is created in two steps:

1. **Write:** `factory issue --title "…"` opens the [work-order template](.github/ISSUE_TEMPLATE/factory-task.md) in your editor and creates the issue under your GitHub login with status `draft`. You write goal, non-goals, acceptance criteria and verification.
2. **Review and accept:** comment `/review` on the issue. The factory proposes the `allowed_paths` and fixes for weak or missing sections as comments; copy what you agree with into the description and `/review` again. `/accept` writes the proposed paths and `status: approved` into the issue. Any later edit withdraws the approval until it is accepted again.

Legacy work orders in `docs/work/` keep working; they change through `factory submit workorders`, and `factory update` brings them into the validation branches once merged.

Details: [way of working, steps 1–2](docs/way-of-working.md#daily-use-step-by-step).

### Start a new task

Start the [isolated author](docs/software-factory.md#the-isolated-author-session) on the approved work order; it runs in the background (Ctrl-C only detaches) and applies its result unstaged to `<login>/issue-<N>` in your candidate checkout. Review and stage what you accept, then commit, push and open the PR:

```sh
factory start workorder 57
git diff; git add -p                  # in the candidate checkout
factory submit                        # commit the staged files and push
factory submit --finished             # collision sweep, preflight, PR, watch
```

Details: [way of working, steps 3–6](docs/way-of-working.md#daily-use-step-by-step) and the [command reference](docs/factory-cli.md#factory-start-workorder).

### Stop or cancel a task

- **Running author:** Ctrl-C only detaches (`factory continue <n>` reattaches). `factory stop workorder <n>` ends the run after its current step and applies what exists; `factory cancel workorder <n>` ends it at once, removes its containers and applies nothing. Nothing reaches GitHub until you submit.
- **Watcher or review:** press Ctrl-C. The PR waits until a device watches again.
- **Pause a PR:** convert it to draft with `gh pr ready <n> --undo`.
- **Cancel a PR:** close it with a reason: `gh pr close <n> --comment '<reason>'`.
- **Finish a work order:** its PR says `Closes #57`, so merging it into `testing` closes the issue. Submit earlier parts of a work order split into several PRs with `factory submit --finished --keep-open`; reopen a closed issue to continue it.
- **Withdraw a work order:** close its issue (or edit it, which withdraws the approval). Every PR that references it is then blocked. A legacy file: change its `status` from `approved` and submit that with `factory submit workorders`.

Details and side effects: [way of working, stop or cancel a task](docs/way-of-working.md#stop-or-cancel-a-task).

### Other interactions

| Action | Command or place | Details |
|---|---|---|
| Run the binding review for a PR | `factory watch <n>`; all waiting PRs: `factory watch --all` | [factory watch](docs/factory-cli.md#factory-watch) |
| Give feedback | Ordinary PR comments, reviews and inline comments; each starts a fresh review | [Step 8](docs/way-of-working.md#daily-use-step-by-step) |
| Ask a question about a PR | `python3 tools/factory/session.py response --pr <n> --question '…' --post` (from the control checkout) | [Step 8](docs/way-of-working.md#daily-use-step-by-step) |
| Fix findings marked `needs-author-action` | `factory fix <n>` (or `factory hotfix <n>` for urgent fixes outside protected paths) | [factory fix](docs/factory-cli.md#factory-fix-and-factory-hotfix) |
| Review your candidate locally | `factory review "<question>"` (read-only, advisory) | [factory review](docs/factory-cli.md#factory-review) |
| Merge into `testing` | `factory merge <n>` (`--dry-run` for the verdict only) | [Merge rules](docs/way-of-working.md#merge-rules) |
| Promote `testing` to `production` | `factory promote testing`, then `/review` on the PR, `factory watch <n>`, and merge on GitHub with a merge commit once the production check is green; then `factory update testing` and push | [Branches and promotion](docs/way-of-working.md#branches-and-promotion) |
| Pass a stuck PR's checks deliberately | Comment `/bypass <reason>` on the PR for its current head; post a new comment instead of editing it or re-running its dispatch (every promotion accepts it, work-order and config PRs never) | [Branches and promotion](docs/way-of-working.md#branches-and-promotion) |
| See or change the branches | `factory branches [--show]`; `factory add validation branch`, `factory add production branch`, `factory remove branch`, `factory set config branch` | [factory branches](docs/factory-cli.md#factory-branches) |
| Run another branch's CLI code | `factory use branch <n>` | [factory use branch](docs/factory-cli.md#factory-use-branch) |
| Restart a stuck run | `gh workflow run factory.yml --ref production -f pr=<n> -f retry=true` (`--ref` is the config branch; a moved config tip re-runs open PRs by itself, a change of the config branch does not) | [Restart](docs/way-of-working.md#restart-a-stuck-run) |
| Work on several PRs at once | Collision sweep in `factory submit --finished`, then merge one PR at a time | [Working in parallel](docs/way-of-working.md#working-in-parallel) |
| See local factory runs | `factory status` | [factory status](docs/factory-cli.md#factory-status) |
| Check your device | `factory doctor` | [factory doctor](docs/factory-cli.md#factory-doctor) |
| Verify the repository locally | `python3 tools/factory/verify.py --root .` (from the control checkout) | [Verify locally](docs/way-of-working.md#verify-locally) |

## Repository map

| Path | Content |
|---|---|
| [AICEPEAK_NORDSTERN.md](AICEPEAK_NORDSTERN.md) | Canonical product goal (German); never copied |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Shared agent rules and the contribution flow |
| [docs/software-factory.md](docs/software-factory.md), [docs/way-of-working.md](docs/way-of-working.md), [docs/factory-cli.md](docs/factory-cli.md), [docs/factory-branches.md](docs/factory-branches.md), [docs/dev-setup.md](docs/dev-setup.md) | Factory description, daily use, `factory` command reference, branch diagram and device setup |
| [factory/policy.md](factory/policy.md), [factory/config.json](factory/config.json) | Binding policy, models, maintainers, limits, protected paths |
| [factory/evidence.md](factory/evidence.md), [factory/review-2026-10-29.md](factory/review-2026-10-29.md) | Real verification evidence and the start-readiness review |
| [factory/github.md](factory/github.md), [factory/clients.md](factory/clients.md) | GitHub operation, rulesets, isolated clients and the local reviewer |
| `.agents/`, `.claude/`, `.codex/` | Canonical skills and roles; generated native adapters (`clients.py sync`, checked by `clients.py check`) |
| `.github/` | Trusted pipeline, production check, dispatcher, feedback ingress, CODEOWNERS, templates |
| `tools/factory/` | Factory tools and their regression tests |
| `tools/factory/cli/` | The global `factory` command and its installer |
| [docs/work/](docs/work/TEMPLATE.md) | Legacy work-order files (on the config branch, brought into the validation branches with `factory update`); new work orders are issues |
| [docs/decisions/](docs/decisions/0005-maintainer-local-senior-review.md) | Decision records |
| [docs/architecture/](docs/architecture/AICEPEAK_SPEC_AND_ARCHITECTURE.md) | Non-binding architecture proposal and its validation |
