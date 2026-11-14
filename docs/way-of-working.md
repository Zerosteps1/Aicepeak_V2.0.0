# Way of working

> This is how maintainers work with the [software factory](software-factory.md) day to day: from a work order to a merged PR, how to stop or cancel work, and how to keep parallel PRs safe. It assumes a device set up as described in [dev-setup.md](dev-setup.md), with the global `factory` command installed. Every command is described in the [command reference](factory-cli.md). The German [CONTRIBUTING.md](../CONTRIBUTING.md) describes the same flow from the author's side.

`factory` manages two checkouts of this repository for you:

- **Control checkout** (default `aicepeak-control-checkout`): trusted CLI code on the branch you follow, by default the config branch `production` ([factory use branch](factory-cli.md#factory-use-branch)). `factory` verifies and fast-forwards it before every command and runs trusted code only from it. Never change anything in it; `factory` refuses to run while it differs from that branch ([why](software-factory.md#the-control-checkout)). Every rule comes from the config branch tip; work orders are GitHub issues.
- **Candidate checkout** (default `aicepeak-candidate`): your working clone. Author results and fixes land here; you review, stage and commit here.

You no longer `cd` between them: run `factory` from anywhere, usually from the candidate. Both are created once by the [installer](factory-cli.md#install).

## Daily use, step by step

The flow is an issue from the "Factory work order" template → `/review` and `/accept` on the issue → `factory start workorder` → `factory submit` → `factory submit --finished` → `factory watch` → `factory merge` → later `factory promote` → `factory update`. Which branch each step targets is explained under [branches and promotion](#branches-and-promotion). Work orders are GitHub issues ([ADR-0009](decisions/0009-issues-as-work-orders.md)); the issue number is the work order's ID. The examples use issue **57** (texts write `#57`; in the shell write `57` or `"#57"`, because `#` after a space starts a comment) and pull request **42**.

1. **Write a work order.** One work order per feature, not per commit. On GitHub, open a new issue with the **"Factory work order"** template ([.github/ISSUE_TEMPLATE/factory-task.md](../.github/ISSUE_TEMPLATE/factory-task.md)): write goal, non-goals, acceptance criteria and verification, and set the `kind` in its `factory-task` block (`factory`, `product` or `smoke`; `status` stays `draft`, `allowed_paths` stays empty). Only issues opened by a configured maintainer count; a draft authorizes nothing.

2. **Let the factory review it, then accept it.** Comment on the issue:

   ```text
   /review
   ```

   The factory's issue reviewer (Claude Sonnet, without tools, answering in schema-bound JSON) posts two comments as the publisher App: a proposal of `allowed_paths` with a reason for each (new paths and control paths are marked), and a list of unclear, weak or missing sections, each with a proposed text. Copy what you agree with into the description by hand and comment `/review` again; each review costs one model call, at most `limits.max_issue_reviews` per issue. When the proposal is right, comment:

   ```text
   /accept
   ```

   Once as many maintainer accounts as `work_order_approvals` in `factory/config.json` names (today 1) have accepted the newest proposal of the unchanged issue, the factory writes the proposed paths and `status: approved` into the `factory-task` block (shown as the App in the description's edit history) and posts the approval. Any later edit of the title or the description withdraws the approval until you `/review` and `/accept` again. A `status` set to `approved` by hand counts for nothing. Once the issue has used all `limits.max_issue_reviews` reviews and you edited it after the newest proposal, comment `/accept-force` instead: it accepts that proposal for the edited issue, and only then.

   To withdraw a work order later, see [stop or cancel a task](#stop-or-cancel-a-task).

3. **Implement.** Start the [isolated author](software-factory.md#the-isolated-author-session) on the approved work order, here issue #57:

   ```sh
   factory start workorder 57
   ```

   The run goes author → advisory Astra preflight → at most two corrections while P0/P1 findings remain → apply, in the background. You see each step, one line per author action and the cost estimate. Ctrl-C only detaches; `factory continue workorder 57` reattaches. The result lands **unstaged** on the issue's branch `57-<issue title>` (for example `57-export-energy-costs-as-csv`, named as GitHub names an issue's branch; an existing branch of the issue is continued), branched from the validation branch routed for the work order's kind (today `testing`), in your candidate; nothing is committed or pushed. If it cannot be applied safely (files outside `allowed_paths`, uncommitted changes, another branch checked out, …), the run keeps the patch and prints the exact commands. Candidate scripts never run on your credential-bearing host: the trusted pipeline runs the tests in an isolated job without secrets or network.

   The container keeps control files (`.agents/`, native adapters, `AGENTS.md`, `CLAUDE.md`, `factory/`, `tools/factory/`) read-only; for those the author only proposes a change, and a maintainer applies it by hand, regenerates adapters and submits a manually managed PR ([protected factory changes](../factory/clients.md#protected-factory-changes)). `factory start` refuses work orders whose `allowed_paths` all lie there.

4. **Review and stage.** In the candidate, inspect the result and the author report in the run log, and stage only what you accept. For a second opinion before submitting, ask the read-only reviewer:

   ```sh
   git diff
   git add -p
   factory review workorder 57 "Check the acceptance criteria"
   ```

5. **Commit and push.** `factory submit` commits only the staged files (title `<issue title> #57` unless you give `--title`) and pushes the branch, never a listed branch and never with force. Repeat steps 4 and 5 as often as needed.

   ```sh
   factory submit --desc "Adds the endpoint and tests"
   ```

6. **Submit the PR.** When the work order is done:

   ```sh
   factory submit --finished
   ```

   It runs `session.py submit` on a disposable checkout of your pushed commit against the PR's target, the validation branch routed for the work order's kind (today `testing`): a collision sweep (the branch must contain the target's current tip; overlaps with other open PRs into it go into the PR body), an advisory preflight, the PR with exactly one handoff block, ready only after `pass`, and then it watches the PR. Unchanged modules that changed Python files import directly are added to the preflight automatically. If the preflight does not pass, no PR is opened: fix the findings and run it again. One work order is one PR: its body says `Closes #57`, so its merge closes the work-order issue ([details](factory-cli.md#factory-submit)).

7. **Review.** Every ready PR into a validation branch with gate `full` (today `testing`) waits for the binding review until a maintainer device watches it. Without a running watcher nothing is reviewed. A gate `tests` branch runs only the deterministic tests. After Ctrl-C, new pushes or comments:

   ```sh
   factory watch 42
   ```

   To review all waiting PRs at once, see [below](#review-all-waiting-prs).

8. **Act on findings and give feedback.** P0/P1 block and start the automatic correction where allowed. Otherwise the PR gets `needs-author-action`; fix it with `factory fix` ([details](#fix-findings-yourself)). P2 findings are hints. Ordinary PR comments, reviews and inline comments by a maintainer start a fresh review that takes them into account. To ask a question about the PR without changing anything, use a manual Claude session, for example the isolated interactive session on the PR's branch in your candidate (`python3 tools/factory/clients.py launch --root . --runner claude`, [without the CLI](factory-cli.md#without-the-cli)); its answer is advisory and authorizes nothing.

9. **Merge one PR at a time.** Update only the PR you merge next, wait for its fresh checks and review, and merge it into the validation branch (see [merge rules](#merge-rules)). Leave the other open PRs until it is their turn: every update costs a fresh review, and every claimed review counts against the per-PR limit.

   ```sh
   gh pr update-branch 42              # only if testing moved
   factory merge 42 --dry-run          # verdict only
   factory merge 42
   ```

   `factory` updates the control checkout itself and fetches the new tip of the target into the candidate; merge `origin/testing` into your branches when you continue. Merging the PR into `testing`, the GitHub default branch, closes its work-order issue: the work order is done. Follow-up work is a new work order.

10. **Promote.** When the validation branch holds what should go to production, run `factory promote testing` and follow [branches and promotion](#branches-and-promotion). After the promotion is merged with a merge commit, run `factory update testing` in the candidate and push it.

### Review all waiting PRs

On a set-up maintainer device (stop with Ctrl-C):

```sh
factory watch --all
```

It reviews every PR labelled `awaiting-senior-review` once a minute and updates the control checkout between rounds.

### Fix findings yourself

When a PR has `needs-author-action` (control paths, exhausted limits, conflicts, a failed author run), fix the cause named in the PR comment, then let the isolated author fix it:

```sh
factory fix workorder 57                           # the open PR's latest senior-review findings and maintainer feedback
factory fix workorder 57 "CSV export drops rows with empty tariffs"
factory fix workorder 57 "#42"                     # a maintainer-written issue, PR or comment
```

`factory fix` reviews the problem, lets the author write a fix plan and the smallest fix inside the work order's `allowed_paths`, runs the preflight/correction loop and applies the result unstaged to the open PR's branch (before the PR exists, to the issue's branch; a fix never opens a second branch or PR). Review the diff, stage what you accept and run the printed `factory submit --finished --title '<problem> #57'`; the new head starts fresh checks and a fresh review. For an urgent, small fix outside the protected paths, `factory hotfix workorder 57` pushes and opens or updates the PR automatically, but only behind its [push gate](factory-cli.md#factory-fix-and-factory-hotfix) and only when the PR's or issue's branch is already on GitHub; otherwise it ends like `fix`. A problem without a work order is a `factory hotfix "<problem>"`: it pushes a branch `hotfix/<date>-…` from the default branch and opens no PR; the maintainer in charge merges it or opens a PR as they see fit. Run `factory doctor` first if the cause was environmental.

The author uses `factory-fix-review`, which answers every point as done, disputed with evidence, or blocked. It never resolves review threads and never changes requirements or tests to make a finding disappear. Findings in control paths are fixed by hand ([protected factory changes](../factory/clients.md#protected-factory-changes)).

## Stop or cancel a task

| What you want to stop | How | What happens |
|---|---|---|
| Watching a factory run (`start`, `fix`, `hotfix`) | Ctrl-C. | Detaches only; the run goes on in the background. Reattach with `factory continue workorder <issue>` (`factory continue hotfix` for a hotfix without a work order). |
| A factory run, after its current step | `factory stop workorder <issue>` (or `factory stop hotfix`). | The current step finishes, every further model and review step is skipped, and what exists is applied as usual. Before a hotfix's push gate nothing changes on GitHub: a stopped `hotfix` pushes nothing and ends like `fix`; after it, the push and the PR finish and only the watch is interrupted. |
| A factory run, at once | `factory cancel workorder <issue>` (or `factory cancel hotfix`). | The run and its processes end immediately, every Docker container, network and volume with the run's label is removed, and nothing is applied. The cancel changes no GitHub state; a review that was already claimed stays claimed, and the command prints the retry. |
| A local review (`factory review`) | Ctrl-C. | Its containers are removed; no report is saved. |
| An interactive author session (`clients.py launch`, [without the CLI](factory-cli.md#without-the-cli)) | End the client session (exit the client or press Ctrl-C in the launcher's Terminal). | The author runs in a disposable container and never modifies your checkout. Nothing reaches GitHub until you apply and push a patch yourself. |
| A watcher, `submit` or review loop | Ctrl-C. | `session.py` stops the local reviewer and its children and prints `STOPPED: local session cancelled` (exit code 130). The PR stays `awaiting-senior-review` until a device watches again (`factory watch <n>`). A review that was already claimed counts against the per-PR review limit; if it is stuck, start a deliberate [retry](#restart-a-stuck-run). |
| A PR, temporarily | Convert it back to draft: `gh pr ready <n> --undo`. | Drafts get a blocking mark and are never approved. Mark it ready again with `gh pr ready <n>`, or with `factory submit --finished` on its branch after a passing preflight. |
| A PR, for good | Close it with a reason: `gh pr close <n> --comment '<reason>'`. | The dispatcher ignores closed PRs and the watcher ends with status `closed`. A workflow run that already started is not cancelled by the close; cancel it in the repository's Actions tab if you want to stop its costs. |
| A work order | Close its issue, or edit it (any edit withdraws the approval until `/review` and `/accept` again). Close the PR that references it. | Every stage re-checks the pinned issue, so a PR that references a closed or edited work-order issue is blocked at its next stage and `factory merge` refuses it. Merging its PR into the default branch closes its issue too: the work order is done, and follow-up work is a new work order. Reopening an issue you withdrew, like accepting it again after an edit, starts no PR run (issue events trigger none): [restart](#restart-a-stuck-run) a PR whose stage failed while the issue was closed. |

## Restart a stuck run

A stuck run is restarted deliberately, which revokes earlier results; GitHub's "Re-run jobs" is refused because it would reuse old reservations, and re-running a dispatcher run never repeats a `/review` or `/bypass` (it fails with "a re-run never repeats a command; post a new comment"):

```sh
gh workflow run factory.yml --ref production -f pr=123 -f retry=true
```

Every factory job runs on the config branch (`--ref production`), whatever the PR's target. A moved config tip needs no retry: a push to the config branch re-runs every open PR into a gated validation branch or another production branch by itself ([branches and promotion](#branches-and-promotion)); `factory merge` names this retry only as the fallback when no fresh run arrives. Only after a change of the config branch does the owner re-run the open PRs on the new one, as the last owner step of [factory set config branch](factory-cli.md#factory-set-config-branch).

A local factory run that hangs is ended with `factory cancel workorder <issue>` and started again with `factory start workorder <issue>`, which continues the issue's branch.

## Branches and promotion

Changes travel in three levels ([diagram](factory-branches.md), [decision](decisions/0008-branch-model.md)):

1. **Issue branch** (`57-<issue title>`, named as GitHub names an issue's branch): where you and the author work on one work order. Its one PR targets the validation branch that the work order's kind is routed to.
2. **Validation branch** (today `testing`, the GitHub default branch): protected and gated automatically. Gate `full` runs the deterministic tests, the binding Astra review and corrections; gate `tests` runs only the deterministic tests; gate `none` runs nothing. Maintainers may also push to it directly.
3. **Production branch** (today `production`): protected; nobody pushes to it. It receives only promotions from a validation branch and config PRs.

All rules come from the **config branch** (today `production`): the gate code, `factory/config.json` and the policy (work orders are approved issues). So a changed branch list counts only once it is merged there. Its config PR changes only `factory/config.json` (or `docs/work/*.md`, the device smoke's file) and needs approving reviews at its current head from as many maintainer accounts as `work_order_approvals` in `factory/config.json` names (today 1) (its production check runs again after every review, dismissals included) and `factory/deterministic`; it never needs `/review` or an AI review (a `/review` on it is refused, and its pipeline comment says that maintainer approvals decide), and `/bypass` does not work on it. The trusted tests of `factory/deterministic` run against its changed `factory/config.json` but never depend on its branch list or config branch, so a config PR passes them. A maintainer merges it on GitHub with a merge commit. Then `factory update <validation branch>` in the candidate brings it into each validation branch (a fast-forward while the branch has nothing production lacks, otherwise a local merge commit limited to `factory/config.json` and `docs/work/*.md`); push the result.

Every factory check is bound to the config tip. A push to the config branch therefore re-runs every open PR into a gated validation branch or another production branch (for a `full` gate this means a new AI review); PRs never get `needs-author-action` for a moved config tip. A `/bypass` given under the earlier config tip no longer counts on the re-run: its comment asks a maintainer for a new `/bypass`, and the author is not asked to act.

**Promote** a validation branch when its state should go to production:

```sh
factory promote testing
```

If `production` has commits that `testing` lacks, the command first brings `production` into `testing` in your candidate and stops: a fast-forward when `testing` has nothing `production` lacks (then there is nothing to promote until `testing` gets new commits), otherwise a merge commit. Push it to `testing` (or resolve conflicts first, then commit and push), and run it again to open or update the promotion PR. Once `production` is contained, it opens the promotion PR `testing` → `production`; if that promotion is already open, it only reports that the PR now carries the new head. Only one promotion into a production branch may be open at a time. The production ruleset requires two checks, `factory/deterministic` and `factory/production/production`; the PR shows three:

- `factory/deterministic` runs on every new commit;
- `factory/senior-review` exists only after a maintainer comments `/review` on the PR, for the head current when the comment was posted. New commits do not restart it; comment `/review` again when you want a fresh review. If maintainer feedback, a moved config tip or a moved `production` makes a pending review stale before a device reviews it, `factory watch` says so instead of waiting: comment `/review` again, after a moved `production` once `factory promote testing` has updated the promotion;
- `factory/production/production` is green only when the PR's head is the current tip of `testing` and already contains `production`, no other promotion into `production` is open, and, because `production` has review mode `maintainer-manual`, a passed `factory/senior-review` exists for exactly this PR, head, target and config tip. When the local review finishes, the reviewing device re-runs this check. If it could not (failed dispatch, timeout, Ctrl-C), it prints the re-run `gh workflow run factory-promotion.yml --repo Zerosteps1/Aicepeak_V2.0.0 --ref production -f pr=<n>`, which the check's "AI review … is missing" summary names too: a review that passed needs only this re-run, never a new `/review`. With review mode `initiated` the review is optional, with `no` it is never offered.

Merge production PRs on GitHub with **Create a merge commit**, the only method the production ruleset allows; `factory merge` handles only PRs into validation branches. A merge commit keeps the commits of `testing` in `production`, so afterwards `factory update testing` in the candidate fast-forwards `testing` to `production` without a new commit; push it, and GitHub no longer reports `production` ahead of `testing`. Squash and rebase are not allowed: they write new commits that `testing` never contains.

**`/bypass <reason>`:** a maintainer comment on a factory PR (into a gated validation branch, or a promotion) marks its required factory checks, on a promotion including the production check and its AI-review requirement, as passed for the head current when the comment was posted. The checks show your login and the reason. It acts within seconds: its run cancels whatever factory run of the PR is running or waiting (snapshot and tests, review coordination, correction, production check), whose results no longer matter for a bypassed head; other runs never cancel each other. It counts only from an unedited comment (post a new one instead of editing; `factory merge` and the production check stop counting it once its comment is edited or deleted), is refused when the head's commit is newer than the comment, runs only when the dispatcher or the comment's author started it, and neither a job re-run nor a re-run of the dispatcher run ever reuses it. A re-run of the same head keeps it on a gate `tests` PR and on a promotion (published again as the newest check run when a newer run on the commit hides it), and removes `needs-author-action`; a gate `full` PR is reviewed again on every run. A new commit, or a moved config tip, needs a new `/bypass`. It works on every promotion, also one whose diff holds only `factory/config.json` or `docs/work/*.md`, and never on config PRs into a production branch.

**Change the branch list** with `factory add validation branch`, `factory add production branch`, `factory remove branch` and `factory set config branch` ([commands](factory-cli.md)). Each opens a config PR into the config branch, without an advisory preflight; `factory set config branch` opens two, first into the new config branch, then into the current one, and lists the owner steps in their order, ending with the re-run of the open PRs on the new config branch ([details](factory-cli.md#factory-set-config-branch)). It refuses while the new branch's `factory/config.json` or work orders lag behind the current config branch, and while the default branch still names an earlier config branch; `factory remove branch` likewise refuses the branch the default branch still names as config branch. After the merge the repository owner applies the GitHub settings (`tools/factory/settings.py`) and creates a new branch. A config PR cannot change the generated [branch diagram](factory-branches.md): regenerate it with `factory branches` in a later change.

## Status labels

| Signal | Meaning |
|---|---|
| `awaiting-senior-review` | Deterministic checks passed; the binding Astra review has not run yet (on a production PR: after a maintainer's `/review`). A maintainer starts it with `factory watch <n>`. |
| `needs-author-action` | Tests or review block, a limit is exhausted, or a control path needs a human-driven fix. The PR comment names the next step and, for a failed author run, a classified launcher reason. PRs into production branches never get it, and no PR gets it for a moved config tip (its fresh run is dispatched automatically), for a failing re-run whose `/bypass` still holds (which removes it, as a `/bypass` does), or for one whose `/bypass` a moved config tip voided (a maintainer posts a new one). |
| No label, required checks green | A human decides about the merge. |

The per-PR limits behind these labels are listed in [software-factory.md](software-factory.md#limits).

## Working in parallel

Maintainers and their agents can work on several PRs at once. Parallel PRs break each other when they were each tested alone but merged together, mostly through shared files such as test modules, registries or lockfiles. The factory keeps that visible and safe:

- **Before the PR:** `factory submit --finished` (through `session.py submit`) shows overlaps with other open PRs and a shared work order; `session.py collisions` shows them without submitting ([without the CLI](factory-cli.md#without-the-cli)). Agree on the order instead of coding against unmerged changes; keep PRs small and away from shared hotspots where possible. One work order is one PR: split larger work into several work orders.
- **While open:** the gate fails any head that does not contain the current tip of its target branch, so stale heads never look mergeable. Every push to the target (a merge, a direct maintainer push, a pushed `factory update`, the merge-back of a promotion) moves that tip.
- **At merge time:** one merge per validation branch at a time with `factory merge`. Merges through it are serialized by a lock per target branch, so two maintainers can never merge against the same tip at once. The PR merged second updates its branch, resolves its own conflicts with the target (with `factory fix` or your own session), and gets a fresh run and review before its merge.
- **On one device:** one factory run per work order at a time; runs for different work orders can run side by side. They share one candidate checkout, so a run applies its result only when the candidate is on a listed branch or that run's branch without uncommitted tracked changes; otherwise it keeps the patch and prints the commands.

## Merge rules

- **PRs into a validation branch.** Normal case: the App-bound required checks of the branch's gate (`full`: `factory/deterministic` and `factory/senior-review`; `tests`: `factory/deterministic`) are green on the current head and all threads are resolved; then a maintainer merges with their own `gh` login. `factory merge` runs `session.py merge` from a disposable checkout of the verified current config branch tip:

  ```sh
  factory merge <n> --dry-run   # verdict only
  factory merge <n>
  ```

  The validation ruleset lets only maintainers update the branch (by their PR merges or direct pushes), so every merge uses the maintainer bypass, which also skips GitHub's check and up-to-date rules. `merge` therefore verifies them itself and refuses unless the PR is ready, its head contains the target's current tip, each required check from App 5510081 is `success` with an `external_id` (`repository:PR:head:policy:base_ref:run:attempt`) bound to exactly this head, this target branch and the current config tip (or is an authentic `/bypass` for that head whose comment is still the same maintainer's unedited `/bypass` on this PR), handoff and human feedback are unchanged since that review, and no review thread is open. Checks with the earlier 6-field binding never count; such PRs need a fresh run. GitHub's merge pins only the head, never the base, so `merge` first takes the target's lock `refs/tags/factory-merge-lock--<branch>` (GitHub creates a ref atomically and refuses an existing one), re-checks the target and config tips, the PR, the checks and the threads while holding it, merges with `--admin --match-head-commit <head>`, releases the lock, compares the merge commit's parents with the verified target tip and head, and records the result as a PR comment. If GitHub gives no answer to the merge (timeout, abort), the lock stays, because GitHub may still merge; a held lock therefore means another merge into that branch is running or its outcome is unknown. Check the named PR (merged: verify the target; certainly not merged: fine), then remove the lock, for `testing` with `gh api -X DELETE repos/Zerosteps1/Aicepeak_V2.0.0/git/refs/tags/factory-merge-lock--testing`. If the target moved, use "Update branch" and wait for the fresh checks and review. If only the config tip moved, the fresh run is dispatched automatically; `merge` says so and names the [retry](#restart-a-stuck-run) with `--ref <config branch>` as the fallback if none arrives.
- **Stuck PR into a validation branch** (no reviewer device, model failure, exhausted limits): a maintainer comments `/bypass <reason>`; the required checks of the current head then pass by bypass with login and reason, and `factory merge` accepts them. A maintainer may also merge deliberately through the ruleset bypass on GitHub; this is outside the `factory merge` guarantee: it takes no lock and does not re-validate against the tip it lands on. Write the reason as a PR comment first; GitHub records every ruleset bypass. A bypassed PR has no independent review, so use both sparingly.
- **PRs into a production branch** are merged on GitHub with a merge commit (no squash or rebase) once all required checks pass, then brought back into the validation branch with `factory update` and a push ([branches and promotion](#branches-and-promotion)). The production rulesets require only `factory/deterministic` and `factory/production/<branch>` and have no bypass actors, so a red check can only be overcome by a `/bypass` on a promotion; config PRs need their maintainer approvals (`work_order_approvals`) and never an AI review.
- Never: direct pushes to production branches, auto-merge, agent or bot merges, or changing protection rules to force a green result.

## Verify locally

**Product code** (`backend/`, `frontend/`): the pipeline's test stage builds and tests both in the sandbox and lists every test case in the run's job summary; failing tests and errors also appear as annotations in the PR ([ADR-0011](decisions/0011-product-checks.md)). Before you stage or submit, run from the repository root

```sh
dotnet format backend/Aicepeak.slnx
dotnet build backend/Aicepeak.slnx -warnaserror
dotnet test backend/Aicepeak.slnx
npm --prefix frontend run lint
npm --prefix frontend test
npm --prefix frontend run build
```

`backend/` holds the API project and the solution, so `dotnet build`, `dotnet test` and `dotnet format` name `Aicepeak.slnx`; `dotnet run`, `dotnet watch` and `dotnet ef` run inside `backend/`. The database tests need Docker; without it add `--filter "Category!=Database"` to `dotnet test`. The build fails on formatting violations, which `dotnet format` fixes. Setup, local start and the code style are in [dev-setup](dev-setup.md#running-aicepeak-locally).

**Factory code:** in the sandbox, like the pipeline: `tools/factory/sandbox-verify.sh` from the checkout you changed ([dev-setup](dev-setup.md#test-changes-in-the-sandbox)). On the host:

Full local verification of the control checkout (needs `actionlint` and `gitleaks`; `factory doctor` prints the command that installs them), run from the control checkout without leaving files behind:

```sh
python3 tools/factory/verify.py --root .
python3 -I -B -m unittest discover -s tools/factory/tests
```

On the host, `verify.py` leaves installed dependencies (`node_modules`) out of its file checks; with `--ci`, as in the pipeline and `sandbox-verify.sh`, it checks every file. Gitleaks' default rules ignore `node_modules` in both cases.

The structural check of your candidate, using only the control checkout's verifier:

```sh
python3 tools/factory/verify.py --root ../aicepeak-candidate --trusted-root . --structure-only
```

After changing skills or roles in `.agents/` (a protected factory change, in the candidate), regenerate and check the native adapters with the control checkout's tools:

```sh
python3 tools/factory/clients.py sync --root ../aicepeak-candidate
python3 tools/factory/clients.py check --root ../aicepeak-candidate
```
