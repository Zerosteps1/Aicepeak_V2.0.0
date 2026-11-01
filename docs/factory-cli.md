# The factory command

`factory` is the maintainer's daily command for the [software factory](software-factory.md). It issues and activates work orders, runs the isolated author, fixes and reviews, submits, watches and merges, from any directory. It manages two checkouts for you: the **control checkout** (trusted code on current `main`) and the **candidate checkout** (where your changes land). It adds no new authority: the gate, the binding review, the isolated launcher, the credential broker and the human merge work exactly as described in [software-factory.md](software-factory.md). The decision record is [ADR-0007](decisions/0007-factory-cli.md); the daily flow is in [way-of-working.md](way-of-working.md).

```sh
factory --help              # commands grouped by flow
factory <command> --help    # what it does, when to use it, examples, documentation
factory --version           # the version of the CLI in use, e.g. "factory 0.1.0"
```

Help and `--version` work without installation, configuration, lock or network. The version is `VERSION` in `tools/factory/cli/factory.py`, the copy in your control checkout.

## Install

Prerequisites: `git`, `gh` (signed in as a configured maintainer) and Python 3.11 or newer, as in [dev-setup.md, step 2](dev-setup.md#2-install-tools-and-sign-in). Author runs additionally need Docker Desktop, the factory image and the author keys ([step 4](dev-setup.md#4-configure-the-isolated-author-skip-on-reviewer-only-devices)).

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../aicepeak-control-checkout && ../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh
```

You can also run `tools/factory/cli/install-factory-cli.sh` from any up-to-date clone of `main`: it refuses to run unless it is byte-identical to the copy on `origin/main`. Paths are resolved next to the clone the script runs from.

The installer has two stages:

1. **The script** checks `git`, `gh` and Python, fetches `main`, compares itself with `origin/main`, clones the control checkout if it is missing and then starts stage 2 from the control checkout.
2. **Stage 2** (`factory.py _install`, reviewed code from `main`) verifies the control checkout (configured repository, on `main`, clean including untracked and ignored files) and fast-forwards it, reuses or clones the candidate checkout, asks for a local Git `user.name`/`user.email` in the candidate if missing (default: your global Git setting), writes the device configuration and the shim, adds a PATH block to `~/.zshrc` only if the shim directory is not on `PATH`, and offers to store the author keys in the macOS login keychain.

| Option | Default | Meaning |
|---|---|---|
| `--control-dir DIR` | `../aicepeak-control-checkout` | Control checkout; an existing clone is reused |
| `--candidate-dir DIR` | `../aicepeak-candidate` | Candidate checkout; an existing clone is reused |
| `--bin-dir DIR` | `~/.local/bin` | Where the `factory` shim goes |
| `--author-keys` | off | Store the author keys again (rotation), even if keychain items exist |

A second run with the same options changes nothing. An existing control clone is fast-forwarded to `main` before its stage 2 starts; the script stops if that clone has local changes, extra or ignored files, or own commits. An existing candidate clone (for example an earlier `Aicepeak-candidate`) is reused if it is a plain clone of the configured repository (its `.git` is a folder, not a linked worktree) whose local Git configuration contains only the keys `factory` accepts ([troubleshooting](#troubleshooting)).

**Author keys.** Author runs need `ANTHROPIC_API_KEY` and `CONTEXT7_API_KEY`. The installer stores them as the keychain items `aicepeak-factory-anthropic-api-key` and `aicepeak-factory-context7-api-key` through `security add-generic-password` at a hidden prompt (enter the value twice). Exported environment variables win over the keychain. Rotate with `install-factory-cli.sh --author-keys`. Without a macOS keychain, export both variables before author runs. Reviewer-only devices need no author keys.

After installing, open a new terminal if the installer added the PATH block, then run `factory doctor`.

## Layout

| Path | Content |
|---|---|
| Control checkout (default `../aicepeak-control-checkout`) | Clean clone on current `main`. `factory` verifies and fast-forwards it before every command and runs trusted code only from it. Never change, add or delete anything there; `factory` refuses to run while it differs from `main` and never deletes files there itself. |
| Candidate checkout (default `../aicepeak-candidate`) | Your working clone: branches, edits, staging, commits. Every command acts on it, whatever your current directory. |
| `~/.local/bin/factory` | The shim: runs the configured control checkout's `tools/factory/cli/factory.py` with the Python found at install time (`-I -S -B`). An existing file that is not this shim is never replaced. |
| `~/.config/aicepeak-factory/cli.json` | Device configuration (mode 0600): absolute paths of control, candidate, Python and shim directory. The repository always comes from `factory/config.json`, never from here. |
| `~/.local/state/aicepeak-factory/runs/` | One folder per run ([details](#runs-steps-budget-and-logs)). |
| `~/.local/state/aicepeak-factory/locks/` | `control.lock` and `candidate.lock` with a `.holder` note (process, command, start time). The kernel releases a lock when its holder ends; there is nothing to delete by hand. |
| `~/.local/state/aicepeak-factory/reviews/` | Saved reports of `factory review`. |
| `~/.local/state/aicepeak-factory/tmp/` | Disposable checkouts; each is removed after use. |

`factory` puts the pinned Codex directory `~/.local/share/aicepeak-factory-cli/node_modules/.bin` in front of the `PATH` of its helper processes, so the reviewer finds `codex-cli 0.164.0` without an `export` in your terminal. When you run a command outside the candidate, it prints `(working on the candidate checkout …)`.

## Daily flow

```sh
factory issue --title "Export energy costs as CSV"   # write the work order in your editor
factory submit workorders                            # validate, approve, push, open and watch the work-order PR
factory merge 51                                     # once both checks are green
factory start workorder 8                            # author → preflight → corrections → applied, unstaged
git diff; git add -p                                 # in the candidate: review and stage what you accept
factory submit                                       # commit the staged files and push (repeat as needed)
factory submit --finished                            # open the PR, preflight, ready on pass, watch
factory watch 52                                     # later reviews: after new pushes or comments
factory merge 52 --dry-run && factory merge 52
```

**Work-order references.** `7`, `007` and `FACTORY-007` all work; a reference resolves only when exactly one work order on `main` matches (for `continue`, `stop` and `cancel`: one work order with runs on this device). If several match, `factory` lists them; use the full name.

**Work-order numbers.** New work orders are named `<KIND>-<NNN>.md` with the prefix `FACTORY`, `PRODUCT` or `SMOKE`. One counter serves all kinds: the next number is one higher than every number ever added on `main` (deleted work orders keep theirs), present in the candidate's `docs/work/`, or added by an open pull request of a configured maintainer in this repository. Names without a number, such as `FACTORY-SMOKE`, do not count.

**Branch names.** `factory` uses and recognises:

| Branch | Created by | Meaning |
|---|---|---|
| `<login>/<ID>` | `factory start` | First implementation branch of a work order |
| `<login>/<ID>-<k>` | `factory start` | Next implementation branch once the previous one is merged |
| `<login>/<ID>-fix-<k>` | `factory fix`, `factory hotfix` | Fix branch when the work order has no open PR |
| `<login>/new-workorders` | `factory submit workorders` | Your work-order PR |

`<login>` is your GitHub login. `factory submit` derives the work order from these names; on any other branch use `--workorder`.

## factory issue

Creates a new work order from [docs/work/TEMPLATE.md](work/TEMPLATE.md) in the candidate checkout and opens it in `$VISUAL`, `$EDITOR` or, on macOS, the default text editor. Use it whenever the factory should build something new: one work order per feature, not per commit.

```sh
factory issue --title "Export energy costs as CSV"
factory issue --kind smoke --title "Reviewer device smoke" --noedit
factory issue          # title later, in the editor
```

The file gets the [next free number](#daily-flow), your title, status `draft`, `requirements: []` (except for `product`) and a handoff block with runner `claude`, the file's own path and you as owner. `--kind` is `factory` (default), `product` or `smoke`; `--noedit` only creates the file and prints its path. Then fill in goal, non-goals, acceptance criteria and the exact `allowed_paths`, and run [factory submit workorders](#factory-submit-workorders). You can stay on any branch: only the work-order file is created.

Notable refusals and warnings: an existing file is never overwritten; if open pull requests cannot be checked, `factory` warns that a number might collide; `product` work orders stay blocked while `product_checks_ready` is `false` in [factory/config.json](../factory/config.json).

## factory submit workorders

Activates work orders. Use it after [factory issue](#factory-issue) (or after editing or deleting a work order), when the text is final. A work order authorizes work only once it is approved and merged to `main`.

```sh
factory submit workorders
```

What it does:

1. Collects your uncommitted changes of `docs/work/*.md` against the candidate's `HEAD`: new files, edits and deletions (the template excluded). Everything else in your checkout stays untouched.
2. Checks every file and lists all problems at once: the `factory-task` block rules of the gate (exactly one block, valid JSON, exactly `status`, `kind`, `allowed_paths`, safe non-empty paths; any status is accepted here); for new files the name `<KIND>-<NNN>.md`, a prefix matching `kind`, the first line `# <ID> – <title>` and an unused number; no template placeholder (`REPLACE-WITH-EXACT-PATHS`, `TASK-ID`, the template title and acceptance-criteria lines); at most one `factory-handoff` block, naming the file itself.
3. Shows the diff of every edited work order and asks before submitting it; asks before every deletion; asks for every draft whether it should become `approved` (and writes that into your file).
4. Commits only these files in a disposable checkout on `<login>/new-workorders` (title `docs(work): add …, update …, remove …`) and pushes. Without an open PR it opens one through `session.py submit` with the handoff task `docs/work/FACTORY-001.md` (collision sweep, advisory preflight, ready on `pass`, then watch). With your open PR it adds the commit, promotes a draft only after a passing preflight, and watches.
5. Moves the submitted files out of your working tree, because they now live on the work-order branch: only after the PR exists (for a new PR, as soon as `session.py submit` reports it, before its watch; for your open PR, once the push succeeded) and only files still byte-identical to what was submitted. New files are removed; edited or deleted ones return to the version of your `HEAD`. If no PR is created (for example the preflight does not pass), the files stay in your working tree.

Then merge the work-order PR with [factory merge](#factory-merge).

Notable refusals: no work-order changes; any validation problem (nothing is pushed); a work order whose version in your `HEAD` differs from `main` or your open work-order PR (update the candidate first); the candidate is itself on `<login>/new-workorders`; a conflict with `main` on your open work-order PR. If `<login>/new-workorders` exists on GitHub with commits that are not on `main` and has no open PR, `factory` lists those commits and replaces the branch only after you confirm (with `--force-with-lease`).

## factory start workorder

Starts the isolated author on an approved, merged work order as a background run and attaches to it. Use it when the work order is on `main` with status `approved` and you want the factory to implement it.

```sh
factory start workorder 7
factory start workorder FACTORY-007
```

Before the run starts, `factory` checks in the foreground: the work order exists on current `main` and is `approved` (`product` only when the north star and product checks are ready), no run for it is active, Docker runs and the factory image exists, and both author keys are available. The branch is the newest unmerged `<login>/<ID>` or `<login>/<ID>-<k>` (continued), otherwise a new one from `main`.

The run then goes: **author** (`factory-start`, then `factory-change` for this work order, limited to its `allowed_paths`) → **advisory Astra preflight** (`session.py preflight`) → at most `max_rounds` (2) **corrections** with `factory-fix-review` while P0/P1 findings remain → **apply**. The result is applied **unstaged** to the branch in your candidate; nothing is committed or pushed. The log shows each step, one line per author tool call, a heartbeat every minute and the cost estimate ([runs](#runs-steps-budget-and-logs)). Ctrl-C only detaches; the run goes on (`factory continue 7`). Next: review `git diff`, stage what you accept, [factory submit](#factory-submit).

The isolated author cannot write the control paths (`.agents`, `.claude`, `.codex`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, `factory/`, `tools/factory/`). `factory` refuses a work order whose `allowed_paths` all lie there and warns when some do; such changes stay [protected factory changes](../factory/clients.md#protected-factory-changes) made by hand.

The result is **not applied** (the patch is kept in the run folder and the exact `git switch` and `git apply` commands are printed) when it changes files outside `allowed_paths`, under `.github/` or `docs/work/`, binary files, symlinks or submodules; when the candidate has uncommitted changes in tracked files, is on another branch than `main` or the target, or untracked files would be overwritten; when the target branch moved since the run started; when the patch does not apply; or when `main` had to be merged for the preflight of an existing branch. The remaining steps are skipped, with the reason in the log, when nothing differs from `main`, more than `max_changed_files` (40) files changed, files outside the work order changed, `main` moved and conflicts, the preflight could not run, or the [run budget](#runs-steps-budget-and-logs) is spent.

Notable refusals: no unique work order on `main`; not approved; a run for it already active; all `allowed_paths` are control paths; Docker or image missing; a key missing; your local branch lacks commits that are on GitHub (`git pull --ff-only` first).

## factory continue

Reattaches to a running run: shows its log from the start and follows it until the run ends; the exit code is the run's result. Use it after Ctrl-C or after closing the terminal.

```sh
factory continue 7
factory continue        # the only active run
```

Without a work order it works only when exactly one run is active. When no run is active it fails and names the last run's result, reason and log path. It needs no network.

## factory stop workorder

Stops a run after its current step. The step in progress (author, review, fix, correction or preflight) finishes; every further model and review step is skipped; what exists is applied as usual. The run ends `stopped`. Nothing changes on GitHub: a stopped `hotfix` pushes nothing and ends like `fix`. A watch that a run already started (after its PR exists) is interrupted at once. Use it when the run is heading in the wrong direction or you need the machine, but the current step may finish.

```sh
factory stop workorder 7
```

## factory cancel workorder

Emergency stop. Terminates the run and its processes at once (SIGTERM to the runner, which forwards it to the launcher or `session.py` and waits up to 30 seconds; after 45 seconds the process group is killed), removes every Docker container, network and volume that carries the run's label, and applies nothing. The run ends `cancelled`. Use it when something is clearly wrong (cost, scope, a runaway step) and waiting for the step is not acceptable.

```sh
factory cancel workorder 7
```

The cancel itself changes no GitHub state. If the run already had a PR, it prints how to pause it (`gh pr ready <n> --undo`), close it, and retry a claimed review that got stuck (`gh workflow run factory.yml --ref main -f pr=<n> -f retry=true`); a review that was already claimed stays claimed. [Stop vs. cancel in the daily flow](way-of-working.md#stop-or-cancel-a-task).

## factory fix and factory hotfix

`factory fix <n> ["prompt"] [--pr N]` fixes a problem within an approved work order: it reviews the problem read-only, lets the author write a fix plan and the smallest fix inside the work order's `allowed_paths` (with a regression test and verification), runs the preflight/correction loop and applies the result unstaged. You check it and submit. Use it when a problem belongs to an approved work order and you want to look at the fix before it is pushed.

```sh
factory fix 7 "CSV export drops rows with empty tariffs"
factory fix 7 "#42"                  # a maintainer-written issue, PR or comment
factory fix 7                        # the open PR's review findings
factory hotfix 7 "Totals use the wrong VAT rate"
```

**Target.** The work order's open PR (same repository, opened by a configured maintainer, handoff naming this work order): the fix lands on its branch. With several such PRs choose one with `--pr`. A PR owned by another maintainer needs your confirmation, which names the owner. Without an open PR, a new `<login>/<ID>-fix-<k>` from `main`.

**Input.** The prompt is free text, or `#N` or a GitHub URL of an issue, PR or comment in this repository written by a configured maintainer (anything else is refused; paste the text instead). Without a prompt, the open PR's newest authentic senior review of its current head plus all maintainer feedback is fixed directly; without an open PR, a read-only review against the work order's acceptance criteria comes first.

After applying, `fix` prints the exact next command, for example `factory submit --finished --title 'fix(FACTORY-007): CSV export drops rows with empty tariffs'`.

`factory hotfix` runs the same steps and then the **push gate**. It pushes automatically only if every changed file is inside `allowed_paths`, outside `.github/`, `docs/work/` and every `protected_paths` entry (and not the north star file), with no binary, symlink or submodule entry, the last preflight returned `pass` on exactly this result, `main` did not move since (and did not have to be merged into an existing PR branch), and the branch on GitHub is unchanged (an existing PR branch still at the run's base; a new fix branch not yet present). Then it creates one commit with your candidate's Git identity, pushes it without force, fetches it into the candidate (`origin/<branch>`) and either watches the existing PR or opens a new one through `session.py submit` (preflight, ready on `pass`, watch). If any condition fails, it names them and ends exactly like `fix`. Use `hotfix` for urgent, small fixes outside the protected factory paths.

Notable refusals: an automatic correction is running on the PR (`factory/author-reservation` in progress); the PR has no senior review yet, it is still running, it has no findings, or the head moved since (give a prompt instead); the referenced text is not by a configured maintainer; the same refusals as [factory start workorder](#factory-start-workorder).

## factory review

A local, read-only review of your candidate: a list of problems, nothing changed. Use it before you submit, or to hunt a suspected problem.

```sh
factory review "Are there error paths in the CSV export without tests?"
factory review "Check the acceptance criteria" --workorder 7
```

It copies the tracked and untracked-but-not-ignored regular files of the candidate exactly as they are on disk (uncommitted changes included) and runs the read-only reviewer in the isolated container (`clients.py run --read-only`: only Read, Glob, Grep, Skill and the documentation tools, no patch). It prints a numbered list of problems with `file:line`, evidence and a minimal fix, and saves the report in `~/.local/state/aicepeak-factory/reviews/`. `--workorder` adds the work order as context. It runs in the foreground; Ctrl-C cancels it and removes its containers. It needs Docker, the image and the author keys and costs one model run (up to `max_run_cost_usd`).

Advisory only: it does not replace the preflight or the binding review. Symlinks and special files are skipped and listed. Control paths are listed as **not reviewed** where your candidate differs from `main`, because the container shows the reviewer their version from `main`.

## factory submit

Commits what you staged and pushes the branch; with `--finished` opens the pull request for the work order. Use it daily to commit and push your work, and with `--finished` when the work order is done.

```sh
factory submit --title "feat(export): CSV export" --desc "Adds the endpoint and tests"
factory submit --finished
factory submit --finished --workorder 7 --draft
```

- Commits **only staged** files. The title defaults to `<ID>: <work order title>`, `--desc` becomes the body; on a branch without a work order and without `--title`, your commit editor opens. Unstaged changes stay where they are.
- Pushes the current branch to GitHub, never `main` and never with force.
- The work order comes from the [branch name](#daily-flow) or `--workorder` (`7`, `007` or `FACTORY-007`). On any other branch `factory` warns and waits 5 seconds (Ctrl-C aborts); `--finished` then requires `--workorder`.
- `--finished` requires that the branch contains current `main`. Without an open PR it runs `session.py submit` on a disposable checkout of the pushed commit: collision sweep, advisory preflight, PR with the handoff block (runner `claude`, the work order, you as owner), ready only on `pass`, then watch. The PR body contains `--desc`, the work order and the commit list. Unchanged repository modules that changed Python files import directly are added as preflight context automatically; add more with `--context <path>` (repeatable). With an open PR it promotes a draft only after a passing preflight and then watches; a ready PR is only watched.
- If the preflight does not pass, no PR is opened: fix the findings and run `--finished` again, or open it as a draft with `--draft`. Ctrl-C stops watching; the PR keeps waiting for a watcher ([factory watch](#factory-watch)).

Notable refusals: detached `HEAD`; the default branch `main`; a branch behind or diverged from GitHub (`git pull --ff-only` or merge first); `--finished` on a branch without current `main` (`git merge origin/main`, or `gh pr update-branch <n>` for an open PR).

## factory watch

Runs the binding senior review for a PR on this device. Every ready PR waits for review until a maintainer device watches it. Use it after Ctrl-C in `submit`, after new pushes or comments, or for other maintainers' PRs.

```sh
factory watch 42
factory watch --all
```

`factory watch <pr>` runs `session.py watch --pr <pr>` from a disposable checkout of the verified `main`: it starts a pending review for the PR's current head through the shared claim and keeps polling until the PR is closed or `session.py`'s watch timeout (30 minutes by default) ends. `--all` reviews every open PR labelled `awaiting-senior-review` once a minute (`session.py watch --pr <n> --once` each), updating the control checkout between rounds, until Ctrl-C. Name one PR or use `--all`. Keep the Mac awake while watching.

## factory merge

Merges a PR with the verified, locked merge of [session.py merge](way-of-working.md#merge-rules). Use it when both required checks are green and you decided to merge; one PR at a time.

```sh
factory merge 42 --dry-run     # the verdict only
factory merge 42
```

It verifies both required checks on exactly this head and current `main`, the handoff, maintainer feedback and open threads, takes the repository merge lock and merges with `--match-head-commit`. After a merge it fetches `main` into the candidate; update your branches from `origin/main` when you continue. The exit code is non-zero when the PR is not mergeable, also with `--dry-run`.

## factory status

Lists the latest 15 runs on this device: active marker, work order, kind, current step (active) or result, start time, branch and PR. Use it to see what the factory is doing or did.

```sh
factory status
```

It needs no network. A run whose runner died is recorded as `failed` (`the runner ended unexpectedly`); its leftover processes and labelled Docker resources are removed.

## factory doctor

Checks this device and prints the fix for every failed check. Use it after installing, after tool updates, or when a command fails for environmental reasons.

```sh
factory doctor
```

Checks: the shim on `PATH` is the installed one; control and candidate are separate repositories; the candidate checkout is usable (plain clone, configured repository, allowed local Git configuration, local `user.name`/`user.email`); both author keys (exported or in the keychain); the factory image (it prints the `docker build` command); the pinned `codex-cli 0.164.0`; your `gh` login is a configured maintainer with write access. The control checkout is verified before every command anyway. It then runs `doctor.py` from a disposable checkout of `main` and summarises its status and blocked checks. `doctor.py` sees only exported author keys and always exits with code 2 because it never certifies live acceptance ([check the tools](dev-setup.md#check-the-tools)). `factory doctor` exits 0 when all of its own checks pass.

## Runs: steps, budget and logs

`start`, `fix` and `hotfix` run in the background, independent of the terminal; one run per work order at a time. The foreground command validates everything, writes a pinned export of the verified control commit into the run folder, starts the runner from that export and attaches. A later update of the control checkout therefore never changes a running job. On macOS, `caffeinate -i` keeps the Mac from idle-sleeping while the runner lives; closing the lid or system sleep still pauses the run.

| Kind | Steps |
|---|---|
| `start` | author → preflight → up to `max_rounds` corrections while P0/P1 findings remain → apply |
| `fix` | review (or the PR's findings) → fix → preflight/correction loop → apply |
| `hotfix` | as `fix`, then the push gate → push and PR, or apply as `fix` |

Every model step is one `clients.py run` from the pinned export, labelled `aicepeak.factory.run=<run id>` on every container, network and volume, with an event stream; review steps use `--read-only` ([launcher options](../factory/clients.md#build-and-run)). Each preflight runs on a disposable checkout of the run's commit; if `main` moved, the run first merges the new `main` and stops on a conflict.

**Budget.** One run stays within `max_cost_usd` (USD 25) across all its model steps; each model step may use up to `max_run_cost_usd` (USD 12), enforced by the credential broker. Before every model step the run checks that the spend so far plus USD 12 still fits into USD 25; otherwise it skips the remaining model steps and applies what exists. The spend is Claude's own reported estimate (`reported_cost_usd`); a failed step or one without a reported cost counts as the full USD 12. The broker's caps stay authoritative; the displayed amounts are estimates, not invoices. Preflights and binding reviews use the maintainer's Codex seat, not this budget.

**Run folder** `~/.local/state/aicepeak-factory/runs/<ID>-<date>-<time>-<hex>/` (mode 0700):

| File | Content |
|---|---|
| `run.json` | Kind, work order, branch, base, PR, step, status, process, Docker host, spend |
| `log` | Everything shown while attached: steps (`— author`), tool calls (`· 12:03:04 Read docs/…`), heartbeats, preflight results, cost lines, next steps |
| `lock` | Held by the runner for its whole life: liveness without inspecting processes |
| `<step>.prompt`, `<step>.events`, `<step>.patch`, `<step>.patch.report.txt` | Prompt (with the work-order text), tool-call lines, patch and report of each model step (`author`, `review`, `fix`, `correction-1`, …) |
| `changes.patch` | The final patch, also when it was not applied |
| `stop` | Present after `factory stop` |

The pinned export and the run's working checkout are removed when the run ends; logs, prompts, patches and reports stay until you delete the folder. A run ends `completed`, `stopped`, `failed` or `cancelled` (exit code 0, 0, 1, 130). If the first author (or review) step fails (launcher error, timeout), the run ends `failed` and applies nothing. If a later preflight or correction step fails, the remaining review steps are skipped and the result that already exists is applied as usual.

## Trust boundary

`factory` runs with your GitHub login and author keys, so it runs only reviewed code and never executes candidate files on your host.

- **Only the control checkout.** The shim lies outside every checkout. `factory.py` exits non-zero before doing anything if it is not the installed control checkout's copy (or, for the background runner, the run's own pinned export).
- **Verified before every command.** Under an exclusive lock (60 seconds wait, then it names the holder) `factory` checks that the control checkout belongs to the configured repository, is on `main` and is clean including untracked and ignored files, fetches `main` over https and fast-forwards it. It never resets or deletes files there. If the code changed, it restarts itself from the new version. `status`, `continue`, `stop` and `cancel` skip the fetch.
- **Disposable checkouts.** `session.py` and `doctor.py` run from a disposable checkout of exactly the `main` commit the command works against, and `session.py` receives the candidate only as a disposable snapshot of committed state (for `submit`, exactly the pushed commit). Both are written byte-exact from Git objects: no clone, checkout filter, hook or attribute conversion.
- **Hardened Git.** Every Git call runs without hooks, fsmonitor, global or system configuration, attribute files, replace objects, lazy fetches or submodule recursion, and reaches GitHub only over https with `gh` as credential helper. The candidate's `.git` must be a plain folder and its local configuration may contain only an allowlist of keys (repository basics, `remote.origin.url`/`fetch`, branch tracking, `user.name`/`user.email`, `pull.rebase`).
- **Explicit environments.** Trusted helpers run with `python -E -S -B` and an allowlisted environment (absolute `PATH` entries only, plus the pinned Codex directory); `CODEX_ACCESS_TOKEN` and `FACTORY_PUBLISHER_APP_PRIVATE_KEY` are passed on only when you exported them.
- **Author keys.** Taken from the environment or the keychain, handed to the background runner through a pipe, and put only into the environment of the `clients.py run` child, which gives them to the credential broker, never to the worker. They are never written to a file, log or argument.
- **GitHub input only from maintainers.** Work-order numbers, fix targets and `#N` prompts use only same-repository PRs, issues and comments by configured maintainers. Model output, tool events and GitHub text are printed only with control characters escaped.
- **Isolated author unchanged.** It cannot write control paths, cannot see your credentials and returns only a patch. `factory` never pushes to `main`, never force-pushes (except the confirmed replacement of an unmerged `<login>/new-workorders`, with lease), merges only through `session.py merge`, and never deletes files except the documented move of submitted work orders.

## Troubleshooting

| Message (after `BLOCKED:`) | Cause and fix |
|---|---|
| `factory is not installed on this device` | Run the [installer](#install). |
| `this is not the installed control checkout` | You started `factory.py` by path. Use the `factory` command. |
| `control checkout …: checkout must be clean: untracked file …` | Something wrote into the control checkout (often `.DS_Store` from Finder, `__pycache__`, an editor). Remove or revert the named file yourself; `factory` never deletes files there. |
| `control checkout … cannot fast-forward to origin/main` | It has its own commits. Recreate it with the installer. |
| `the control checkout is busy (held by pid …)` / `the candidate checkout is busy` | Another `factory` command holds the lock. Wait for it or stop it, then retry. |
| `control and candidate checkouts share one Git repository` / `must be separate folders` | Use two separate clones, neither inside the other. |
| `candidate … has settings factory does not run with: …` | Remove each named key with `git -C <candidate> config --local --unset <key>`. |
| `candidate has no local user.name` | `git -C <candidate> config --local user.name '…'` (same for `user.email`), or rerun the installer. |
| `Docker is not running` / `author image … is missing` | Start Docker Desktop; `factory doctor` prints the build command. Set `FACTORY_DOCKER_HOST` only if the active Docker context is not the right endpoint. |
| `ANTHROPIC_API_KEY missing` | Rerun the installer with `--author-keys`, or export the key. |
| `a run for … is already active` | `factory continue <n>`, or `factory stop`/`cancel workorder <n>`. |
| `every allowed path of this work order is a control path` | The isolated author cannot write it: make it a [protected factory change](../factory/clients.md#protected-factory-changes). |
| `Patch kept, not applied: …` (in the run log) | Check the named reason, then run the printed `git switch` and `git apply` commands yourself. |
| `… is behind or diverged from GitHub` | `git -C <candidate> pull --ff-only` (or merge), then retry. |
| `the run did not start; see …/log` | Read the log; often Docker, the image or a key. |
| `command not found: factory` | Open a new terminal (PATH block) or add the shim directory to `PATH`. If the Python recorded in the shim no longer exists, rerun the installer. |
| `pinned Codex 0.164.0` fails in `factory doctor` | Install it as in [dev-setup.md, step 2](dev-setup.md#2-install-tools-and-sign-in). |
| The merge lock is held | See [merge rules](way-of-working.md#merge-rules). |

System sleep pauses runs and watchers; keep the Mac awake during long runs. `factory status` shows every run; each run's `log` has the complete history.

## Without the CLI

The CLI wraps the existing tools; for troubleshooting you can run them yourself. Run them from the control checkout, which must stay a clean copy of current `main` (`git status --short --untracked-files=all --ignored` shows nothing; update with `git pull --ff-only`), and pass the candidate checkout explicitly. Export the pinned Codex directory in that terminal (`export PATH="$HOME/.local/share/aicepeak-factory-cli/node_modules/.bin:$PATH"`).

```sh
python3 tools/factory/session.py collisions --candidate ../aicepeak-candidate --task docs/work/<ID>.md
python3 tools/factory/session.py preflight --candidate ../aicepeak-candidate --task docs/work/<ID>.md
python3 tools/factory/session.py submit --candidate ../aicepeak-candidate \
  --task docs/work/<ID>.md --runner claude --title '<title>' --body-file /path/outside/checkouts/body.md
python3 tools/factory/session.py watch --pr <n>              # --once: poll once
python3 tools/factory/session.py response --pr <n> --question '<question>' --post
python3 tools/factory/session.py merge --pr <n> --dry-run
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py launch --root . --runner claude    # interactive author; needs exported keys
```

`session.py submit` needs a clean candidate whose branch is already pushed. The unattended launcher with labels, read-only mode and event stream is documented in [factory/clients.md](../factory/clients.md#build-and-run). Leftover Docker resources of a run can be listed with `docker ps -a --filter label=aicepeak.factory.run=<run id>` (likewise `docker network ls` and `docker volume ls`); `factory cancel` and `factory status` remove them for you.
