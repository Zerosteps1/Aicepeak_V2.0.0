# FACTORY-DEPS – Check Dependabot update PRs through the factory

Status: factory task for dependency update PRs opened by Dependabot. It authorizes work only after a human-reviewed merge to `main`. No product change.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":["factory/package.json","factory/package-lock.json","factory/Dockerfile","factory/tools.lock.json",".github/workflows/"]}
```

requirements: []

## Goal

Dependabot PRs for the ecosystems in `.github/dependabot.yml` (GitHub Actions in `/`, Docker and npm in `/factory`) get the same deterministic checks and senior review as any other PR, so a maintainer can decide on them with evidence. Today they cannot: Dependabot writes no `factory-handoff` block, the snapshot stops with "exactly one factory-handoff JSON block required", and the required checks never appear (finding F4 in the [factory review](../review/2026-10-28-factory-review.md); visible on PR #3).

## Non-goals

- No change to `.github/dependabot.yml`. Switching to a monthly schedule with `groups` and a cooldown is a separate control PR.
- No synthetic handoff in the dispatcher. Generating the block for `dependabot[bot]` PRs automatically is a later factory change.
- No automatic correction. Every allowed path is a factory control path (`protected_paths` in `factory/config.json`), so the engine never starts an author run for these PRs; a needed fix is made in a separate, manually managed PR (`factory/clients.md`, "Protected factory changes").
- No auto-merge. A human code owner approves and merges.

## Known limits

- The test stage builds its container image from the trusted base (`factory/Dockerfile` on `main`), not from the PR. A Dockerfile or npm change in a Dependabot PR is therefore not built by that PR's own run. Before approving such a PR, a maintainer builds it from a checkout of the PR head (`docker build -f factory/Dockerfile factory`) and records the result in the PR. A trusted image workflow (finding F15) would replace this manual step.
- A client CLI bump also needs the other pinned places (Dockerfile asserts, `clients.VERSIONS`, image tag in `clients.py` and `doctor.py`, `README.md`, `factory/clients.md`). Most are outside this task's paths, so such a bump is completed in a manually managed PR under a task that covers `tools/factory/`, such as [FACTORY-001](FACTORY-001.md).

## Adding the handoff block (maintainer)

1. Check that the PR was opened by `dependabot[bot]` and changes only paths listed in the block above. A PR that changes anything else stays blocked ("PR outside approved task").
2. Edit the PR description: on GitHub, open the PR, choose **Edit** on the description and append the block below; or with the GitHub CLI write the current body to a file, append the block and run `gh pr edit <number> --body-file <file>`.
3. Use exactly one block, with a configured runner and your own verified login as `owner`:

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-DEPS.md","owner":"Zerosteps1"}
```

4. Saving the description is a `pull_request_target` `edited` event; the dispatcher starts a new pipeline run for the current head. Each edit starts a new run, so edit once.
5. If Dependabot later updates or recreates the PR (for example for a newer version), it can replace the description. Check that the block is still present before relying on the checks, and add it again if needed.

The `runner` value only selects the author client for automatic corrections, which do not happen for these paths; it must still be one of the `runners` in `factory/config.json`.

## Acceptance criteria

1. AC-1: When a maintainer adds exactly one valid handoff block that references this task to a Dependabot PR that changes only allowed paths, the pipeline shall complete the snapshot and publish `factory/deterministic` for the PR head.
2. AC-2: If such a PR changes a path outside `allowed_paths`, then the snapshot shall stop with "PR outside approved task" and no check shall pass.
3. AC-3: If the PR body contains no block or more than one block, then the snapshot shall stop with "exactly one factory-handoff JSON block required".
4. AC-4: While the PR changes only control paths, the engine shall not start an automatic author run ("control change cannot be auto-remediated").
5. AC-5: If a Dependabot npm bump changes a pinned client CLI version in `factory/package.json` without the matching `clients.VERSIONS` (finding F32), then the trusted regression test `test_standard_npm_lock_matches_reviewed_cli_versions` shall fail and `factory/deterministic` shall not pass.

## Verification

```sh
gh pr view <number> --json author,files,body --jq '.author.login, [.files[].path], (.body | split("factory-handoff") | length - 1)'
gh pr checks <number>
```

Expected output: author `app/dependabot` (the CLI's name for `dependabot[bot]`), only allowed paths, block count `1`; after the run, `factory/deterministic` is listed with a result for the current head, and `factory/senior-review` appears once activation and the review path are in place (advisory during the shadow phase, see `CONTRIBUTING.md`). Record run and check IDs in the PR. The live evidence for this task is the Dependabot probe of the activation smoke (review report, section 8, step 4c).

## Open questions

- Should the dispatcher synthesise the handoff for `dependabot[bot]` PRs (runner placeholder, owner = first maintainer) so that no body edit is needed? Decision by the maintainers; requires a contracts change because `runner` must currently be a configured runner.
