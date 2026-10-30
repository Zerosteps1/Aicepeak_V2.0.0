# Way of working

> This is how maintainers work with the [software factory](software-factory.md) day to day: from a work order to a merged PR, how to stop or cancel work, and how to keep parallel PRs safe. It assumes a device set up as described in [dev-setup.md](dev-setup.md). The German [CONTRIBUTING.md](../CONTRIBUTING.md) describes the same flow from the author's side.

You work with two clones of this repository:

- **Control checkout** (`Aicepeak-factory`): stays on current `main` with no local changes. Run all commands in this document from here. The factory tools refuse to run in a checkout that has changes ([why](software-factory.md#the-control-checkout)).
- **Candidate checkout** (`Aicepeak-candidate`): a second clone on a feature branch. This is where you apply, commit and push the author's patch.

Both are created once during [device setup](dev-setup.md#create-the-control-checkout).

## Daily use, step by step

You already have `factory-start`, `factory-change`, `factory-review` and `factory-fix-review`, use them inside the [isolated author session](software-factory.md#the-isolated-author-session), a Claude Code session in a disposable container without access to your credentials: start it from the control checkout and tell it which skill to use for which work order.

```sh
python3 tools/factory/clients.py launch --root . --runner claude
```

When you end the session, the launcher prints JSON whose `patch` field is the path of the patch file. The author's explanation stays only in the session, so keep it.

1. **Generate a work order.** One work order per feature, not per commit. Start the author session and ask:
    > Use factory-start to draft `docs/work/<TASK-ID>.md` from `docs/work/TEMPLATE.md` for: \<goal>. Leave the status at `draft`.
    
    Apply the returned patch in the candidate checkout as in step 4, but do not commit yet. Read the draft and correct goal, non-goals, acceptance criteria and `allowed_paths` until you agree with them. A draft authorizes nothing.

2. **Activate the work order.** The status is set in the `factory-task` block at the top of the work order. In the candidate checkout, change `"status":"draft"` to `"status":"approved"`:

   ```factory-task
   {"status":"approved","kind":"factory","allowed_paths":["docs/"]}
   ```

   Change only `status`; `kind` and `allowed_paths` stay as drafted. `approved` is the only status the factory accepts; any other value blocks every PR that references the work order ([field rules](work/TEMPLATE.md)). The work order becomes active only once it is merged to `main`, because the factory reads tasks only from there. So commit and push it, submit it as a PR of its own with the handoff task `docs/work/FACTORY-001.md` (which allows `docs/work/`), and merge it as in step 9:

   ```sh
   cd ../Aicepeak-candidate
   git add docs/work/<TASK-ID>.md
   git commit -m 'docs(work): add <TASK-ID>'
   git push -u origin HEAD
   cd ../Aicepeak-factory
   python3 tools/factory/session.py submit --candidate ../Aicepeak-candidate \
     --task docs/work/FACTORY-001.md --runner claude \
     --title 'docs(work): add <TASK-ID>' --body-file /path/to/pr-body.md
   ```

   To deactivate a work order later, see [stop or cancel a task](#stop-or-cancel-a-task).
  
3. **Implement.** Start the author session and ask: "Use factory-change for `docs/work/<TASK-ID>.md`". The launcher copies the trusted checkout into a fresh container, applies the trusted control overlays and does not modify your checkout. For an unattended run with a saved author report use `clients.py run`, which takes the candidate (`--root`) and the trusted base (`--policy-root`) separately ([clients](../factory/clients.md#build-and-run)).

4. **Apply the patch to a candidate branch.** Inspect the patch and the author's explanation, apply only the changes the work order allows, commit and push. Do not run candidate scripts on your credential-bearing host: the trusted pipeline runs the tests in an isolated job without secrets or network. The structural check below uses only the control checkout's verifier.

   ```sh
   cd ../Aicepeak-candidate
   git fetch origin
   git switch -c <branch> origin/main
   git apply --check /path/to/changes.patch
   git apply /path/to/changes.patch
   git diff
   git add -A
   git commit -m '<type>(<scope>): <change>'
   git push -u origin HEAD
   cd ../Aicepeak-factory
   python3 tools/factory/verify.py --root ../Aicepeak-candidate --trusted-root . --structure-only
   ```

   The container keeps control files (`.agents/`, native adapters, `AGENTS.md`, `CLAUDE.md`, `factory/`, `tools/factory/`) read-only; for those the author only proposes a change, and a maintainer applies it in an ordinary checkout, regenerates adapters and submits a manually managed PR ([protected factory changes](../factory/clients.md#protected-factory-changes)).

5. **Check for collisions, then submit.** `collisions` reports whether the candidate contains current `main`, which files a merge of `main` would conflict in, and, for every other open PR, shared files, a shared work order and trial-merge conflicts. It only reads both checkouts. Resolve conflicts with `main` in the candidate (merge `main`, fix, commit, push); never adapt the candidate to an unmerged PR.

   ```sh
   python3 tools/factory/session.py collisions --candidate ../Aicepeak-candidate --task docs/work/<TASK-ID>.md
   python3 tools/factory/session.py submit --candidate ../Aicepeak-candidate \
     --task docs/work/<TASK-ID>.md --runner claude \
     --title '<type>(<scope>): <change>' --body-file /path/to/pr-body.md
   ```

   `submit` repeats the collision sweep, runs the advisory preflight, creates a draft, marks it ready only after `pass` and a fresh head/base check, records the result in the PR body and then watches the PR. If the preflight lacks context (for example an unchanged module the change relies on), add `--context <path>`. `session.py preflight` runs the same advisory preflight without opening a PR.

6. **Review.** Every ready PR waits for the binding review until a maintainer device watches it. Without a running watcher nothing is reviewed. To review all waiting PRs at once, see [below](#review-all-waiting-prs).

   ```sh
   python3 tools/factory/session.py watch --pr <n>
   ```

7. **Act on findings.** P0/P1 block and start the automatic correction where allowed. Otherwise the PR gets `needs-author-action`; start the author session and ask: "Use factory-fix-review for PR #<n>" ([details](#fix-findings-yourself)). P2 findings are hints.

8. **Give feedback.** Ordinary PR comments, reviews and inline comments by a maintainer start a fresh review that takes them into account. To get a cited answer to a question about the PR, without changing anything:

   ```sh
   python3 tools/factory/session.py response --pr <n> --question '<question>' --post
   ```

9. **Merge one PR at a time.** Update only the PR you merge next, wait for its fresh checks and review, merge it (see [merge rules](#merge-rules)) and update the control checkout. Leave the other open PRs until it is their turn: every update costs a fresh review, and every claimed review counts against the per-PR limit.

   ```sh
   gh pr update-branch <n>                                      # only if main moved
   python3 tools/factory/session.py merge --pr <n> --dry-run    # verdict only
   python3 tools/factory/session.py merge --pr <n>
   git pull --ff-only
   ```

### Review all waiting PRs

On a set-up maintainer device (stop with Ctrl-C):

```sh
while true; do
  for pr in $(gh pr list --label awaiting-senior-review --json number --jq '.[].number'); do
    python3 tools/factory/session.py watch --pr "$pr" --once
  done
  sleep 60
done
```

### Fix findings yourself

When a PR has `needs-author-action` (control paths, exhausted limits, conflicts, a failed author run), fix the cause named in the PR comment, check out the current branch fresh and start the author again with the `factory-fix-review` skill:

```sh
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py launch --root . --runner claude
# In the client: factory-fix-review for PR #<n>, the current work order and its findings.
```

`factory-fix-review` answers every point as done, disputed with evidence, or blocked. It never resolves review threads and never changes requirements or tests to make a finding disappear. Apply and push the patch as in step 4; the new head starts fresh checks and a fresh review.

## Stop or cancel a task

| What you want to stop | How | What happens |
|---|---|---|
| A running author session | End the interactive client session (exit the client or press Ctrl-C in the launcher's Terminal). | The author runs in a disposable container and never modifies your checkout. Nothing reaches GitHub until you apply and push a patch yourself. |
| A watcher, `submit` or review loop | Ctrl-C. | `session.py` stops the local reviewer and its children and prints `STOPPED: local session cancelled` (exit code 130). The PR stays `awaiting-senior-review` until a device watches again. A review that was already claimed counts against the per-PR review limit; if it is stuck, start a deliberate [retry](#restart-a-stuck-run). |
| A PR, temporarily | Convert it back to draft: `gh pr ready <n> --undo`. | Drafts get a blocking mark and are never approved. Mark it ready again with `gh pr ready <n>`. |
| A PR, for good | Close it with a reason: `gh pr close <n> --comment '<reason>'`. | The dispatcher ignores closed PRs and `session.py watch` ends with status `closed`. A workflow run that already started is not cancelled by the close; cancel it in the repository's Actions tab if you want to stop its costs. |
| A work order | In a PR of its own (handoff task `docs/work/FACTORY-001.md`), change the order's `status` from `approved` to another value such as `draft`. Close the PRs that reference it. | The engine accepts only `approved`, so every PR that references the order is blocked from then on. |

## Restart a stuck run

A stuck run is restarted deliberately, which revokes earlier results; GitHub's "Re-run jobs" is refused because it would reuse old reservations:

```sh
gh workflow run factory.yml --ref main -f pr=123 -f retry=true
```

## Status labels

| Signal | Meaning |
|---|---|
| `awaiting-senior-review` | Deterministic checks passed; the binding Astra review has not run yet. A maintainer starts it with `session.py watch --pr <n>`. |
| `needs-author-action` | Tests or review block, a limit is exhausted, or a control path needs a human-driven fix. The PR comment names the next step and, for a failed author run, a classified launcher reason. |
| No label, two green checks | A human decides about the merge. |

The per-PR limits behind these labels are listed in [software-factory.md](software-factory.md#limits).

## Working in parallel

Maintainers and their agents can work on several PRs at once. Parallel PRs break each other when they were each tested alone but merged together, mostly through shared files such as test modules, registries or lockfiles. The factory keeps that visible and safe:

- **Before the PR:** `session.py collisions` (and `submit`) shows overlaps with other open PRs and a shared work order. Agree on the order instead of coding against unmerged changes; keep PRs small and away from shared hotspots where possible.
- **While open:** the gate fails any head that does not contain current `main`, so stale heads never look mergeable.
- **At merge time:** one merge at a time with `session.py merge`. Merges through it are serialized by a lock, so two maintainers can never merge against the same `main` at once. The PR merged second updates its branch, resolves its own conflicts with `main` (with `factory-fix-review` or your own session), and gets a fresh run and review before its merge.

## Merge rules

- Normal case: both App-bound required checks `factory/deterministic` and `factory/senior-review` are green on the current head and all threads are resolved; then a maintainer merges from the clean control checkout on current `main`, with their own `gh` login:

  ```sh
  python3 tools/factory/session.py merge --pr <n> --dry-run   # verdict only
  python3 tools/factory/session.py merge --pr <n>
  ```

  The "updates by humans only" ruleset lets `main` change only through a maintainer's PR merge, so every merge uses the maintainer bypass, which also skips GitHub's check and up-to-date rules. `merge` therefore verifies them itself and refuses unless the PR is ready, its head contains current `main`, both checks from App 5510081 are `success` with an `external_id` (`repository:PR:head:policy:run:attempt`) bound to exactly this head and current `main`, handoff and human feedback are unchanged since that review, and no review thread is open. GitHub's merge pins only the head, never the base, so `merge` first takes the lock `refs/tags/factory-merge-lock` (GitHub creates a ref atomically and refuses an existing one), re-checks `main`, the PR, both checks and the threads while holding it, merges with `--admin --match-head-commit <head>`, releases the lock, compares the merge commit's parents with the verified `main` and head, and records the result as a PR comment. If GitHub gives no answer to the merge (timeout, abort), the lock stays, because GitHub may still merge; a held lock therefore means another merge is running or its outcome is unknown. Check the named PR (merged: verify `main`; certainly not merged: fine), then remove the lock with `gh api -X DELETE repos/Zerosteps1/Aicepeak_V2.0.0/git/refs/tags/factory-merge-lock`. If `main` moved, use "Update branch" and wait for the fresh checks and review.
- Stuck PR (no reviewer device, model failure, exhausted limits): a maintainer may merge deliberately through the ruleset bypass. This is outside the `session.py merge` guarantee: it takes no lock and does not re-validate against the `main` it lands on. Write the reason as a PR comment first; GitHub records every bypass. A bypassed PR has no independent review, so use this sparingly.
- Never: direct pushes to `main`, auto-merge, agent or bot merges, or changing protection rules to force a green result.

## Verify locally

Full local verification of the control checkout (needs `actionlint` and `gitleaks`):

```sh
python3 tools/factory/verify.py --root .
python3 -I -B -m unittest discover -s tools/factory/tests
```

After changing skills or roles in `.agents/`, regenerate and check the native adapters:

```sh
python3 tools/factory/clients.py sync --root .
python3 tools/factory/clients.py check --root .
```
