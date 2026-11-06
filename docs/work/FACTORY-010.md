# FACTORY-010 – `factory update`: merge the config branch's work orders and config into a branch

Status: approved by the maintainer on 2026-11-06; active once this file is merged into the config branch `production`. Replaces `factory sync workorders` / `factory sync workorder <n>` from [FACTORY-008](FACTORY-008.md) (its AC-10 sync sentence is superseded by this work order).

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/cli/","tools/factory/tests/test_cli.py","docs/factory-cli.md","docs/way-of-working.md","docs/software-factory.md","docs/dev-setup.md","docs/decisions/0008-branch-model.md","docs/work/TEMPLATE.md","README.md","CONTRIBUTING.md"]}
```

requirements: []

## Goal

`factory update [<target-branch>]` merges the tip of the config branch into one branch as a local merge commit, limited to work orders and `factory/config.json`, so work-order and config PRs (and squash/rebase promotions) no longer leave the validation branches diverged from `production`. It replaces `factory sync`.

## Non-goals

- No push: the merge commit stays local in the candidate; the maintainer pushes it.
- No change to promotion, its merge-back in `factory promote`, the production merge methods (squash/rebase stay), rulesets, workflows, settings or the owner's steps.
- No change to how work-order or config PRs are opened or approved.
- Never a change to a production branch.

## Context and constraints

- Today `tools/factory/cli/branching.py` `sync` + `push_orders` copy only missing `docs/work/*.md` files byte-exact into every validation branch and push them directly; they never update or delete, and the Git history stays diverged. GitHub then reports `production` as ahead of `testing` after every work-order, config or squash/rebase promotion merge.
- The merge-back core already exists in `branching.merge_production` (clean check, local-versus-origin reconciliation, switch, ff-only, `--no-ff` merge, conflict report). Extract it into one helper used by both `promote` and `update`; `promote` keeps its own messages.
- Reuse `local_tip`, `checkouts.current_branch`, `checkouts.head`, `is_ancestor`, `ctx.candidate_lock()`, `ctx.identity()`, `ctx.tips()` and `branches.config_change(paths)` (the type-(b) path rule: `docs/work/*.md` and `factory/config.json`).
- The scope guard computes the merge without touching the working tree: `git merge-tree --write-tree --name-only <target-tip> <config-tip>` (git ≥ 2.38; the factory image has 2.39), then diffs the target tip's tree against the result with `--no-renames`.
- Remove `sync` and `push_orders`; keep `orders_at` while `drift()` uses it. `factory sync …` becomes a stub that only names the replacement.
- Next-step texts that mention sync change: `commands.submit_workorders` ("after the merge, bring them into your branch: `factory update`") and `branching.add_validation`'s owner step for a new branch ("`factory update <name>` in the candidate, then push"). `helptext.py`: replace the `sync workorders` and `sync workorder` entries with `update` (anchor `docs/factory-cli.md#factory-update`), and update the "Work orders" group and the `issue` text.
- Docs: `docs/factory-cli.md` gets `## factory update` instead of the sync section; also `docs/way-of-working.md`, `docs/software-factory.md`, `docs/dev-setup.md`, `README.md`, `CONTRIBUTING.md` (German), `docs/work/TEMPLATE.md` and ADR-0008 (decision 5; runbook step 8: "`factory update testing`, then push").
- This is a protected factory change (its paths are control paths): implemented by hand on a feature branch from `origin/testing`, PR into `testing` through the gate, then promoted. `production`'s trusted tests pin the old sync behaviour (`test_sync_adds_missing_orders_byte_exact_and_never_overwrites`), so the promotion needs `/bypass` with that reason.
- Expected size: about half a day to a day (`branching.py` about 80 lines changed, `factory.py`/`helptext.py` about 30, tests about 150, about 15 doc passages).

## Acceptance criteria

1. AC-1: When `factory update` runs without a target, the CLI shall merge the config branch tip into the branch checked out in the candidate; with `<target-branch>` it shall merge into that branch, switching the candidate to it (creating the local branch from `origin/<target>` when missing).
2. AC-2: The CLI shall create the merge as a local merge commit (`--no-ff`, message `Merge <config branch> into <target> (factory update)`) and shall never push; it shall print the commit, "Nothing was pushed." and the next step: `git -C <candidate> push origin <target>` for a listed validation branch, or "it goes up with your next `factory submit`" for a feature branch.
3. AC-3: If the merge would change any path other than `docs/work/*.md` and `factory/config.json` in the target, then the CLI shall refuse before touching the working tree, name up to 20 of those paths and point to `factory promote` or a manual merge.
4. AC-4: If the config branch tip is already contained in the target, then the CLI shall report it up to date, create no commit and exit 0.
5. AC-5: If the merge stops on conflicts, then the CLI shall leave the merge in the candidate, list the conflicted files, explain how to resolve or abort, and exit 1.
6. AC-6: If the target is a listed production branch, the candidate has uncommitted or untracked files, or the local target diverged from `origin/<target>`, then the CLI shall refuse and change nothing; a local branch behind origin shall be fast-forwarded first, and unpushed local commits shall be kept with a warning.
7. AC-7: After a squash promotion (production equals the validation branch's content plus work orders), `factory update` on that validation branch shall pass the scope guard and merge.
8. AC-8: `factory sync workorders` and `factory sync workorder <n>` shall exit 2 naming `factory update [<target-branch>]`; help texts, anchors and docs shall describe `factory update` only.

## Verification

```sh
tools/factory/sandbox-verify.sh 'test_cli*.py'
tools/factory/sandbox-verify.sh
```

Expected output:

- the CLI tests end with `OK`, including tests for AC-1 to AC-8 (default target, named and feature targets, up to date, out-of-scope refusal with unchanged HEAD and working tree, config.json conflict, production target and dirty candidate refused, ahead and diverged local branch, the squash-promotion case, the `sync` stub). They replace `test_sync_adds_missing_orders_byte_exact_and_never_overwrites`;
- the full run prints four `PASS:` lines and exits 0, also with the candidate's branch list changed by a branch edit helper (config-PR robustness);
- live check after the change runs from `testing` (`factory use branch testing`): `factory update` in the candidate on `testing`, `git log --graph -5` shows the merge commit, and after the push GitHub no longer reports `production` ahead of `testing`.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-010.md","owner":"ftrutschnig"}
```

## Open questions

- None. Decided by the maintainer on 2026-11-06: scope work orders and `factory/config.json`; a merge, not a copy; default target is the candidate's checked-out branch; always a local commit.
