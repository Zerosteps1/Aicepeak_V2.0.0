# FACTORY-004 – Merge safety for parallel pull requests

Status: requested by Gabriel on 2026-10-29 after reviewing how parallel agent pull requests break each other; it authorizes work only after this file is merged to protected `main` in its own reviewed PR.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/engine.py","tools/factory/github_api.py","tools/factory/session.py","tools/factory/tests/test_engine.py","tools/factory/tests/test_session.py","tools/factory/tests/test_local_review.py","tools/factory/tests/test_local_review_queue.py","README.md","CONTRIBUTING.md","factory/github.md","factory/evidence.md"]}
```

requirements: []

## Goal

When Gabriel, Felix and their agents have several pull requests open at the same time, what lands on `main` is exactly the state that the deterministic checks and the senior review saw, and collisions with current `main` or other open PRs are visible before a PR is opened.

## Non-goals

- No automatic conflict resolution against other open, unmerged PRs; no integrator agent that bundles PRs; no GitHub merge queue (available only for organization-owned repositories, and the senior review cannot run on merge-group commits).
- No change to rulesets, required checks, the maintainer bypass setting, review limits, budgets or models.
- No post-merge verification run on `main`; that is a separate follow-up work order.
- No product structure conventions; they belong to the definition of `product_checks_ready`.
- No agent or bot merges: the merge helper runs under the human maintainer's own `gh` login.

## Context and constraints

- The pipeline requires the PR's base SHA to equal current `main` (`snapshot_stage`, `assert_current`) but tests the PR head. GitHub moves the base SHA on every push to the PR, even when `main` was not merged into the branch: PRs #4 and #5 had a base their head did not contain (compare status `diverged`). A green check bound to current `main` therefore does not prove that the tested head contains `main`, and a later merge commit can combine code that was never tested together.
- Every maintainer merge uses the ruleset bypass, which also skips the strict up-to-date rule (README, merge rules). The manual check sequence verifies head and policy but not containment, and cannot notice a concurrent merge by the other maintainer. GitHub's merge API pins only the head (`--match-head-commit`, `expectedHeadOid`), never the base, so merges by different maintainers must be serialized before the merge, not detected after it.
- README step 8 asks to update all open PRs after every merge. Each update starts a fresh run and senior review, and every claimed review counts against `limits.max_reviews_per_pr` (`local_review_queue.py`), so a PR that waits while others merge can exhaust its limit.
- Both GitHub transports reject every API path containing `..` as unsafe; the compare route `base...head` needs a narrow, tested exception.
- Author containers have no GitHub or network access. A collision sweep therefore runs in `session.py` on the maintainer host, identically for Claude and Codex sessions, and only reads the candidate and control checkouts.

## Acceptance criteria

1. AC-1: If the PR head does not contain the current `main` commit, then `Publish gates` shall complete `factory/deterministic` and `factory/senior-review` as `failure` with a reason that names "Update branch", label the PR `needs-author-action` and request no senior review.
2. AC-2: When the head contains current `main` and the tests pass, publication shall behave as before.
3. AC-3: `session.py collisions --candidate <path> [--task <path>]` shall report, without changing the candidate or the control checkout: whether the candidate contains current `main`, the files a merge of current `main` would conflict in, and for every other open PR to `main` a shared work order, the overlapping files and the files a trial merge would conflict in. It shall exit non-zero when the candidate does not contain current `main`; overlaps with other PRs alone do not fail it. Missing history blocks the sweep, and an unavailable fetch or trial merge is reported as a limitation, never as a clean result.
4. AC-4: `session.py submit` shall refuse a candidate that does not contain current `main`, naming the conflicting files, before any model call. For an accepted candidate it shall add the collision summary, referencing overlapping PRs by number, to the new PR's body and shall not comment on other PRs.
5. AC-5: `session.py merge --pr <n>` shall merge only if the PR is open and ready, its base is current `main`, its head contains current `main`, both required checks from the publisher App are `success` and bound to exactly this head and current `main`, the handoff and human feedback are unchanged since that review, and no review thread is unresolved. Before merging it shall take a repository-wide merge lock that GitHub creates atomically (the tag ref `refs/tags/factory-merge-lock`; creating an existing ref fails), then re-read `main`, the PR head and its state while holding the lock, merge with `--match-head-commit` only if nothing changed, and release the lock afterwards. Every merge through `session.py merge` is therefore validated against the `main` it lands on. It shall verify the merge commit's parents, record the result as a PR comment and report an unexpected parent as an error, which only a merge outside the helper can cause. `--dry-run` shall only report the verdict and take no lock.
6. AC-6: If a required check is missing, not successful, from another App, bound to another head or an older `main`, the feedback or handoff changed after the review, a review thread is unresolved, the lock cannot be taken, or `main` or the head changed by the time the lock is held, then `merge` shall refuse without calling GitHub's merge.
7. AC-7: README and CONTRIBUTING shall describe: run the collision sweep before submitting; update only the PR that is merged next; merge one PR at a time with `session.py merge`; the PR merged second resolves its own conflicts with `main`; nothing is resolved against unmerged PRs. The manual bypass for stuck PRs stays documented, and the documentation states that it is outside the AC-5 guarantee: it neither takes the lock nor re-validates against the `main` it lands on.

## Verification

```sh
python3 -I -B -m unittest discover -s tools/factory/tests
python3 tools/factory/verify.py --root .
```

Expected output:

- unittest ends with `OK`, including new regressions for AC-1 to AC-6 that use real temporary Git repositories for the containment and trial-merge cases;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- live: the first PR merged with `session.py merge` records its comment with the verified `main` and head; this evidence is added to `factory/evidence.md` in a later reviewed update.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-004.md","owner":"Zerosteps1"}
```

## Open questions

- None blocking. Follow-up: a post-merge verification run on `main` (deterministic checks on every new `main` commit; a red `main` blocks new merges) as its own work order once this one is merged, because both change `engine.py` and the README.
