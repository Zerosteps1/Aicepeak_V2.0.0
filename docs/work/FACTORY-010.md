# FACTORY-010 – Merge commits into production; `factory update` fast-forwards branches to the config branch

Status: approved by the maintainer on 2026-11-06; amended by the maintainer on 2026-11-06 (the main problem is the production merge method: production PRs merge only with merge commits, and bringing production back is a fast-forward). Active once this file is merged into the config branch `production`. Replaces `factory sync workorders` / `factory sync workorder <n>` from [FACTORY-008](FACTORY-008.md) (its AC-10 sync sentence is superseded) and the production merge methods "squash or rebase" of FACTORY-008 AC-9 and ADR-0008 decision 8.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/cli/","tools/factory/settings.py","tools/factory/tests/test_cli.py","tools/factory/tests/test_settings.py","factory/github-settings.json","factory/github.md","factory/policy.md","docs/factory-cli.md","docs/way-of-working.md","docs/software-factory.md","docs/dev-setup.md","docs/decisions/0008-branch-model.md","docs/work/TEMPLATE.md","README.md","CONTRIBUTING.md"]}
```

requirements: []

## Goal

The main problem is that PRs into production are not merged with a merge commit. Squash and rebase make GitHub write new commits that no validation branch contains, so after every promotion `production` is "ahead" of `testing` and has to be merged back with an extra merge commit.

Production PRs shall therefore merge only with **Create a merge commit**. Production then keeps the validation branch's own commits plus one merge commit, and bringing production back into the validation branch is a fast-forward: no new commit, no conflicts.

`factory update [<target-branch>]` performs that step in the candidate. It fast-forwards the target to the config branch tip, and creates a local merge commit only when a fast-forward is impossible. Its scope is limited to work orders and `factory/config.json`. It replaces `factory sync`.

## Non-goals

- No push: the fast-forward or merge commit stays local in the candidate; the maintainer pushes it.
- No automatic fast-forward on GitHub: no workflow pushes to validation branches, and nothing merges automatically.
- No change to the checks, `/review`, `/bypass`, the approvals, or what a production branch accepts. Work-order and config PRs are opened and approved as before.
- Never a change to a production branch from the CLI.
- No change to the repository-level merge settings by code ("Allow merge commits" is already on), and no migration of work-order files or issues.

## Context and constraints

- **The problem.**
  - Today the production ruleset allows only squash and rebase: `factory/github-settings.json` `production_merge_methods`, enforced by `tools/factory/settings.py` ("production branches allow only squash or rebase merges"), recorded in ADR-0008 decision 8.
  - Both methods write new commits. Even rebase sets a new committer, so the commit IDs change. GitHub has no fast-forward merge for PRs.
  - So after every merge into production, production holds commits no validation branch contains: PR #48 became `133f5e3`, #47 became `4d0988a`, and the promotion #49 became `8fc09b1`.
  - GitHub then reports `production` ahead of `testing`, and `factory promote` has to merge production back as an extra commit (`4bdf629` "Merge branch 'production' into testing").
- **Why merge commits fix it.**
  - With a merge commit, production keeps the validation branch's commits.
  - A promotion PR's head is the validation branch itself, so after the merge the validation branch is contained in production, and bringing production back is a fast-forward.
  - Required checks are strict (the PR must be up to date with production), so the merge commit's content equals the checked PR head: the gate is unchanged.
  - `git log --first-parent production` still shows one entry per promotion.
- **Limit.**
  - A config PR, or a PR that amends a work-order file, comes from its own branch, not from the validation branch.
  - Bringing it into a validation branch is a fast-forward only while that branch has no commits production lacks. Otherwise it stays a merge commit, whatever the merge method.
  - Since FACTORY-009 new work orders are GitHub issues, so this affects only config changes and amendments of existing work-order files.
- **Settings.**
  - `production_merge_methods` becomes `["merge"]`. `settings.py` accepts exactly that and refuses any other value ("production branches allow only merge commits"). The production ruleset it plans has `allowed_merge_methods: ["merge"]`.
  - The owner applies it with `python3 tools/factory/settings.py apply` after this change is on production.
  - The repository's "Allow merge commits" stays on (it is on today).
- **`factory update` reuses the merge-back core.** The core of `branching.merge_production` becomes one helper used by `promote` (merge-back) and `update`:
  - clean check, local-versus-origin reconciliation and switch;
  - then `git merge --ff-only <config tip>` when the target tip is an ancestor of the config tip, otherwise a `--no-ff` merge with the conflict report.

  `promote` keeps its own messages, and its merge-back fast-forwards the same way when it can.
- **Reuse.** `local_tip`, `checkouts.current_branch`, `checkouts.head`, `is_ancestor`, `ctx.candidate_lock()`, `ctx.identity()`, `ctx.tips()` and `branches.config_change(paths)` (the type-(b) path rule: `docs/work/*.md` and `factory/config.json`).
- **Scope guard.** It applies to fast-forwards and merges alike and is computed without touching the working tree:
  - the result tree is the config tip's tree for a fast-forward, or `git merge-tree --write-tree --name-only <target-tip> <config-tip>` for a merge (git ≥ 2.38; the factory image has 2.39);
  - the guard diffs the target tip's tree against that result with `--no-renames`.

  After a merge-commit promotion the diff is empty.
- **Removal.** Remove `sync` and `push_orders`; keep `orders_at` while `drift()` uses it. `factory sync …` becomes a stub that only names the replacement.
- **Texts.**
  - `commands.submit_workorders`: "after the merge, bring them into your branch: `factory update`".
  - `branching.add_validation`'s owner step for a new branch: "`factory update <name>` in the candidate, then push".
  - `helptext.py`: replace the `sync workorders` and `sync workorder` entries with `update` (anchor `docs/factory-cli.md#factory-update`), and update the "Work orders" group and the `issue` text.
- **Docs.** Replace every "squash or rebase" with merge commits and explain the fast-forward:
  - `docs/factory-cli.md`: work-order PR and promotion sections, and `## factory update` instead of the sync section;
  - `docs/way-of-working.md` (two places), `factory/github.md` (production ruleset), `factory/policy.md` (German, the reviewer's policy: an explicit policy change by this work order), `CONTRIBUTING.md` (German);
  - `docs/software-factory.md`, `docs/dev-setup.md`, `README.md` and `docs/work/TEMPLATE.md` where they mention sync;
  - ADR-0008: decision 8 (merge commits only, with this reason), decision 5, and runbook step 8 ("`factory update testing`, then push").

  The owner guide outside the repository says "Squash and merge"; the maintainer updates it.
- **Delivery.**
  - This is a protected factory change (its paths are control paths): implemented by hand on a feature branch from `origin/testing`, PR into `testing` through the gate, then promoted.
  - `production`'s trusted tests pin squash/rebase (`test_settings.py`) and the old sync (`test_sync_adds_missing_orders_byte_exact_and_never_overwrites`), so the promotion needs `/bypass` with that reason.
  - That promotion is still merged with squash, because the old ruleset applies until the owner runs `settings.py apply`.
  - Rollout:
    1. promote and merge;
    2. the owner runs `settings.py apply`;
    3. `factory update testing` once (a merge commit this one time, because of that squash), then push.

    From then on, `factory update` fast-forwards after every promotion.
- **Expected size.** About a day:
  - `branching.py` about 90 lines changed;
  - `factory.py` and `helptext.py` about 30;
  - `settings.py` and `github-settings.json` about 5;
  - tests about 180;
  - about 20 doc passages.

## Acceptance criteria

1. AC-1: The settings shall allow only merge commits for production PRs.
   - `factory/github-settings.json` `production_merge_methods` shall be `["merge"]`.
   - `settings.py` shall refuse any other value with "production branches allow only merge commits".
   - The production ruleset that `settings.py` plans shall have `allowed_merge_methods: ["merge"]`.
2. AC-2: Without a target, `factory update` shall bring the config branch tip into the branch checked out in the candidate. With `<target-branch>` it shall bring it into that branch, switching the candidate to it and creating the local branch from `origin/<target>` when missing.
3. AC-3: When the target contains no commit that the config branch tip lacks, the CLI shall fast-forward the target to the config branch tip and create no commit. Otherwise it shall create a local merge commit (`--no-ff`, message `Merge <config branch> into <target> (factory update)`).
   - It shall never push.
   - It shall print the resulting commit, whether it was a fast-forward or a merge commit, and "Nothing was pushed."
   - It shall print the next step: `git -C <candidate> push origin <target>` for a listed validation branch, or "it goes up with your next `factory submit`" for a feature branch.
4. AC-4: If the fast-forward or merge would change any path other than `docs/work/*.md` and `factory/config.json` in the target, then the CLI shall refuse before touching the working tree, name up to 20 of those paths and point to `factory promote` or a manual merge.
5. AC-5: If the config branch tip is already contained in the target, then the CLI shall report it up to date, change nothing and exit 0.
6. AC-6: If the merge stops on conflicts, then the CLI shall leave the merge in the candidate, list the conflicted files, explain how to resolve or abort, and exit 1.
7. AC-7: The CLI shall refuse and change nothing if the target is a listed production branch, the candidate has uncommitted or untracked files, or the local target diverged from `origin/<target>`. A local branch behind origin shall be fast-forwarded first. Unpushed local commits shall be kept with a warning, which makes it a merge commit.
8. AC-8: After a promotion merged with a merge commit, `factory update` on that validation branch shall fast-forward it to production, and `factory promote`'s merge-back shall fast-forward the same way. After a promotion merged with squash (before the settings are applied), `factory update` shall pass the scope guard and create a merge commit.
9. AC-9: `factory sync workorders` and `factory sync workorder <n>` shall exit 2 naming `factory update [<target-branch>]`. Help texts, anchors and docs shall describe `factory update` and merge commits into production only.
10. AC-10: `factory --version` shall print `factory 0.4.0`.

## Verification

```sh
tools/factory/sandbox-verify.sh 'test_cli*.py'
tools/factory/sandbox-verify.sh 'test_settings.py'
tools/factory/sandbox-verify.sh
```

Expected output:

- The CLI tests end with `OK`, including tests for AC-2 to AC-10. They replace `test_sync_adds_missing_orders_byte_exact_and_never_overwrites`. They cover:
  - fast-forward after a merge-commit promotion, and a merge commit after a squash promotion;
  - promote's merge-back as a fast-forward;
  - default, named and feature targets;
  - up to date;
  - out-of-scope refusal with unchanged HEAD and working tree;
  - a `factory/config.json` conflict;
  - a production target and a dirty candidate refused;
  - ahead and diverged local branches;
  - the `sync` stub.
- The settings tests end with `OK`, including AC-1: `["merge"]` accepted, squash, rebase or mixed lists refused, and the planned production ruleset.
- The full run prints four `PASS:` lines and exits 0, also with the candidate's branch list changed by a branch edit helper (config-PR robustness).
- Live check after the rollout:
  1. The next promotion is merged with **Create a merge commit**.
  2. `factory update` in the candidate on `testing` reports a fast-forward.
  3. `git log --graph -5` shows no new commit on `testing`.
  4. After the push, GitHub no longer reports `production` ahead of `testing`.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-010.md","owner":"ftrutschnig"}
```

## Open questions

- None. Decided by the maintainer on 2026-11-06:
  - scope work orders and `factory/config.json`;
  - bring production in, not copy files;
  - the default target is the candidate's checked-out branch;
  - always local, never pushed.
- Amendment of 2026-11-06:
  - the main problem is the production merge method;
  - production PRs merge only with merge commits;
  - `factory update` fast-forwards, and creates a merge commit only when a fast-forward is impossible.
