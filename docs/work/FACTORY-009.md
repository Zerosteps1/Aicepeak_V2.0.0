# FACTORY-009 – Issues as workorders

Status: approved; amended by the maintainer on 2026-11-06 (scope, acceptance criteria, verification). Implemented manually outside the factory pipeline: it changes control paths, which the isolated author cannot write.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["tools/factory/","factory/",".github/","docs/","README.md","CONTRIBUTING.md"]}
```

requirements: []

## Goal

Work orders are GitHub issues instead of files. A maintainer issues one by creating an issue that contains a `factory-task` block, either with `factory issue` or with the issue template on GitHub. The issue number is the work-order ID (`#57`), as every issue already has a unique number.

On a maintainer's `/review` comment, the factory's issue reviewer (the configured Claude model, today Sonnet) reviews the issue. It posts one comment that proposes the `allowed_paths`, and a second comment that names unclear, weak or missing sections, each with a proposed text that the human copies into the issue by hand. On a maintainer's `/accept`, the factory writes the proposed `allowed_paths` into the issue description and approves the work order. Every comment and edit by the factory is visibly the factory's, also in the description's edit history.

The engine, `session.py` and the `factory` CLI then read the approved issue as the work order, exactly as they read approved work-order files today.

## Non-goals

- The factory never creates GitHub issues; only humans do (`factory issue` uses the maintainer's own GitHub login).
- No reaction (👍) trigger: GitHub sends no event for reactions; `/accept` replaces it.
- No automatic review when an issue is opened or edited; only `/review` starts the reviewer.
- No migration or change of the existing work-order files in `docs/work/`: they keep working; the maintainer handles them separately. `factory submit workorders` and `factory sync workorders` stay for them and for config PRs.
- No change to the PR gates, the senior review, corrections, promotion, `/bypass` or the rules for work-order/config PRs into production branches.
- Issues opened by anyone other than a configured maintainer are never work orders and never reviewed.

## Context and constraints

- Reverses ADR-0007 decision 8 (FACTORY-006, issues as work orders, was superseded then); record the decision in a new ADR.
- Today the binding work order is a file merged on the config branch. An issue description stays editable, so an approval must be pinned to one exact text: any later edit of title or description un-approves the issue until it is accepted again.
- GitHub facts: no Actions or webhook event for reactions; `issue_comment` events of issues run the default branch's copy of the dispatcher, like PR comments; maintainers can edit any comment, so a record only counts while unedited.
- Model access on GitHub only through the existing Workload Identity Federation of `factory.yml` on the config branch (environment `factory-control`); the model call is tool-less and its output is untrusted until validated.
- The publisher App needs the additional permission Issues: read and write (owner step).

## Acceptance criteria

1. AC-1: When a maintainer comments `/review` on an open issue (not a PR) that a maintainer opened and that contains exactly one valid `factory-task` block, the factory shall run the issue reviewer (configured Claude model through Workload Identity Federation, without tools) and post as the publisher App (a) one proposal comment with the proposed `allowed_paths` and a reason for each, bound to the SHA-256 of the reviewed title and description, and (b) a second comment naming unclear, weak or missing sections, each with a proposed replacement text.
2. AC-2: If the commenter or the issue's author is not a configured maintainer, the issue is a PR or closed, the `factory-task` block is missing, duplicated or invalid, the command comment was edited, the run is a re-run, or `limits.max_issue_reviews` reviews were already posted on the issue, then the factory shall not call the model; a maintainer's refused command gets a short comment with the reason.
3. AC-3: When `/accept` comments of as many distinct maintainer accounts as `work_order_approvals` names follow the newest proposal and title and description are unchanged since that review, the factory shall set `allowed_paths` to the proposal and `status` to `approved` in the issue description as the publisher App (nothing else in the description changes) and post an authenticated approval record with the SHA-256 of the resulting title and description; with fewer `/accept` comments it shall report the count; a changed issue, a missing proposal or an edited `/accept` shall be refused, leaving the description unchanged.
4. AC-4: The engine snapshot, the correction, the senior-review material, `session.py` preflight, submit, watch and merge, and the `factory` CLI shall accept a work order `#N` only when issue N is open, was opened by a maintainer, and the SHA-256 of its current title and description equals the newest authentic, unedited approval record whose `/accept` comments still exist unedited from current maintainers; any later edit shall make snapshots stale and block merges until the issue is accepted again. Work-order files in `docs/work/` shall keep working unchanged.
5. AC-5: `factory issue` shall create the GitHub issue under the maintainer's own GitHub login (template body, chosen kind, status `draft`), print its number and URL and create no file; `57`, `#57` and `issue-57` shall resolve it; its work branches shall be `<login>/issue-57`, `<login>/issue-57-<k>` and `<login>/issue-57-fix-<k>`; the handoff shall name `"task":"#57"`.
6. AC-6: All comments and description edits of the factory on issues shall come from the publisher App installation, so GitHub shows the App as author and in the edit history; the model's output shall be validated against a schema, its paths checked with the factory's path rules, its texts length-limited and neutralised (no @-mentions, no HTML comments, no breaking out of code fences) before posting; the step that calls the model shall hold no App key, and the steps holding the App key no model credential.
7. AC-7: `factory --version` shall print `factory 0.3.0`, and the tests shall pass in the factory image.

## Verification

```sh
python3 -I -m unittest discover -s tools/factory/tests
python3 tools/factory/verify.py --root .
python3 tools/factory/verify.py --root /candidate --trusted-root /candidate --ci   # in the factory image, see docs/factory-cli.md
python3 tools/factory/clients.py check --root .
bash -n tools/factory/cli/install-factory-cli.sh
```

Expected output:

- unittest ends with `OK`, including the new tests for AC-1 to AC-6 (records, hash pinning, `/accept` counting and refusals, description edits limited to the block, neutralisation, dispatcher routing and refusals, issue references in engine, session, merge safety and CLI);
- `verify.py` prints its `PASS:` lines and exits with code 0, also with `--ci` in the factory image;
- `clients.py check` and `bash -n` exit with code 0.

Live acceptance after the owner steps of the new ADR (publisher App permission Issues: read and write, settings applied, promotion to `production`), recorded in `factory/evidence.md`: `factory issue` → `/review` → two App comments → `/accept` → the edit history shows the App → `factory start workorder <N>` finds the work order; negative probes: `/accept` from a non-maintainer is ignored, an edit after approval blocks the work order.

## Handoff

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-009.md","owner":"ftrutschnig"}
```

## Open questions

- How to start the issue reviewer on GitHub: a maintainer's `/review` comment on the issue; the dispatcher starts `factory.yml` on the config branch.
- How to let the issue reviewer adapt the issue when instructed to do so: a maintainer's `/accept` comment; the publisher App edits only the `factory-task` block.
- How to let the issue reviewer be shown as such in the GitHub UI: everything is written with the publisher App's installation token, so GitHub shows the App as author and editor.
