# FACTORY-006 – GitHub issues as work orders

Status: draft; it authorizes work only after a maintainer sets `status` to `approved` and this file is merged to protected `main` in its own reviewed PR. It builds on [FACTORY-005](FACTORY-005.md) (single developer checkout); implement it only after FACTORY-005 has merged.

```factory-task
{"status":"draft","kind":"factory","allowed_paths":[".github/",".agents/",".claude/",".codex/","factory/","tools/factory/","docs/decisions/","docs/work/TEMPLATE.md","README.md","CONTRIBUTING.md","docs/software-factory.md","docs/way-of-working.md"]}
```

requirements: []

## Goal

A developer defines a task as a GitHub issue (description and acceptance criteria). An AI recommends `kind` and `allowed_paths` as a comment, and a maintainer approves it with a thumbs-up or adapts it in a comment. The author, the deterministic gate, the senior review, the automatic correction and the merge all work against that approved, frozen issue instead of a `docs/work/` file.

## Non-goals

- No change to the isolated container, the credential broker or its network boundary.
- No change to models, limits, budgets, rulesets or required checks.
- No automatic approval: only a configured maintainer approves an issue.
- No removal of file work orders in `docs/work/` (see open questions).

## Context and constraints

Today every component reads the task from `docs/work/<ID>.md` at the protected `main` commit: `session.py` (`task_order`, scope and collision checks), the gate (`engine.py`, `allowed_paths` check), the review snapshot, the correction prompt and merge safety. A reviewed file on `main` is the trust anchor. Issues are editable and, in this public repository, anyone can open one. The replacement trust anchor is therefore a maintainer approval bound to a hash of the issue. Each component checks it independently, because they run in different places: Actions, the maintainer device and the local merge.

Design:

1. **Issue form.** `.github/ISSUE_TEMPLATE/factory-task.yml` with goal, non-goals, acceptance criteria and verification. It replaces the stale `factory-task.md`.
2. **Recommendation.** An AI posts one comment with a parseable block:
   ````
   ```factory-paths
   {"issue_hash":"<sha256 of the issue body>","kind":"factory","allowed_paths":["…"]}
   ```
   ````
3. **Approval.** A configured maintainer adds a thumbs-up to that comment, verified through the reactions API, or posts a comment with an adapted `factory-paths` block. The latest maintainer-approved block wins. The approval covers the issue body at `issue_hash`, `kind` and `allowed_paths`.
4. **Invalidation.** An edited issue body (hash mismatch), a closed or transferred issue, a removed reaction or an approved comment edited after its approval all invalidate the approval.
5. **Handoff.** The PR handoff accepts `{"runner":"claude","issue":<n>,"issue_hash":"…","owner":"…"}` as an alternative to `task`. Every component checks against that hash.
6. **Author.** `clients.py launch --issue <n>` fetches the issue and the approval with the host `gh` login, verifies them and writes `TASK.md` to a read-only mount outside the repository copy. The file is never committed, never part of the patch and never written into the developer's checkout or `.aicepeak-control-checkout`. The skills read it when present; the adapters are regenerated with `clients.py sync`.
7. **Pipeline.** `session.py` (submit, collisions, watch, merge), the gate, the review snapshot (issue text at `issue_hash`, bound to the result), the correction prompt (issue text as untrusted data) and merge safety load and verify the issue. The dispatcher also reacts to `issues` and `issue_comment` events on approved issues and re-runs the checks of the PRs that reference them.

A PR may change at most 40 files. If the implementation exceeds that, split it into consecutive PRs under this work order.

## Acceptance criteria

1. AC-1: When a maintainer has approved a `factory-paths` block on an open issue whose body matches `issue_hash`, the gate, `session.py submit`, the senior review and `session.py merge` shall accept a PR whose handoff references that issue and hash and whose files all match the approved `allowed_paths`.
2. AC-2: If the approval comes from an account not in `maintainers`, then every component shall reject the PR.
3. AC-3: If the issue body changes after approval, the issue is closed or transferred, or the approval is withdrawn, then every component shall reject the PR until a new approval exists, and the dispatcher shall re-run the checks of affected open PRs.
4. AC-4: If a PR changes a file outside the approved `allowed_paths`, then the gate and `session.py submit` shall reject it.
5. AC-5: When `clients.py launch --issue <n>` runs for an approved issue, the author shall see the issue as a read-only `TASK.md` that appears neither in the patch nor in either checkout. If the issue is not approved, the launcher shall stop before starting the container.
6. AC-6: The senior review result and the correction prompt shall be bound to the issue text at `issue_hash`, and the correction shall treat it as untrusted data.
7. AC-7: PRs that reference a `docs/work/` file work order shall keep working unchanged, unless the open question below decides otherwise.
8. AC-8: `factory/policy.md` and a new decision record in `docs/decisions/` shall describe the approved issue as a trust anchor; the docs shall describe the new flow.

## Verification

```sh
python3 -I -m unittest discover -s tools/factory/tests
python3 tools/factory/clients.py check --root .
python3 tools/factory/verify.py --root .
```

Expected output:

- unittest ends with `OK`, with regression tests for AC-1 to AC-7, including every rejection case;
- `clients.py check` passes with the regenerated adapters;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- live evidence in `factory/evidence.md`: one smoke issue taken from approval to two green checks, and one rejection after an edit of the issue body.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-006.md","owner":"ftrutschnig"}
```

## Open questions

- Who posts the path recommendation: a local command run by a maintainer, or a GitHub workflow through the publisher App? Decided by a maintainer.
- Do file work orders in `docs/work/` stay supported next to issues? Recommendation: yes. Decided by a maintainer.
- May an issue opened by a non-maintainer be approved, or only issues opened by maintainers? Decided by a maintainer.
