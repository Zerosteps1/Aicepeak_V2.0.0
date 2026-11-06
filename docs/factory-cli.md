# The factory command

`factory` is the maintainer's daily command for the [software factory](software-factory.md). It issues, activates and syncs work orders, runs the isolated author, fixes and reviews, submits, watches, merges and promotes, and manages the branch list, from any directory. It manages two checkouts for you: the **control checkout** (trusted CLI code on the listed branch you follow, by default the config branch `production`) and the **candidate checkout** (where your changes land). Every rule (branch list, gates, routing, policy, limits and work orders) comes from the tip of the **config branch** ([branch model](factory-branches.md)). It adds no new authority: the gate, the binding review, the isolated launcher, the credential broker and the human merge work exactly as described in [software-factory.md](software-factory.md). The decision records are [ADR-0007](decisions/0007-factory-cli.md) and [ADR-0008](decisions/0008-branch-model.md); the daily flow is in [way-of-working.md](way-of-working.md).

```sh
factory --help              # commands grouped by flow
factory <command> --help    # what it does, when to use it, examples, documentation
factory --version           # the version of the CLI in use: "factory 0.2.0"
```

Help and `--version` work without installation, configuration, lock or network. The version is `VERSION` in `tools/factory/cli/factory.py`, the copy in your control checkout; this documentation describes `factory 0.2.0`. Help texts link to the documentation on the config branch.

## Install

Prerequisites: `git`, `gh` (signed in as a configured maintainer) and Python 3.11 or newer, as in [dev-setup.md, step 2](dev-setup.md#2-install-tools-and-sign-in). Author runs additionally need Docker Desktop, the factory image and the author keys ([step 4](dev-setup.md#4-configure-the-isolated-author-skip-on-reviewer-only-devices)).

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git ../aicepeak-control-checkout && ../aicepeak-control-checkout/tools/factory/cli/install-factory-cli.sh
```

You can also run `tools/factory/cli/install-factory-cli.sh` from any clone whose copy of the script is current: it refuses to run unless it is byte-identical to the copy on the config branch (`origin/production`). Paths are resolved next to the clone the script runs from.

The installer has two stages:

1. **The script** checks `git`, `gh` and Python and takes the initial configuration from a production branch, because only reviewed PRs reach those. Production branches are the ones GitHub protects with an active ruleset `Factory production: <branch>` that targets exactly that branch; only an admin creates these rulesets (`settings.py apply`), and `gh` reads them with any login that can read the repository.
   - One protected production branch: it is used.
   - Several: on a terminal the script lists them and asks for a number; otherwise name one with `--config-branch NAME`.
   - `--config-branch NAME` must name a protected production branch.
   - None yet (before `settings.py apply`), or `gh` cannot read the rulesets: the script falls back to the GitHub default branch and prints `note: GitHub protects no production branch yet …; the default branch <name> names the config branch`.

   It reads the `config_branch` that branch's `factory/config.json` names, fetches the config branch and checks that the configuration there names that same branch and lists the control branch (`--branch`, default: the config branch). When GitHub protects production branches, the config branch must be one of them. Every problem with a configuration (missing file, invalid JSON, no `config_branch`, no branch list, a branch missing on GitHub) ends with a message that names it; while GitHub's default branch still carries the configuration from before the branch model, the message names the [owner runbook](decisions/0008-branch-model.md#owner-runbook-after-the-merge). After a finished [change of the config branch](#factory-set-config-branch) that configuration names another listed production branch whose own configuration names itself: the script then fetches that branch too, follows it once (printing `note: <old> names the config branch <new>; following it`) and uses it as the config branch from then on. It compares itself with the config branch's copy, clones the control checkout on the control branch if it is missing (or switches a clean existing one to it and fast-forwards it), and then starts stage 2 from the control checkout.
2. **Stage 2** (`factory.py _install`, reviewed code of the control branch) verifies the control checkout (configured repository, on the control branch, clean including untracked and ignored files, listed on the config branch) and fast-forwards it, reuses or clones the candidate checkout, asks for a local Git `user.name`/`user.email` in the candidate if missing (default: your global Git setting), writes the device configuration (including the control branch) and the shim, adds a PATH block to `~/.zshrc` only if the shim directory is not on `PATH`, and offers to store the author keys in the macOS login keychain.

| Option | Default | Meaning |
|---|---|---|
| `--control-dir DIR` | `../aicepeak-control-checkout` | Control checkout; an existing clone is reused |
| `--candidate-dir DIR` | `../aicepeak-candidate` | Candidate checkout; an existing clone is reused |
| `--bin-dir DIR` | `~/.local/bin` | Where the `factory` shim goes |
| `--branch NAME` | the config branch | Listed branch whose factory code this device runs; change it later with [factory use branch](#factory-use-branch) |
| `--config-branch NAME` | the protected production branch | Production branch to take the initial configuration from; needed without a terminal when GitHub protects several |
| `--author-keys` | off | Store the author keys again (rotation), even if keychain items exist |

A second run with the same options changes nothing. An existing control clone is switched to the control branch and fast-forwarded before its stage 2 starts; the script stops if that clone has local changes, extra or ignored files, or own commits on that branch. A device installed before the branch model (control checkout on `main`) stops working once `main` is renamed; reinstall it as described in [dev-setup.md](dev-setup.md#install-the-factory-command). An existing candidate clone (for example an earlier `Aicepeak-candidate`) is reused if it is a plain clone of the configured repository (its `.git` is a folder, not a linked worktree) whose local Git configuration contains only the keys `factory` accepts ([troubleshooting](#troubleshooting)).

**Author keys.** Author runs need `ANTHROPIC_API_KEY` and `CONTEXT7_API_KEY`. The installer stores them as the keychain items `aicepeak-factory-anthropic-api-key` and `aicepeak-factory-context7-api-key` through `security add-generic-password` at a hidden prompt (enter the value twice). Exported environment variables win over the keychain. Rotate with `install-factory-cli.sh --author-keys`. Without a macOS keychain, export both variables before author runs. Reviewer-only devices need no author keys.

After installing, open a new terminal if the installer added the PATH block, then run `factory doctor`.

## Layout

| Path | Content |
|---|---|
| Control checkout (default `../aicepeak-control-checkout`) | Clean clone on its control branch: the config branch by default, or the listed branch chosen with [factory use branch](#factory-use-branch). `factory` verifies and fast-forwards it before every command and runs trusted CLI code only from it. Never change, add or delete anything there; `factory` refuses to run while it differs from that branch and never deletes files there itself. |
| Candidate checkout (default `../aicepeak-candidate`) | Your working clone: branches, edits, staging, commits. Every command acts on it, whatever your current directory. |
| `~/.local/bin/factory` | The shim: runs the configured control checkout's `tools/factory/cli/factory.py` with the Python found at install time (`-I -S -B`). An existing file that is not this shim is never replaced. |
| `~/.config/aicepeak-factory/cli.json` | Device configuration (mode 0600): absolute paths of control, candidate, Python and shim directory, and the control branch (`branch`). A configuration without `branch` (installed before the branch model) gets the verified control branch recorded by the next command, before any fast-forward. The repository and every rule always come from `factory/config.json`, never from here. |
| `~/.local/state/aicepeak-factory/runs/` | One folder per run ([details](#runs-steps-budget-and-logs)). |
| `~/.local/state/aicepeak-factory/locks/` | `control.lock` and `candidate.lock` with a `.holder` note (process, command, start time). The kernel releases a lock when its holder ends; there is nothing to delete by hand. |
| `~/.local/state/aicepeak-factory/reviews/` | Saved reports of `factory review`. |
| `~/.local/state/aicepeak-factory/branches.html` | The page written by `factory branches --show`. |
| `~/.local/state/aicepeak-factory/tmp/` | Disposable checkouts; each is removed after use. |

`factory` puts the pinned Codex directory `~/.local/share/aicepeak-factory-cli/node_modules/.bin` in front of the `PATH` of its helper processes, so the reviewer finds `codex-cli 0.164.0` without an `export` in your terminal. When you run a command outside the candidate, it prints `(working on the candidate checkout …)`.

**Which code and which rules.** The CLI code is the control checkout's commit. Every rule is read from `factory/config.json` and `docs/work/` at the config branch tip that the command fetched and pinned: the branch list, gates, routing, review modes, limits and work orders. `session.py` and `doctor.py` always run from a disposable checkout of that config branch tip, so the checks and reviews they start bind to it even when your control checkout follows a validation branch. Only the repository and the name of the config branch come from the control checkout's own `factory/config.json`. When the configuration on that branch names another listed production branch whose own configuration names itself (a finished [config branch change](#factory-set-config-branch)), `factory` fetches both and follows that one hop; every message and every later use then names the followed config branch.

## Daily flow

```sh
factory issue --title "Export energy costs as CSV"   # write the work order in your editor
factory submit workorders                            # validate, approve, push and open the work-order PR into the config branch
                                                     # two maintainer approvals, then a maintainer merges it on GitHub
factory sync workorders                              # copy the merged work order to every validation branch
factory start workorder 8                            # author → preflight → corrections → applied, unstaged
git diff; git add -p                                 # in the candidate: review and stage what you accept
factory submit                                       # commit the staged files and push (repeat as needed)
factory submit --finished                            # open the PR into the routed validation branch, preflight, ready on pass, watch
factory watch 52                                     # later reviews: after new pushes or comments
factory merge 52 --dry-run && factory merge 52
factory promote testing                              # when testing should go to production
```

**Branches.** Feature branches (below) target the validation branch that the work order's kind is routed to (today `testing` for every kind). Work orders and changes of the branch list target the config branch (today `production`); everything else reaches a production branch only by [promotion](#factory-promote). The generated [branch diagram](factory-branches.md) shows the current list, gates, routing and review modes.

**Work-order references.** `7`, `007` and `FACTORY-007` all work; a reference resolves only when exactly one work order at the config branch tip matches (for `continue`, `stop` and `cancel`: one work order with runs on this device). If several match, `factory` lists them; use the full name.

**Work-order numbers.** New work orders are named `<KIND>-<NNN>.md` with the prefix `FACTORY`, `PRODUCT` or `SMOKE`. One counter serves all kinds: the next number is one higher than every number ever added on the config branch (deleted work orders keep theirs), present in the candidate's `docs/work/`, or added by an open pull request of a configured maintainer in this repository. Names without a number, such as `FACTORY-SMOKE`, do not count. Because work orders are created only on the config branch, numbers stay unique across all branches.

**Branch names.** `factory` uses and recognises:

| Branch | Created by | Meaning |
|---|---|---|
| `<login>/<ID>` | `factory start` | First implementation branch of a work order |
| `<login>/<ID>-<k>` | `factory start` | Next implementation branch once the previous one is merged |
| `<login>/<ID>-fix-<k>` | `factory fix`, `factory hotfix` | Fix branch when the work order has no open PR |
| `<login>/new-workorders` | `factory submit workorders` | Your work-order PR into the config branch |
| `<login>/config-<change>-<branch>` | `factory add … branch`, `factory remove branch` | Your config PR into the config branch; `<change>` is `add`, `change` or `remove` |
| `<login>/config-set-config-<branch>-into-<target>` | `factory set config branch` | Your two config PRs, one into the new config branch and one into the current one |

`<login>` is your GitHub login. `factory submit` derives the work order from these names; on any other branch use `--workorder`. Listed branches (validation and production branches, whose names never contain `/`) are never a working branch: `factory submit` refuses them.

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

Activates work orders. Use it after [factory issue](#factory-issue) (or after editing or deleting a work order), when the text is final. A work order authorizes work only once it is approved and merged into the config branch, because the factory reads work orders only from there.

```sh
factory submit workorders
```

What it does:

1. Collects your uncommitted changes of `docs/work/*.md` against the candidate's `HEAD`: new files, edits and deletions (the template excluded). Everything else in your checkout stays untouched.
2. Checks every file and lists all problems at once: the `factory-task` block rules of the gate (exactly one block, valid JSON, exactly `status`, `kind`, `allowed_paths`, safe non-empty paths; any status is accepted here); for new files the name `<KIND>-<NNN>.md`, a prefix matching `kind`, the first line `# <ID> – <title>` and an unused number; no template placeholder (`REPLACE-WITH-EXACT-PATHS`, `TASK-ID`, the template title and acceptance-criteria lines); at most one `factory-handoff` block, naming the file itself.
3. Shows the diff of every edited work order and asks before submitting it; asks before every deletion; asks for every draft whether it should become `approved` (and writes that into your file).
4. Commits only these files in a disposable checkout of the config branch tip on `<login>/new-workorders` (title `docs(work): add …, update …, remove …`) and pushes. Without an open PR it opens one into the config branch through `session.py submit --base <config branch>`: collision sweep, no AI preflight (two maintainer approvals decide work-order PRs), ready at once; an open draft is marked ready. The PR carries no handoff block. With your open PR it adds the commit and promotes a draft only after a passing preflight.
5. Moves the submitted files out of your working tree, because they now live on the work-order branch: only after the PR exists (for a new PR, as soon as `session.py submit` reports it; for your open PR, once the push succeeded) and only files still byte-identical to what was submitted. New files are removed; edited or deleted ones return to the version of your `HEAD`. If no PR is created (for example the preflight does not pass), the files stay in your working tree.

It does not watch the PR: a work-order PR gets no senior review. A PR into a production branch whose head is not a validation branch of this repository and that changes only `docs/work/*.md` and/or `factory/config.json` (rename sources included) is a **work-order/config PR**; a promotion stays a promotion whatever its files. Its check `factory/production/<config branch>` passes only when two different configured maintainer accounts have approved its current head (the latest review decision of each account counts; the check runs again after every review, dismissals included), and `/bypass` never applies to it. Besides that it needs only `factory/deterministic` (automatic); it never needs `/review` or an AI review, whatever the branch's review mode: a `/review` on it is refused (`work-order and config PRs need no AI review: two maintainer approvals decide them`), and its pipeline comment says the same ([branches and promotion](way-of-working.md#branches-and-promotion)). Then a maintainer merges it on GitHub with squash or rebase; `factory merge` refuses PRs into production branches. Afterwards copy the new work orders to the validation branches with [factory sync workorders](#factory-sync-workorders).

Notable refusals: no work-order changes; any validation problem (nothing is pushed); a work order whose version in your `HEAD` differs from the config branch or your open work-order PR (merge `origin/<config branch>` into the candidate first); the candidate is itself on `<login>/new-workorders`; your open work-order PR targets another branch than the config branch (close it, then submit again); a conflict with the config branch on your open work-order PR. If `<login>/new-workorders` exists on GitHub with commits that are not on the config branch and has no open PR, `factory` lists those commits and replaces the branch only after you confirm (with `--force-with-lease`).

## factory start workorder

Starts the isolated author on an approved, merged work order as a background run and attaches to it. Use it when the work order is merged into the config branch with status `approved` (and [synced](#factory-sync-workorders) to the validation branches) and you want the factory to implement it.

```sh
factory start workorder 7
factory start workorder FACTORY-007
```

Before the run starts, `factory` checks in the foreground: the work order exists at the current config branch tip and is `approved` (`product` only when the north star and product checks are ready), no run for it is active, Docker runs and the factory image exists, and both author keys are available. The run's **target** is the validation branch routed for the work order's kind (today `testing`). The branch is the newest `<login>/<ID>` or `<login>/<ID>-<k>` not yet merged into the target (continued; it must contain the target's current tip), otherwise a new one from the target's tip.

The run then goes: **author** (`factory-start`, then `factory-change` for this work order, limited to its `allowed_paths`) → **advisory Astra preflight** (`session.py preflight`) → at most `max_rounds` (2) **corrections** with `factory-fix-review` while P0/P1 findings remain → **apply**. The result is applied **unstaged** to the branch in your candidate; nothing is committed or pushed. The log shows each step, one line per author tool call, a heartbeat every minute and the cost estimate ([runs](#runs-steps-budget-and-logs)). Ctrl-C only detaches; the run goes on (`factory continue 7`). Next: review `git diff`, stage what you accept, [factory submit](#factory-submit).

The isolated author cannot write the control paths (`.agents`, `.claude`, `.codex`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md`, `factory/`, `tools/factory/`). `factory` refuses a work order whose `allowed_paths` all lie there and warns when some do; such changes stay [protected factory changes](../factory/clients.md#protected-factory-changes) made by hand.

The result is **not applied** (the patch is kept in the run folder and the exact `git switch` and `git apply` commands are printed) when it changes files outside `allowed_paths`, under `.github/` or `docs/work/`, binary files, symlinks or submodules; when the candidate has uncommitted changes in tracked files, is on a branch other than the run's branch or a listed branch, or untracked files would be overwritten; when the run's branch moved since the run started; when the patch does not apply; or when the target had to be merged for the preflight of an existing branch. The remaining steps are skipped, with the reason in the log, when nothing differs from the target, more than `max_changed_files` (40) files changed, files outside the work order changed, the target moved and conflicts, the preflight could not run, or the [run budget](#runs-steps-budget-and-logs) is spent.

Notable refusals: no unique work order at the config branch tip; not approved; a run for it already active; all `allowed_paths` are control paths; Docker or image missing; a key missing; your local branch lacks commits that are on GitHub (`git pull --ff-only` first); an existing branch that does not contain the target's current tip (merge `origin/<target>` first).

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

The cancel itself changes no GitHub state. If the run already had a PR, it prints how to pause it (`gh pr ready <n> --undo`), close it, and retry a claimed review that got stuck (`gh workflow run factory.yml --ref production -f pr=<n> -f retry=true`, with the run's config branch); a review that was already claimed stays claimed. [Stop vs. cancel in the daily flow](way-of-working.md#stop-or-cancel-a-task).

## factory fix and factory hotfix

`factory fix <n> ["prompt"] [--pr N]` fixes a problem within an approved work order: it reviews the problem read-only, lets the author write a fix plan and the smallest fix inside the work order's `allowed_paths` (with a regression test and verification), runs the preflight/correction loop and applies the result unstaged. You check it and submit. Use it when a problem belongs to an approved work order and you want to look at the fix before it is pushed.

```sh
factory fix 7 "CSV export drops rows with empty tariffs"
factory fix 7 "#42"                  # a maintainer-written issue, PR or comment
factory fix 7                        # the open PR's review findings
factory hotfix 7 "Totals use the wrong VAT rate"
```

**Target.** The work order's open PR (same repository, opened by a configured maintainer, handoff naming this work order): the fix lands on its branch and keeps that PR's target branch, which must be a validation branch. With several such PRs choose one with `--pr`. A PR owned by another maintainer needs your confirmation, which names the owner. Without an open PR, a new `<login>/<ID>-fix-<k>` from the tip of the validation branch routed for the work order's kind.

**Input.** The prompt is free text, or `#N` or a GitHub URL of an issue, PR or comment in this repository written by a configured maintainer (anything else is refused; paste the text instead). Without a prompt, the open PR's newest authentic senior review of its current head plus all maintainer feedback is fixed directly; without an open PR, a read-only review against the work order's acceptance criteria comes first.

After applying, `fix` prints the exact next command, for example `factory submit --finished --title 'fix(FACTORY-007): CSV export drops rows with empty tariffs'`.

`factory hotfix` runs the same steps and then the **push gate**. It pushes automatically only if every changed file is inside `allowed_paths`, outside `.github/`, `docs/work/` and every `protected_paths` entry (and not the north star file), with no binary, symlink or submodule entry, the last preflight returned `pass` on exactly this result, the target branch did not move since (and did not have to be merged into an existing PR branch), and the branch on GitHub is unchanged (an existing PR branch still at the run's base; a new fix branch not yet present). Then it creates one commit with your candidate's Git identity, pushes it without force, fetches it into the candidate (`origin/<branch>`) and either watches the existing PR or opens a new one through `session.py submit` (preflight, ready on `pass`, watch). If any condition fails, it names them and ends exactly like `fix`. Use `hotfix` for urgent, small fixes outside the protected factory paths.

Notable refusals: an automatic correction is running on the PR (`factory/author-reservation` in progress); the PR has no senior review yet, it is still running, it has no findings, or the head moved since (give a prompt instead); the referenced text is not by a configured maintainer; the same refusals as [factory start workorder](#factory-start-workorder).

## factory review

A local, read-only review of your candidate: a list of problems, nothing changed. Use it before you submit, or to hunt a suspected problem.

```sh
factory review "Are there error paths in the CSV export without tests?"
factory review "Check the acceptance criteria" --workorder 7
```

It copies the tracked and untracked-but-not-ignored regular files of the candidate exactly as they are on disk (uncommitted changes included) and runs the read-only reviewer in the isolated container (`clients.py run --read-only`: only Read, Glob, Grep, Skill and the documentation tools, no patch). It prints a numbered list of problems with `file:line`, evidence and a minimal fix, and saves the report in `~/.local/state/aicepeak-factory/reviews/`. `--workorder` adds the work order as context. It runs in the foreground; Ctrl-C cancels it and removes its containers. It needs Docker, the image and the author keys and costs one model run (up to `max_run_cost_usd`).

Advisory only: it does not replace the preflight or the binding review. Symlinks and special files are skipped and listed. Control paths are listed as **not reviewed** where your candidate differs from the control checkout, because the container shows the reviewer the control checkout's version.

## factory submit

Commits what you staged and pushes the branch; with `--finished` opens the pull request for the work order. Use it daily to commit and push your work, and with `--finished` when the work order is done.

```sh
factory submit --title "feat(export): CSV export" --desc "Adds the endpoint and tests"
factory submit --finished
factory submit --finished --workorder 7 --draft
```

- Commits **only staged** files. The title defaults to `<ID>: <work order title>`, `--desc` becomes the body; on a branch without a work order and without `--title`, your commit editor opens. Unstaged changes stay where they are.
- Pushes the current branch to GitHub, never a listed branch and never with force.
- The work order comes from the [branch name](#daily-flow) or `--workorder` (`7`, `007` or `FACTORY-007`), read at the config branch tip. On any other branch `factory` warns and waits 5 seconds (Ctrl-C aborts); `--finished` then requires `--workorder`.
- `--finished` targets the validation branch routed for the work order's kind (today `testing`); an open PR keeps its own target. It requires that the branch contains the target's current tip. Without an open PR it runs `session.py submit --base <target>` on a disposable checkout of the pushed commit: collision sweep, advisory preflight, PR with the handoff block (runner `claude`, the work order, you as owner), ready only on `pass`, then watch while the target's gate is `full`. The PR body contains `--desc`, the work order and the commit list. Unchanged repository modules that changed Python files import directly are added as preflight context automatically; add more with `--context <path>` (repeatable). With an open PR it promotes a draft only after a passing preflight and then watches; a ready PR is only watched.
- If the preflight does not pass, no PR is opened: fix the findings and run `--finished` again, or open it as a draft with `--draft`. Ctrl-C stops watching; the PR keeps waiting for a watcher ([factory watch](#factory-watch)).

Notable refusals: detached `HEAD`; a listed branch (create a feature branch first); a branch behind or diverged from GitHub (`git pull --ff-only` or merge first); `--finished` on a branch without the target's current tip (`git merge origin/<target>`, or `gh pr update-branch <n>` for an open PR).

## factory watch

Runs the binding senior review for a PR on this device. Every ready PR waits for review until a maintainer device watches it. Use it after Ctrl-C in `submit`, after new pushes or comments, or for other maintainers' PRs.

```sh
factory watch 42
factory watch --all
```

`factory watch <pr>` runs `session.py watch --pr <pr>` from a disposable checkout of the verified config branch tip: it starts a pending review for the PR's current head through the shared claim and keeps polling until the PR is closed or `session.py`'s watch timeout (30 minutes by default) ends. A PR into a validation branch with gate `tests` has no senior review; the watch ends at once with status `no_review`. On a promotion a review is pending only after a maintainer's `/review` comment; work-order/config PRs refuse `/review` ([branches and promotion](way-of-working.md#branches-and-promotion)). Nothing re-reserves such a review, so when maintainer feedback, a moved config tip or a moved target branch made it stale, the watch does not wait: it ends with status `stale` and `factory` prints `WARNING: PR #<n>: feedback or the config branch changed after /review; comment /review again`, or, when the target branch moved (into the config branch it always moves with the config tip), ``WARNING: PR #<n>: the target branch moved after /review: update the promotion (`factory promote <validation branch>`), then comment /review again`` (with `--to <production branch>` when several production branches are listed). `--all` reviews every open PR labelled `awaiting-senior-review` once a minute (`session.py watch --pr <n> --once` each), updating the control checkout between rounds, until Ctrl-C; a stale or failed PR is reported and the others go on. Name one PR or use `--all`. Keep the Mac awake while watching.

## factory merge

Merges a PR into a validation branch with the verified, locked merge of [session.py merge](way-of-working.md#merge-rules). Use it when the required checks of the target's gate are green and you decided to merge; one PR at a time.

```sh
factory merge 42 --dry-run     # the verdict only
factory merge 42
```

It verifies the required checks of the target's gate (`full`: `factory/deterministic` and `factory/senior-review`; `tests`: `factory/deterministic`), each passed for exactly this head, the current target tip and the current config tip, normally or by an authentic maintainer `/bypass` (it counts only while its comment is still that maintainer's unedited `/bypass` on this PR; otherwise the verdict says `` <check>: the `/bypass` comment was edited or deleted; post a new `/bypass` ``); that the head contains the target's tip; the handoff, maintainer feedback and open threads. It then takes the target's merge lock `refs/tags/factory-merge-lock--<branch>` and merges with `--match-head-commit`. After a merge it fetches the target into the candidate; update your branches from `origin/<target>` when you continue. The exit code is non-zero when the PR is not mergeable, also with `--dry-run`. When a check differs only in the config tip, the config branch moved after that run: the verdict says that a fresh run is dispatched automatically and names the fallback if none arrives, `gh workflow run factory.yml --repo <repository> --ref <config branch> -f pr=<n> -f retry=true`.

Notable refusals: a PR into a production branch (maintainers merge those on GitHub); a PR into a gate `none` or unlisted branch; a PR from a listed branch.

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

Checks: the shim on `PATH` is the installed one; control and candidate are separate repositories; the candidate checkout is usable (plain clone, configured repository, allowed local Git configuration, local `user.name`/`user.email`); both author keys (exported or in the keychain); Docker running and the factory image (like every author run, it starts a stopped Docker Desktop, wakes it from its resource saver and waits up to 2 minutes, and prints the `docker build` command only for an image that is really missing); the pinned `codex-cli 0.164.0`; your `gh` login is a configured maintainer with write access. The control checkout is verified before every command anyway. It then runs `doctor.py` from a disposable checkout of the config branch tip (which also validates the branch model) and summarises its status and each blocked check with its fix, including one command that installs missing pinned check tools. `doctor.py` sees only exported author keys (`factory doctor` marks those two checks as expected when the keychain holds the keys) and always exits with code 2 because it never certifies live acceptance ([check the tools](dev-setup.md#check-the-tools)). `factory doctor` exits 0 when all of its own checks pass.

## factory promote

Promotes a validation branch into a production branch: first it brings the production branch into the validation branch, then it opens the promotion PR. Use it when the state of a validation branch (today `testing`) should go to production. It never merges a pull request.

```sh
factory promote testing
factory promote testing --to production     # --to is needed only when several production branches are listed
```

It works in two passes; run the same command again after the first:

1. **Production not yet contained.** When the production tip is not an ancestor of the validation branch on GitHub, `factory` merges it in the candidate. The candidate must be clean (no uncommitted or untracked files). It switches to the validation branch (created from GitHub's tip if it is missing locally, fast-forwarded if it is behind) and creates the merge commit `Merge <production> into <validation> for promotion` with your candidate's Git identity. **Nothing is pushed:** check the merge, push it yourself with the printed `git -C <candidate> push origin <validation>` (maintainers may push to validation branches), then run the command again to open or update the promotion PR. On conflicts the merge is left in the candidate and the conflicting files are listed: resolve them, `git add` and `git commit` (or give up with `git merge --abort`), push, and run the command again. If your local validation branch already contains production but GitHub's does not, it only asks you to push; local commits that are not on GitHub yet are pushed with it, and `factory` warns about them.
2. **Production contained.** It opens the PR `<validation>` → `<production>` (title `Promote <validation> to <production>`). The body names the head, the checks and the review mode, and `factory` prints the review hint: with review mode `maintainer-manual` a maintainer comments `/review` when the PR is ready and the review must pass; with `initiated` the review is optional and starts whenever a maintainer comments `/review`; with `no` there is none. When the promotion of this validation branch is already open, it opens nothing: it prints `Promotion #<n> (<validation> → <production>) is already open and now carries <sha>` and the review hint and exits 0; that PR's checks run again on its new head.

The promotion PR runs `factory/deterministic` on every new commit with the config branch's rules. `factory/production/<production>` passes only while its head is the current tip of the validation branch, the production tip is contained in it and it is the only open promotion into that production branch, and, with review mode `maintainer-manual`, once a passed `factory/senior-review` exists for exactly this PR, head, target and config tip; a review published for another PR on the same commit never counts. When the local review finishes, the reviewing maintainer device re-runs the production check itself. When it cannot (its result dispatch failed, the wait for the coordination timed out, or it was interrupted), its message names the re-run, `gh workflow run factory-promotion.yml --repo <repository> --ref <config branch> -f pr=<n>`; the check's summary "the AI review of this head is missing" names the same command, because a review that passed since needs only this re-run, not a new `/review`. When the production tip is not contained, the check names the remedy `factory promote <validation branch>` (with `--to <production branch>` when several production branches are listed). A maintainer `/bypass <reason>` for exactly the current head overrides every one of these conditions, on every promotion, also one whose diff holds only work orders or `factory/config.json` ([branches and promotion](way-of-working.md#branches-and-promotion)). A maintainer merges it on GitHub with squash or rebase. A squash or rebase merge leaves a commit on production that the validation branch lacks, so the next promotion starts with the first pass again.

Notable refusals and warnings: the source is not a listed validation branch; several production branches are listed and `--to` is missing, or `--to` names no listed production branch; either branch is missing on GitHub; the candidate is not clean (first pass); your local and GitHub's validation branch diverged (reconcile them first); a promotion from another validation branch into that production branch is open (merge or close it first). A source with gate `none` is only warned about: its production check fails unless a maintainer comments `/bypass`.

## factory sync workorders

`factory sync workorders` copies every work order of the config branch to the validation branches that lack it; `factory sync workorder <n>` copies one. Use it after a work-order PR was merged into the config branch, before `factory start workorder`, so that every validation branch carries the work orders.

```sh
factory sync workorders
factory sync workorder 9           # 9, 009 or FACTORY-009
```

For every validation branch it compares the work orders at the config branch tip (`docs/work/<ID>.md`, regular files, the template excluded) with those at the validation branch's tip. Missing ones are added as the config branch's own Git objects, so byte-exact, in one commit per branch (`docs(work): sync FACTORY-009 from production`, with your candidate's Git identity), built in a disposable checkout and pushed directly to the validation branch without force. It never changes or deletes a file: a work order that exists there with other content is reported (`differs from production; left unchanged`) and left alone. Your candidate's working tree stays untouched. Each branch reports `up to date`, the added work orders and the pushed commit, or why it was not synced. Like any push to a validation branch, a sync moves its tip, so its open PRs need an update before their merge.

The exit code is 1 when a validation branch is missing on GitHub or could not be synced (for example because its tip moved during the push); run the command again.

Notable refusals: the config branch is missing on GitHub or has no work orders; `factory sync workorder` without a work order, or `factory sync workorders` with one; an unknown or ambiguous work-order reference.

## factory branches

Shows the branch model and writes its diagram. Use it to see how work flows, or after a change of the branch list so that the diagram follows.

```sh
factory branches
factory branches --show
```

It reads the branch list at the config branch tip and prints one row per listed branch: name, level (with default and config branch), gate or review mode, routed kinds and required checks; then the config branch, the default branch and the branch this device's control checkout follows. It writes the generated [docs/factory-branches.md](factory-branches.md) into the candidate: a Mermaid `flowchart LR` of feature branches → validation branches (gate, kinds) → production branches (review mode), dotted work-order sync arrows from the config branch, and the table. An identical file is left as it is; commit a changed one with your next change. A config PR changes only `factory/config.json` and cannot carry it, so after a change of the branch list is merged, run `factory branches` and commit the regenerated file with a later change. `--show` also writes `~/.local/state/aicepeak-factory/branches.html`, a self-contained page (inline SVG diagram, table and Mermaid source; nothing is loaded from the network), and opens it (on macOS with `open`; elsewhere it prints the path). In the SVG, every line of text stays inside its box: boxes widen to fit a long branch name, and an ungated validation branch shows `not gated` as the last line of its own box, so no arrow crosses it.

It never commits, pushes or changes the branch list; that is done by the [config PRs](#factory-add-validation-branch).

## factory use branch

Chooses the listed branch whose factory code this device runs. Use it to run the CLI version of a validation branch, or to return to the config branch, for example after the branch you followed was removed from the list.

```sh
factory use branch testing
factory use branch production
```

It switches the control checkout to the named branch, only when the control checkout is clean (untracked and ignored files included) and its local copy of that branch has no own commits: it switches (creating the local branch from GitHub's tip if needed) and fast-forwards, never resets or deletes anything, and records the branch as `branch` in `cli.json`. From then on every command verifies and fast-forwards the control checkout on that branch. Only listed production and validation branches are accepted. Rules, branch list, policy and work orders still come from the config branch tip, `session.py` and `doctor.py` still run from a checkout of that tip, and every command still acts on the candidate, whatever your current directory. Runs that already started keep their pinned export. The installer's `--branch` sets the same value.

It works from any state of the branch you follow now: unlisted, missing on GitHub, or naming an old config branch after a finished [config branch change](#factory-set-config-branch) (which is followed). An interrupted `factory use branch` (Ctrl-C, or a failed fast-forward or check after the switch) leaves a clean control checkout on the new listed branch while `cli.json` still records the old one: every other command then stops with ``control checkout … is on <new>, but it must stay on <old>, its recorded control branch: `factory use branch <listed branch>` switches it``. `factory use branch <new>` finishes the switch, and any other listed name switches on from there. If the branch you follow is later removed from the list, every command except `use`, `status`, `continue`, `stop` and `cancel` stops with the hint to run `factory use branch <config branch>`.

Notable refusals: a name that is not listed; the control checkout is not clean (remove or revert the named file yourself; `factory` never deletes files there); the control checkout is on neither its recorded branch nor a listed branch, or on a detached `HEAD` (switch it back yourself with `git -C <control> switch <recorded branch>`); the branch is not on GitHub yet; the control checkout's local branch has own commits (recreate it with the installer).

## factory add validation branch

`factory add validation branch <name> --gate full|tests|none [--kinds k1,k2]` opens a config PR that adds a validation branch, or changes the gate or routed kinds of a listed one. Use it when a new validation stage is needed, or a gate or the routing changes.

```sh
factory add validation branch staging --gate tests --kinds smoke
factory add validation branch staging --gate full --kinds smoke    # change the gate of a listed branch
```

`--gate` is `full` (deterministic tests, binding Astra review, corrections), `tests` (deterministic tests only) or `none` (not gated). `--kinds` lists the work-order kinds (`factory`, `product`, `smoke`) routed to the branch and replaces its previous list; the kinds it takes over leave their previous branch, and every kind must stay routed to exactly one validation branch. To change only the gate of a listed branch, repeat its kinds. A name has lowercase letters, digits and inner hyphens, at most 40 characters, and is neither `main`, `master`, `head` nor a maintainer login; at most 20 validation and 5 production branches.

Every config PR (this command, [add production branch](#factory-add-production-branch), [remove branch](#factory-remove-branch) and [set config branch](#factory-set-config-branch)) works the same way:

1. It reads `factory/config.json` at the config branch tip and changes only its `branches` and `config_branch` values; `tools/factory/branches.py` refuses any result that breaks the branch model. If nothing changes, it says so and stops.
2. If its branch `<login>/config-<change>-<branch>` already has an open PR, it names that PR, leaves it unchanged and stops (exit 0; close it to propose something else). An open PR that is still a draft (for example because `session.py submit` could not verify it after creating it) fails its production check while it is one: `factory` says so, names `gh pr ready <n> --repo <repository>` and exits 1. Otherwise it shows the diff.
3. It commits the file alone (title `factory(config): …`, your candidate's Git identity) on that branch from the config branch tip in a disposable checkout, pushes the branch and opens the PR into the config branch through `session.py submit --base <config branch>` without `--task`: a collision sweep, no advisory preflight (the two approvals and `factory/deterministic` decide), ready once the new PR is verified. A branch left on GitHub by an earlier attempt without a PR is reused when it holds exactly this proposal (one commit on the current config tip whose `factory/config.json` is the proposed one); otherwise `factory` lists its commits and replaces it only after you confirm (with `--force-with-lease`). Your candidate's working tree is not touched.
4. The PR body lists the owner steps after the merge, for a new branch for example: create it on GitHub from the default branch's tip (validation) or the config branch's tip (production) before applying the settings, apply the settings (`python3 tools/factory/settings.py diff`, then `apply`, from a clean checkout of the config branch), then `factory sync workorders` for a new validation branch.

It is a work-order/config PR: it needs approving reviews from two maintainer accounts at its current head and `factory/deterministic`, never `/review` (refused) or an AI review; `/bypass` never applies, and a maintainer merges it on GitHub ([factory submit workorders](#factory-submit-workorders)). `factory/deterministic` runs the config tip's trusted tests against the PR head and so against its changed `factory/config.json`; the tests never take the branch model from it (they use a fixed test model and only check that the changed one is valid), so a changed branch list or config branch does not fail them. The change counts once it is merged; open PRs keep their target. The PR does not change [docs/factory-branches.md](factory-branches.md): regenerate it with [factory branches](#factory-branches) in a later change.

Notable refusals: `--gate` missing or `--review` given; unknown or repeated `--kinds`; an invalid or reserved name; a change that would leave a kind unrouted; you decline to replace a differing branch of an earlier attempt.

## factory add production branch

`factory add production branch <name> --review no|initiated|maintainer-manual` opens a config PR that adds a production branch, or changes the review mode of a listed one. Use it when a further production branch is needed, or the AI review of promotions changes.

```sh
factory add production branch release --review maintainer-manual
factory add production branch production --review initiated     # change the review mode
```

`--review` decides the AI review (`factory/senior-review`) of promotions into the branch: `maintainer-manual` (required: a maintainer starts it with `/review`, and `factory/production/<name>` passes a promotion only after the review of its own head passed, unless a maintainer bypasses the promotion), `initiated` (optional; started by `/review` when wanted) or `no` (never offered). Work-order/config PRs never need it. The production ruleset itself requires only `factory/deterministic` and `factory/production/<name>`. The config PR works as described under [add validation branch](#factory-add-validation-branch); its owner steps create a new branch from the config branch tip, apply the settings (a production ruleset without bypass actors) and name `factory promote <validation branch> --to <name>` for its first promotion.

Notable refusals: `--review` missing, or `--gate` or `--kinds` given; an invalid or reserved name.

## factory remove branch

`factory remove branch <name>` opens a config PR that removes a branch from the branch list. Use it when a validation or production branch is retired.

```sh
factory remove branch staging
```

The kinds routed to a removed validation branch move to the default branch, and its open PRs are no longer gated. The branch itself stays on GitHub: `factory` never deletes branches; delete it yourself if you want. The owner steps apply the settings (the branch's ruleset is retired) and switch devices that follow it back with `factory use branch <config branch>`. The config PR works as described under [add validation branch](#factory-add-validation-branch).

Notable refusals: an unlisted name; the config branch, the default branch or the last production branch; a branch that `factory/config.json` on the default branch still names as the config branch, for example the old config branch after a [config branch change](#factory-set-config-branch) whose step 5 has not reached the default branch yet. The dispatcher and the installer still start from that branch, so `factory` first asks you to bring the change into the default branch: `factory promote <default branch> --to <config branch>` (its first pass merges the config branch into it; push that merge), then retry.

## factory set config branch

`factory set config branch <name>` opens the two config PRs that make another listed production branch the config branch. Use it when rules, policy and work orders should come from another production branch.

```sh
factory set config branch release
```

Both change only `config_branch`, and each works like every [config PR](#factory-add-validation-branch) (two approvals, merged on GitHub). The first goes into `<name>` (from its own `factory/config.json`, branch `<login>/config-set-config-<name>-into-<name>`), so that `<name>` names itself; the second goes into the current config branch (branch `<login>/config-set-config-<name>-into-<old>`). If `<name>` already names itself, the first is skipped as unchanged; if `<name>` already is the config branch, nothing is proposed (exit 0).

The code of every branch names the config branch in its own `factory/config.json`. A finished change is followed exactly once: when the configuration on the named branch names another listed production branch whose own configuration names itself, the dispatcher, the installer and `factory` use that branch (`branches.follow`). Any other mismatch stops them (`factory`: `… the change of the config branch is not finished`). Follow the owner steps in both PRs, in this order:

1. Right before merging, run `factory set config branch <name>` again: it reuses both PRs and refuses if the old config branch changed since (its checks run only when the PRs are proposed). Then merge the config PR into `<name>` first: `<name>` then names itself as the config branch.
2. Then merge the config PR into the old config branch: from then on the dispatcher, the installer and every device follow `<name>`.
3. Apply the settings from a clean checkout of `<name>` right away (`python3 tools/factory/settings.py diff`, then `apply`): `factory-control` and `factory-promotion` then admit only `<name>`. Until then, factory jobs fail at their environment.
4. Change the WIF rule (`ref` and `workflow_ref`, printed by `python3 tools/factory/settings.py wif`) to `refs/heads/<name>` and run the WIF smoke there.
5. Bring the change into the validation branches with the next `factory promote <validation branch> --to <name>`, which merges `<name>` into them.
6. Devices keep working and take their rules from `<name>`; a device whose control checkout runs the old config branch may switch with `factory use branch <name>`.
7. Re-run the open pull requests on `<name>`, because their checks are bound to the old config branch: `gh pr list --repo <repository> --state open --limit 1000 --json number --jq '.[].number' | xargs -I{} gh workflow run factory.yml --repo <repository> --ref <name> -f pr={} -f retry=true`, and for each production branch `<P>` the production checks of its PRs: `gh pr list --repo <repository> --state open --base <P> --limit 1000 --json number --jq '.[].number' | xargs -I{} gh workflow run factory-promotion.yml --repo <repository> --ref <name> -f pr={}`. The PR body prints both with the real names. The first push to `<name>` (for example a merged promotion) re-runs them too.

Step 7 is needed because the merge of the second config PR re-runs nothing else: the old config branch is no longer the config branch, so its push dispatches only the production checks of its own open PRs. A `factory.yml` run still in progress on the old config branch cannot act for `<name>`, because its checks bind the old config branch; the dispatcher skips it when it cancels obsolete runs, so it neither cancels it nor refuses the PR's next event.

`factory set config branch` refuses a change that would roll the policy back: `factory/config.json` on `<name>` must equal the one on the current config branch apart from `config_branch`, and `<name>` must hold every `docs/work/*.md` of the current config branch byte-identical. Otherwise it names the differing top-level keys and the missing or differing work orders, proposes nothing, and names the remedy: bring the current config branch into a validation branch `<V>` (if `<V>` does not contain it yet, `factory promote <V> --to <current>` merges it into `<V>`; push that merge; if it already does, that command would open a promotion PR instead), promote `<V>` into `<name>` (`factory promote <V> --to <name>`, merged on GitHub), then retry. It also refuses while `factory/config.json` on the default branch names a config branch other than the current one, that is while step 5 of an earlier change has not reached the default branch: `branches.follow` takes one hop only, so a further change would need two. Bring the earlier change into the default branch first with `factory promote <default branch> --to <current>`.

Notable refusals: the name is not a listed production branch (add it first with [add production branch](#factory-add-production-branch)) or is not on GitHub yet; the new branch lags behind the current config branch; the default branch still names an earlier config branch.

## Runs: steps, budget and logs

`start`, `fix` and `hotfix` run in the background, independent of the terminal; one run per work order at a time. The foreground command validates everything, writes a pinned export of the verified control commit into the run folder, starts the runner from that export and attaches. A later update of the control checkout therefore never changes a running job. On macOS, `caffeinate -i` keeps the Mac from idle-sleeping while the runner lives; closing the lid or system sleep still pauses the run.

| Kind | Steps |
|---|---|
| `start` | author → preflight → up to `max_rounds` corrections while P0/P1 findings remain → apply |
| `fix` | review (or the PR's findings) → fix → preflight/correction loop → apply |
| `hotfix` | as `fix`, then the push gate → push and PR, or apply as `fix` |

Every model step is one `clients.py run` from the pinned export, labelled `aicepeak.factory.run=<run id>` on every container, network and volume, with an event stream; review steps use `--read-only` ([launcher options](../factory/clients.md#build-and-run)). Each preflight runs on a disposable checkout of the run's commit against the run's target, with `session.py` from the newest config branch tip; if the target moved, the run first merges its new tip and stops on a conflict. Limits and protected paths come from the configuration pinned when the run started.

**Budget.** One run stays within `max_cost_usd` (USD 25) across all its model steps; each model step may use up to `max_run_cost_usd` (USD 12), enforced by the credential broker. Before every model step the run checks that the spend so far plus USD 12 still fits into USD 25; otherwise it skips the remaining model steps and applies what exists. The spend is Claude's own reported estimate (`reported_cost_usd`); a failed step or one without a reported cost counts as the full USD 12. The broker's caps stay authoritative; the displayed amounts are estimates, not invoices. Preflights and binding reviews use the maintainer's Codex seat, not this budget.

**Run folder** `~/.local/state/aicepeak-factory/runs/<ID>-<date>-<time>-<hex>/` (mode 0700):

| File | Content |
|---|---|
| `run.json` | Kind, work order, branch, base, target branch and its tip, config branch, PR, step, status, process, Docker host, spend |
| `log` | Everything shown while attached: steps (`— author`), tool calls (`· 12:03:04 Read docs/…`), heartbeats, preflight results, cost lines, next steps |
| `lock` | Held by the runner for its whole life: liveness without inspecting processes |
| `<step>.prompt`, `<step>.events`, `<step>.patch`, `<step>.patch.report.txt` | Prompt (with the work-order text), tool-call lines, patch and report of each model step (`author`, `review`, `fix`, `correction-1`, …) |
| `changes.patch` | The final patch, also when it was not applied |
| `stop` | Present after `factory stop` |

The pinned export and the run's working checkout are removed when the run ends; logs, prompts, patches and reports stay until you delete the folder. A run ends `completed`, `stopped`, `failed` or `cancelled` (exit code 0, 0, 1, 130). If the first author (or review) step fails (launcher error, timeout), the run ends `failed` and applies nothing. If a later preflight or correction step fails, the remaining review steps are skipped and the result that already exists is applied as usual.

## Trust boundary

`factory` runs with your GitHub login and author keys, so it runs only reviewed code and never executes candidate files on your host.

- **Only the control checkout.** The shim lies outside every checkout. `factory.py` exits non-zero before doing anything if it is not the installed control checkout's copy (or, for the background runner, the run's own pinned export).
- **Verified before every command.** Under an exclusive lock (60 seconds wait, then it names the holder) `factory` checks that the control checkout belongs to the configured repository, is on its control branch and is clean including untracked and ignored files (only Finder's `.DS_Store` files are tolerated), fetches the control branch and the config branch over https and fast-forwards the control checkout. It never resets or deletes files there. If the code changed, it restarts itself from the new version. `status`, `continue`, `stop` and `cancel` skip the fetch.
- **Rules from the config branch only.** Every command except those four pins the fetched config branch tip and reads the branch list, gates, routing, limits and work orders only from there. A finished change of the config branch is followed once (the configuration there names another listed production branch whose own configuration names itself). It fails closed: without that tip, when the configuration names another config branch in any other way, or when the control branch is no longer listed (except for `factory use branch`), it stops before acting.
- **Disposable checkouts.** `session.py` and `doctor.py` run from a disposable checkout of exactly the config branch tip the command pinned, and `session.py` receives the candidate only as a disposable snapshot of committed state (for `submit`, exactly the pushed commit). Both are written byte-exact from Git objects: no clone, checkout filter, hook or attribute conversion.
- **Hardened Git.** Every Git call runs without hooks, fsmonitor, global or system configuration, attribute files, replace objects, lazy fetches or submodule recursion, and reaches GitHub only over https with `gh` as credential helper. The candidate's `.git` must be a plain folder and its local configuration may contain only an allowlist of keys (repository basics, `remote.origin.url`/`fetch`, branch tracking, `user.name`/`user.email`, `pull.rebase`).
- **Explicit environments.** Trusted helpers run with `python -E -S -B` and an allowlisted environment (absolute `PATH` entries only, plus the pinned Codex directory); `CODEX_ACCESS_TOKEN` and `FACTORY_PUBLISHER_APP_PRIVATE_KEY` are passed on only when you exported them.
- **Author keys.** Taken from the environment or the keychain, handed to the background runner through a pipe, and put only into the environment of the `clients.py run` child, which gives them to the credential broker, never to the worker. They are never written to a file, log or argument.
- **GitHub input only from maintainers.** Work-order numbers, fix targets and `#N` prompts use only same-repository PRs, issues and comments by configured maintainers. Model output, tool events and GitHub text are printed only with control characters escaped.
- **Isolated author unchanged.** It cannot write control paths, cannot see your credentials and returns only a patch.
- **Pushes and merges.** `factory` never pushes to a production branch. It pushes to a validation branch only in `factory sync workorders` (adding missing work orders); `factory promote` leaves its merge commit for you to push. It never force-pushes (except the confirmed replacement of an unmerged `<login>/new-workorders` or of a config-PR branch without an open PR, with lease), merges only PRs into validation branches through `session.py merge`, never merges a PR into a production branch, never deletes branches, and never deletes files except the documented move of submitted work orders.

## Troubleshooting

| Message (after `BLOCKED:`) | Cause and fix |
|---|---|
| `factory is not installed on this device` | Run the [installer](#install). |
| `this is not the installed control checkout` | You started `factory.py` by path. Use the `factory` command. |
| `control checkout …: checkout must be clean: untracked file …` | Something wrote into the control checkout (often `__pycache__` or an editor; Finder's `.DS_Store` files are tolerated). Remove or revert the named file yourself; `factory` never deletes files there. |
| `control checkout … cannot fast-forward to origin/<branch>` | It has its own commits. Recreate it with the installer. |
| `control checkout … is on …, but it must stay on <branch>, its recorded control branch` | Someone switched it by hand, or a `factory use branch` was interrupted. On a listed branch, `factory use branch <listed branch>` finishes or reverts the switch; otherwise switch it back with `git -C <control> switch <branch>`. Change branches only with [factory use branch](#factory-use-branch). |
| `the control checkout follows …, which factory/config.json on … does not list (any more)` | The branch you follow was removed: `factory use branch <config branch>`. |
| `factory/config.json on … names the config branch …, whose own configuration does not name itself: the change of the config branch is not finished` | A [config branch change](#factory-set-config-branch) was merged in the wrong order: merge the config PR into the new config branch, then retry. |
| `the config branch … is not on GitHub` / `was never fetched` | Check your network and `gh` login. Before the owner runbook of [ADR-0008](decisions/0008-branch-model.md) is complete, the branch model is not live yet. |
| `the control checkout is busy (held by pid …)` / `the candidate checkout is busy` | Another `factory` command holds the lock. Wait for it or stop it, then retry. |
| `control and candidate checkouts share one Git repository` / `must be separate folders` | Use two separate clones, neither inside the other. |
| `candidate … has settings factory does not run with: …` | Remove each named key with `git -C <candidate> config --local --unset <key>`. |
| `candidate has no local user.name` | `git -C <candidate> config --local user.name '…'` (same for `user.email`), or rerun the installer. |
| `Docker did not answer within 120 s, not even after starting Docker Desktop` / `author image … is missing` | `factory` starts a stopped Docker Desktop itself (`Starting Docker Desktop…`), wakes it from its resource saver with one no-op container from the author image (Docker Desktop answers queries without its VM and may then call a present image missing) and waits up to 2 minutes. The message means Docker Desktop is not installed or does not start. For a missing image, `factory doctor` prints the build command. Set `FACTORY_DOCKER_HOST` only if the active Docker context is not the right endpoint. |
| `ANTHROPIC_API_KEY missing` | Rerun the installer with `--author-keys`, or export the key. |
| `a run for … is already active` | `factory continue <n>`, or `factory stop`/`cancel workorder <n>`. |
| `every allowed path of this work order is a control path` | The isolated author cannot write it: make it a [protected factory change](../factory/clients.md#protected-factory-changes). |
| `Patch kept, not applied: …` (in the run log) | Check the named reason, then run the printed `git switch` and `git apply` commands yourself. |
| `… is behind or diverged from GitHub` | `git -C <candidate> pull --ff-only` (or merge), then retry. |
| `… does not contain current <target>` | Merge `origin/<target>` into your branch (`gh pr update-branch <n>` for an open PR), then retry. |
| `never on <branch>, a listed … branch` | `factory submit` commits only on feature branches: `git -C <candidate> switch -c <login>/<ID>`. |
| `PR #… targets the production branch …: merge production PRs on GitHub` | `factory merge` merges only into validation branches; merge production PRs on GitHub. |
| `a promotion into … is already open` | A promotion from another validation branch is open: merge or close it first. An open promotion of the same validation branch is reported as updated instead. |
| `… the config branch moved after this run; a fresh run is dispatched automatically` (`factory merge`) | Wait for the fresh run and its review; if none arrives, run the printed `gh workflow run factory.yml … --ref <config branch> -f pr=<n> -f retry=true`. |
| `WARNING: PR #…: feedback or the config branch changed after /review; comment /review again` | The pending production review is stale and never re-reserved: comment `/review` on the PR again, then `factory watch <n>`. |
| `WARNING: PR #…: the target branch moved after /review: update the promotion …` | The production branch moved, so the promotion needs a new head: run the named `factory promote`, push its merge, run it again, then comment `/review` on the new head. |
| `…: the /bypass comment could not be re-read, or was edited or deleted; retry, or post a new /bypass` (`factory merge`) | A bypass counts only while its comment is unchanged. Retry when GitHub was unreachable; otherwise a maintainer posts a new `/bypass <reason>`. |
| `… cannot become the config branch yet, it would roll the policy back: …` | The new config branch lags behind the current one (configuration or work orders). Promote the current config branch into it through a validation branch as the message says, then retry ([set config branch](#factory-set-config-branch)). |
| `factory/config.json on the default branch … still names …` (`set config branch`, `remove branch`) | An earlier config branch change has not reached the default branch: run the printed `factory promote <default branch> --to <config branch>`, push its merge, then retry. |
| `the run did not start; see …/log` | Read the log; often Docker, the image or a key. |
| `command not found: factory` | Open a new terminal (PATH block) or add the shim directory to `PATH`. If the Python recorded in the shim no longer exists, rerun the installer. |
| `pinned Codex 0.164.0` fails in `factory doctor` | Install it as in [dev-setup.md, step 2](dev-setup.md#2-install-tools-and-sign-in). |
| `merge lock refs/tags/factory-merge-lock--<branch> is held` | See [merge rules](way-of-working.md#merge-rules). |

System sleep pauses runs and watchers; keep the Mac awake during long runs. `factory status` shows every run; each run's `log` has the complete history.

## Without the CLI

The CLI wraps the existing tools; for troubleshooting you can run them yourself. Run them from a clean checkout at the current config branch tip: the control checkout when it follows the config branch (the default; `git status --short --untracked-files=all --ignored` shows nothing; update with `git pull --ff-only`). `session.py` refuses any other revision. Pass the candidate checkout explicitly. Export the pinned Codex directory in that terminal (`export PATH="$HOME/.local/share/aicepeak-factory-cli/node_modules/.bin:$PATH"`).

`--base <branch>` names the listed target branch. Without it, `preflight` and `submit` use the validation branch routed for the work order's kind and `collisions` uses it too, or the default branch without `--task`. `submit --base <production branch>` opens a work-order/config PR (only `docs/work/*.md` and `factory/config.json`, no handoff block; `--task` is optional there: with it an advisory preflight runs, as for `factory submit workorders`; `factory`'s config PRs give none). `watch`, `response` and `merge` always take the target from the PR; a given `--base` must match it.

```sh
python3 tools/factory/session.py collisions --candidate ../aicepeak-candidate --task docs/work/<ID>.md
python3 tools/factory/session.py preflight --candidate ../aicepeak-candidate --task docs/work/<ID>.md
python3 tools/factory/session.py submit --candidate ../aicepeak-candidate --base testing \
  --task docs/work/<ID>.md --runner claude --title '<title>' --body-file /path/outside/checkouts/body.md
python3 tools/factory/session.py watch --pr <n>              # --once: poll once
python3 tools/factory/session.py response --pr <n> --question '<question>' --post
python3 tools/factory/session.py merge --pr <n> --dry-run
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py launch --root . --runner claude    # interactive author; needs exported keys
```

`session.py submit` needs a clean candidate whose branch is already pushed. The unattended launcher with labels, read-only mode and event stream is documented in [factory/clients.md](../factory/clients.md#build-and-run). Leftover Docker resources of a run can be listed with `docker ps -a --filter label=aicepeak.factory.run=<run id>` (likewise `docker network ls` and `docker volume ls`); `factory cancel` and `factory status` remove them for you.
