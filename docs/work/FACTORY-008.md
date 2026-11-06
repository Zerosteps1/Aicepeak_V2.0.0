# FACTORY-008 – Branch model: validation and production branches

Status: approved by the maintainer on 2026-11-02. Builds on FACTORY-007 (factory CLI).

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/","factory/",".github/","docs/factory-cli.md","docs/factory-branches.md","docs/way-of-working.md","docs/software-factory.md","docs/dev-setup.md","docs/decisions/","docs/work/TEMPLATE.md","docs/work/FACTORY-WIF-SMOKE.md","README.md","CONTRIBUTING.md","AGENTS.md"]}
```

requirements: []

## Goal

Changes travel in three levels: **feature branch → validation branch → production branch**. Validation branches are protected and gated automatically at a configurable level. Production branches are protected and reached only by promotion from a validation branch, plus work-order and config PRs that maintainers approve (`work_order_approvals`). All rules, configuration, policy and work orders come from one **config branch** (default: the only production branch). Today's `main` becomes `testing` (validation, full gate, GitHub default branch); a new branch `production` is the production and config branch. The factory CLI manages the branch list, routes work, syncs work orders, promotes, and draws the branch and gate diagram.

## Non-goals

- No change to the author container, the credential broker, models, limits or the review protocol schema.
- No automatic merge into a production branch: maintainers merge production PRs on GitHub.
- No direct pushes to production branches, by anyone.
- No verification of GitHub rulesets by the CLI: the branch list is trusted as declared.
- No identity proof beyond GitHub accounts: two different maintainer accounts count as two maintainers.

## Context and constraints

- Branch list, gates and review modes live in `factory/config.json` (`config_branch`, `branches`) on the config branch and are validated by `tools/factory/branches.py`. Validation branches: `gate` `full` (deterministic tests, binding Astra review, corrections), `tests` (deterministic tests only) or `none` (not gated), and the work-order kinds routed to them; every kind is routed to exactly one validation branch. Production branches: `review` `no`, `initiated` or `maintainer-manual`.
- Every gate job runs `factory.yml` dispatched on the config branch, so trusted code, configuration, policy and work orders are the config tip. The check binding carries the target branch (`contracts.binding`, 7 fields); `policy_sha` is the config tip, `base_sha` the target tip.
- Maintainers may push directly to validation branches. Nobody pushes to production branches.
- PRs into a production branch are (a) promotions (head is a validation branch), (b) work-order or config PRs (only `docs/work/*.md` and/or `factory/config.json`; approving reviews at the current head by as many maintainer accounts as `work_order_approvals` names (2 when absent, set to 1 on 2026-11-06); `/bypass` refused) or (c) anything else (refused).
- `/review` (maintainer comment on a promotion PR) starts the AI review; new commits never start it. With review mode `maintainer-manual` the production check requires that review for the promotion's own head, so a review published for another PR on the same commit never counts; type-(b) PRs never need it. `/bypass <reason>` (maintainer comment on any factory PR except type b) publishes the required factory checks of the head it was posted for as passed by bypass, with login and reason.
- Revised on 2026-11-02 after the independent review of the first implementation: production AI review inside the production check, re-runs when the config tip moves, `/review` and `/bypass` bound to their head, dismissed approvals, and a config-branch change that the factory follows once (ADR-0008, decision 14).
- Delivered locally by the maintainer outside the factory pipeline (maintainer decision of 2026-11-02). Decision record: `docs/decisions/0008-branch-model.md`. The owner applies settings, renames `main`, creates `production` and changes the WIF rule after the merge (runbook in that record).

## Acceptance criteria

1. AC-1: `branches.problems(config)` shall name every violation of the branch model (schema, name pattern, duplicates, reserved names, gate and review values, kinds routed exactly once, `default_branch` a validation branch, `config_branch` a production branch); `verify.py` shall fail on any.
2. AC-2: The branch edit helpers shall change only the `branches` and `config_branch` spans of `factory/config.json` and refuse results that break the branch model, the removal of the config or default branch and of the last production branch.
3. AC-3: Every gate job shall run from the config branch tip; the dispatcher shall dispatch `factory.yml` (and `factory-promotion.yml`) only with `ref` set to the config branch and follow a finished change of the config branch exactly once (`branches.follow`: the old config branch names a listed production branch whose own configuration names itself); otherwise it shall refuse to dispatch.
4. AC-4: Checks shall be bound to repository, PR, head, config tip, target branch, run and attempt; a changed head, target branch, target tip or config tip shall make a snapshot stale; legacy 6-field bindings shall not count. A push to the config branch shall re-dispatch the open PRs into gated validation branches and other production branches, without asking their authors for action.
5. AC-5: A PR into a validation branch with gate `full` shall run as today (deterministic tests, binding review, corrections into feature branches only); with gate `tests` it shall publish only `factory/deterministic` and never start a correction; a branch with gate `none` shall never be dispatched; a head that is a listed branch shall be refused.
6. AC-6: On every new head of a PR into a production branch, `factory/deterministic` shall run with the config branch's rules and no work-order scope; `factory/senior-review` shall be created only by a maintainer's `/review` comment on a promotion, for the head it was posted on (work-order/config PRs refuse it), follow the branch's `review` mode and never be restarted by a new commit; a pending review made stale by later feedback or a moved config tip shall be reported by `session.py watch`.
7. AC-7: `factory/production/<branch>` shall pass a promotion only when its head is the current tip of a validation branch whose gate is not `none`, the production tip is contained in it and it is the only open promotion into that production branch, and, for review mode `maintainer-manual`, a passed `factory/senior-review` bound to this PR, head, target and config tip exists; or after a `/bypass` for exactly that head; it shall pass a type-(b) PR only with approving reviews at the current head from as many maintainer accounts as `work_order_approvals` names, without AI review and without bypass, and run again after every review, dismissals included; it shall fail type (c).
8. AC-8: `/review` and `/bypass` shall be accepted only from maintainer accounts and only on open PRs into listed branches; a command comment shall count only unedited, for the head the dispatcher saw when it was posted; a bypass shall record the login and reason, be refused for a head newer than its comment, run only when dispatched by the dispatcher or the comment's author and never be reused by a job or dispatcher re-run; a same-head re-run of a gate-`tests` or production PR shall keep it, and `factory merge` shall count it only while its comment is unedited.
9. AC-9: `settings.py` shall generate validation rulesets (required checks of their gate; maintainers may push), production rulesets (PR only, squash or rebase, no bypass actors, required `factory/deterministic` and `factory/production/<branch>`), the `factory-control` and `factory-promotion` environments limited to the config branch, and print the WIF claim for the config branch.
10. AC-10: `factory add validation branch`, `factory add production branch`, `factory remove branch` and `factory set config branch` shall open a config PR into the config branch that changes only `factory/config.json` (`set config branch` first opens the same change into the new config branch, and refuses while that branch's configuration or work orders differ from the current config branch's or while an earlier change is still being followed); config PRs need no advisory preflight; an existing config-PR branch without a PR shall be reused or replaced, never left stranded; `factory submit workorders` shall open its PR into the config branch; `factory sync workorder <n>` and `factory sync workorders` shall push missing work orders byte-exact to every validation branch and never delete.
11. AC-11: `factory start`, `fix`, `hotfix` and `submit --finished` shall target the validation branch routed for the work order's kind; `factory submit` shall refuse listed branches.
12. AC-12: `factory promote <V>` shall merge the production branch into `V` in the candidate when it is not contained (merge commit, never pushed; conflicts left to the maintainer with instructions) and otherwise open the PR `V` → production, refusing when a promotion from another validation branch into that production branch is open (an open promotion of `V` itself is reported as updated); it shall never merge.
13. AC-13: `factory use branch <n>` shall accept only listed production or validation branches, switch the control checkout only when it is clean and work from any state of the control checkout, including after a finished config-branch change; `factory branches` shall write `docs/factory-branches.md` with a Mermaid diagram of branches, gates, kinds and review modes, and `--show` shall also write and open a self-contained HTML page.
14. AC-14: No `main` literal shall remain in trusted factory code, workflows or CLI; `factory --version` shall print `factory 0.2.0`.
15. AC-15: The tests shall pass in the factory image with a read-only root filesystem and no network within 180 s, as a single pass with this change as trusted root, and also when the candidate's `factory/config.json` was changed by any branch edit helper (as in a config PR).

## Verification

```sh
python3 tools/factory/verify.py --root /candidate --trusted-root /candidate --ci   # in the factory image, see docs/factory-cli.md
bash -n tools/factory/cli/install-factory-cli.sh
```

Expected output:

- the unittest pass ends with `OK`;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- `bash -n` prints nothing and exits with code 0.

Live acceptance after the owner runbook of `docs/decisions/0008-branch-model.md` is recorded in `factory/evidence.md`.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-008.md","owner":"ftrutschnig"}
```

## Open questions

- None. Live acceptance (rename, rulesets, WIF rule, first promotion) is open until recorded in `factory/evidence.md`.
