# Way of working

> This is how maintainers work with the [software factory](software-factory.md) day to day: from a work order to a merged PR, how to stop or cancel work, and how to keep parallel PRs safe. It assumes a device set up as described in [dev-setup.md](dev-setup.md), with the global `factory` command installed. Every command is described in the [command reference](factory-cli.md). The German [CONTRIBUTING.md](../CONTRIBUTING.md) describes the same flow from the author's side.

`factory` manages two checkouts of this repository for you:

- **Control checkout** (default `aicepeak-control-checkout`): trusted code on current `main`. `factory` verifies and fast-forwards it before every command and runs trusted code only from it. Never change anything in it; `factory` refuses to run while it differs from `main` ([why](software-factory.md#the-control-checkout)).
- **Candidate checkout** (default `aicepeak-candidate`): your working clone. Work orders, author results and fixes land here; you review, stage and commit here.

You no longer `cd` between them: run `factory` from anywhere, usually from the candidate. Both are created once by the [installer](factory-cli.md#install).

## Daily use, step by step

The flow is `factory issue` → `factory submit workorders` → merge → `factory start workorder` → `factory submit` → `factory submit --finished` → `factory watch` → `factory merge`.

1. **Write a work order.** One work order per feature, not per commit.

   ```sh
   factory issue --title "Export energy costs as CSV"
   ```

   `factory issue` creates `docs/work/<KIND>-<NNN>.md` in the candidate with the next free number, status `draft` and you as handoff owner, and opens it in your editor. Write goal, non-goals, acceptance criteria and the exact `allowed_paths` until you agree with them ([field rules](work/TEMPLATE.md)). A draft authorizes nothing.

2. **Activate the work order.** A work order becomes active only once it is approved and merged to `main`, because the factory reads tasks only from there.

   ```sh
   factory submit workorders
   ```

   It checks every changed work order against the gate's block rules, asks whether each draft should become `approved` (the only status the factory accepts), commits only the work orders on `<login>/new-workorders`, pushes and opens the PR with the handoff task `docs/work/FACTORY-001.md` (which allows `docs/work/`), and watches its review. Other changes in your candidate stay untouched; the submitted files move to the work-order branch. Merge the PR as in step 9. To deactivate a work order later, see [stop or cancel a task](#stop-or-cancel-a-task).

3. **Implement.** Start the [isolated author](software-factory.md#the-isolated-author-session) on the merged work order:

   ```sh
   factory start workorder 8
   ```

   The run goes author → advisory Astra preflight → at most two corrections while P0/P1 findings remain → apply, in the background. You see each step, one line per author action and the cost estimate. Ctrl-C only detaches; `factory continue 8` reattaches. The result lands **unstaged** on `<login>/<ID>` in your candidate; nothing is committed or pushed. If it cannot be applied safely (files outside `allowed_paths`, uncommitted changes, another branch checked out, …), the run keeps the patch and prints the exact commands. Candidate scripts never run on your credential-bearing host: the trusted pipeline runs the tests in an isolated job without secrets or network.

   The container keeps control files (`.agents/`, native adapters, `AGENTS.md`, `CLAUDE.md`, `factory/`, `tools/factory/`) read-only; for those the author only proposes a change, and a maintainer applies it by hand, regenerates adapters and submits a manually managed PR ([protected factory changes](../factory/clients.md#protected-factory-changes)). `factory start` refuses work orders whose `allowed_paths` all lie there.

4. **Review and stage.** In the candidate, inspect the result and the author report in the run log, and stage only what you accept. For a second opinion before submitting, ask the read-only reviewer:

   ```sh
   git diff
   git add -p
   factory review "Check the acceptance criteria" --workorder 8
   ```

5. **Commit and push.** `factory submit` commits only the staged files (title `<ID>: <work order title>` unless you give `--title`) and pushes the branch, never `main` and never with force. Repeat steps 4 and 5 as often as needed.

   ```sh
   factory submit --desc "Adds the endpoint and tests"
   ```

6. **Submit the PR.** When the work order is done:

   ```sh
   factory submit --finished
   ```

   It runs `session.py submit` on a disposable checkout of your pushed commit: a collision sweep (the branch must contain current `main`; overlaps with other open PRs go into the PR body), an advisory preflight, the PR with exactly one handoff block, ready only after `pass`, and then it watches the PR. If the preflight lacks context (for example an unchanged module the change relies on), add `--context <path>`; modules that changed Python files import directly are added automatically. If the preflight does not pass, fix the findings and run it again, or use `--draft`.

7. **Review.** Every ready PR waits for the binding review until a maintainer device watches it. Without a running watcher nothing is reviewed. After Ctrl-C, new pushes or comments:

   ```sh
   factory watch 52
   ```

   To review all waiting PRs at once, see [below](#review-all-waiting-prs).

8. **Act on findings and give feedback.** P0/P1 block and start the automatic correction where allowed. Otherwise the PR gets `needs-author-action`; fix it with `factory fix` ([details](#fix-findings-yourself)). P2 findings are hints. Ordinary PR comments, reviews and inline comments by a maintainer start a fresh review that takes them into account. To get a cited answer to a question about the PR without changing anything, run from the control checkout (it has no `factory` command):

   ```sh
   python3 tools/factory/session.py response --pr 52 --question '<question>' --post
   ```

9. **Merge one PR at a time.** Update only the PR you merge next, wait for its fresh checks and review, and merge it (see [merge rules](#merge-rules)). Leave the other open PRs until it is their turn: every update costs a fresh review, and every claimed review counts against the per-PR limit.

   ```sh
   gh pr update-branch 52              # only if main moved
   factory merge 52 --dry-run          # verdict only
   factory merge 52
   ```

   `factory` updates the control checkout itself and fetches the new `main` into the candidate; merge `origin/main` into your branches when you continue.

### Review all waiting PRs

On a set-up maintainer device (stop with Ctrl-C):

```sh
factory watch --all
```

It reviews every PR labelled `awaiting-senior-review` once a minute and updates the control checkout between rounds.

### Fix findings yourself

When a PR has `needs-author-action` (control paths, exhausted limits, conflicts, a failed author run), fix the cause named in the PR comment, then let the isolated author fix it:

```sh
factory fix 8                                      # the open PR's latest senior-review findings and maintainer feedback
factory fix 8 "CSV export drops rows with empty tariffs"
factory fix 8 "#42"                                # a maintainer-written issue, PR or comment
```

`factory fix` reviews the problem, lets the author write a fix plan and the smallest fix inside the work order's `allowed_paths`, runs the preflight/correction loop and applies the result unstaged to the open PR's branch (or a new `<login>/<ID>-fix-<k>`). Review the diff, stage what you accept and run the printed `factory submit --finished --title 'fix(<ID>): …'`; the new head starts fresh checks and a fresh review. For an urgent, small fix outside the protected paths, `factory hotfix` pushes and opens or updates the PR automatically, but only behind its [push gate](factory-cli.md#factory-fix-and-factory-hotfix); otherwise it ends like `fix`. Run `factory doctor` first if the cause was environmental.

The author uses `factory-fix-review`, which answers every point as done, disputed with evidence, or blocked. It never resolves review threads and never changes requirements or tests to make a finding disappear. Findings in control paths are fixed by hand ([protected factory changes](../factory/clients.md#protected-factory-changes)).

## Stop or cancel a task

| What you want to stop | How | What happens |
|---|---|---|
| Watching a factory run (`start`, `fix`, `hotfix`) | Ctrl-C. | Detaches only; the run goes on in the background. Reattach with `factory continue <n>`. |
| A factory run, after its current step | `factory stop workorder <n>`. | The current step finishes, every further model and review step is skipped, and what exists is applied as usual. Nothing changes on GitHub: a stopped `hotfix` pushes nothing and ends like `fix`. |
| A factory run, at once | `factory cancel workorder <n>`. | The run and its processes end immediately, every Docker container, network and volume with the run's label is removed, and nothing is applied. The cancel changes no GitHub state; a review that was already claimed stays claimed, and the command prints the retry. |
| A local review (`factory review`) | Ctrl-C. | Its containers are removed; no report is saved. |
| An interactive author session (`clients.py launch`, [without the CLI](factory-cli.md#without-the-cli)) | End the client session (exit the client or press Ctrl-C in the launcher's Terminal). | The author runs in a disposable container and never modifies your checkout. Nothing reaches GitHub until you apply and push a patch yourself. |
| A watcher, `submit` or review loop | Ctrl-C. | `session.py` stops the local reviewer and its children and prints `STOPPED: local session cancelled` (exit code 130). The PR stays `awaiting-senior-review` until a device watches again (`factory watch <n>`). A review that was already claimed counts against the per-PR review limit; if it is stuck, start a deliberate [retry](#restart-a-stuck-run). |
| A PR, temporarily | Convert it back to draft: `gh pr ready <n> --undo`. | Drafts get a blocking mark and are never approved. Mark it ready again with `gh pr ready <n>`, or with `factory submit --finished` on its branch after a passing preflight. |
| A PR, for good | Close it with a reason: `gh pr close <n> --comment '<reason>'`. | The dispatcher ignores closed PRs and the watcher ends with status `closed`. A workflow run that already started is not cancelled by the close; cancel it in the repository's Actions tab if you want to stop its costs. |
| A work order | In the candidate, change its `status` from `approved` to another value such as `draft` (or delete the file), then `factory submit workorders` and decline the approval. Close the PRs that reference it. | The engine accepts only `approved`, so every PR that references the order is blocked from then on. Numbers of deleted work orders are never reused. |

## Restart a stuck run

A stuck run is restarted deliberately, which revokes earlier results; GitHub's "Re-run jobs" is refused because it would reuse old reservations:

```sh
gh workflow run factory.yml --ref main -f pr=123 -f retry=true
```

A local factory run that hangs is ended with `factory cancel workorder <n>` and started again with `factory start workorder <n>`, which continues the newest unmerged `<login>/<ID>` branch if one exists.

## Status labels

| Signal | Meaning |
|---|---|
| `awaiting-senior-review` | Deterministic checks passed; the binding Astra review has not run yet. A maintainer starts it with `factory watch <n>`. |
| `needs-author-action` | Tests or review block, a limit is exhausted, or a control path needs a human-driven fix. The PR comment names the next step and, for a failed author run, a classified launcher reason. |
| No label, two green checks | A human decides about the merge. |

The per-PR limits behind these labels are listed in [software-factory.md](software-factory.md#limits).

## Working in parallel

Maintainers and their agents can work on several PRs at once. Parallel PRs break each other when they were each tested alone but merged together, mostly through shared files such as test modules, registries or lockfiles. The factory keeps that visible and safe:

- **Before the PR:** `factory submit --finished` (through `session.py submit`) shows overlaps with other open PRs and a shared work order; `session.py collisions` shows them without submitting ([without the CLI](factory-cli.md#without-the-cli)). Agree on the order instead of coding against unmerged changes; keep PRs small and away from shared hotspots where possible.
- **While open:** the gate fails any head that does not contain current `main`, so stale heads never look mergeable.
- **At merge time:** one merge at a time with `factory merge`. Merges through it are serialized by a lock, so two maintainers can never merge against the same `main` at once. The PR merged second updates its branch, resolves its own conflicts with `main` (with `factory fix` or your own session), and gets a fresh run and review before its merge.
- **On one device:** one factory run per work order at a time; runs for different work orders can run side by side. They share one candidate checkout, so a run applies its result only when the candidate is on `main` or that run's branch without uncommitted tracked changes; otherwise it keeps the patch and prints the commands.

## Merge rules

- Normal case: both App-bound required checks `factory/deterministic` and `factory/senior-review` are green on the current head and all threads are resolved; then a maintainer merges with their own `gh` login. `factory merge` runs `session.py merge` from a disposable checkout of the verified current `main`:

  ```sh
  factory merge <n> --dry-run   # verdict only
  factory merge <n>
  ```

  The "updates by humans only" ruleset lets `main` change only through a maintainer's PR merge, so every merge uses the maintainer bypass, which also skips GitHub's check and up-to-date rules. `merge` therefore verifies them itself and refuses unless the PR is ready, its head contains current `main`, both checks from App 5510081 are `success` with an `external_id` (`repository:PR:head:policy:run:attempt`) bound to exactly this head and current `main`, handoff and human feedback are unchanged since that review, and no review thread is open. GitHub's merge pins only the head, never the base, so `merge` first takes the lock `refs/tags/factory-merge-lock` (GitHub creates a ref atomically and refuses an existing one), re-checks `main`, the PR, both checks and the threads while holding it, merges with `--admin --match-head-commit <head>`, releases the lock, compares the merge commit's parents with the verified `main` and head, and records the result as a PR comment. If GitHub gives no answer to the merge (timeout, abort), the lock stays, because GitHub may still merge; a held lock therefore means another merge is running or its outcome is unknown. Check the named PR (merged: verify `main`; certainly not merged: fine), then remove the lock with `gh api -X DELETE repos/Zerosteps1/Aicepeak_V2.0.0/git/refs/tags/factory-merge-lock`. If `main` moved, use "Update branch" and wait for the fresh checks and review.
- Stuck PR (no reviewer device, model failure, exhausted limits): a maintainer may merge deliberately through the ruleset bypass. This is outside the `factory merge` guarantee: it takes no lock and does not re-validate against the `main` it lands on. Write the reason as a PR comment first; GitHub records every bypass. A bypassed PR has no independent review, so use this sparingly.
- Never: direct pushes to `main`, auto-merge, agent or bot merges, or changing protection rules to force a green result.

## Verify locally

Full local verification of the control checkout (needs `actionlint` and `gitleaks`), run from the control checkout without leaving files behind:

```sh
python3 tools/factory/verify.py --root .
python3 -I -B -m unittest discover -s tools/factory/tests
```

The structural check of your candidate, using only the control checkout's verifier:

```sh
python3 tools/factory/verify.py --root ../aicepeak-candidate --trusted-root . --structure-only
```

After changing skills or roles in `.agents/` (a protected factory change, in the candidate), regenerate and check the native adapters with the control checkout's tools:

```sh
python3 tools/factory/clients.py sync --root ../aicepeak-candidate
python3 tools/factory/clients.py check --root ../aicepeak-candidate
```
