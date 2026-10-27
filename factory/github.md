# GitHub factory research — 2026-10-27

Scope: public official GitHub documentation and official GitHub Actions release pages only. No project history, Workbrain, other private repositories, or target repository contents were read. Target metadata/configuration is being verified by the parent agent. Everything below labelled design is a recommendation/inference, not a claim that remote settings already exist.

## Implemented local settings interface

Desired settings are versioned in `factory/github-settings.json`; identities and default branch come from `factory/config.json`. Initial identity placeholders deliberately block all settings commands before network access. `.github/CODEOWNERS` initially contains comments only. Do not replace placeholders with invented values.

```sh
python3 tools/factory/settings.py inspect
python3 tools/factory/settings.py diff
python3 tools/factory/settings.py codeowners
python3 tools/factory/settings.py apply
```

`inspect` and `diff` read GitHub only. `codeowners` verifies configured human login/ID and write access using GitHub, then writes the local CODEOWNERS file; commit it through the reviewed bootstrap PR. `apply` is the explicit remote mutation command: it refuses blockers, updates only managed settings/rulesets, and reads them back. It does not create Apps, add secrets, change the GitHub plan, merge a PR, or alter other rulesets. No command here has been run against the remote repository during implementation.

App verification requires short-lived `FACTORY_PUBLISHER_APP_JWT` and `FACTORY_WRITER_APP_JWT` environment variables. These must be App JWTs, not installation tokens. They are used only for `/app` and target-repository `/installation` requests in gh subprocess environments, never written to files or printed. The normal `gh` identity needs repository administration and a private owner profile exposing the Pro plan (`read:user` for a classic/OAuth token). Unknown plan, mismatched identity, unsupported environment/ruleset endpoints, or excess App permissions blocks activation. Each JWT proof checks App ID, slug presence, exact permissions, owner account, and a live installation.

Required secrets are environment-scoped `OPENAI_API_KEY`, `FACTORY_PUBLISHER_APP_PRIVATE_KEY`, and `FACTORY_WRITER_APP_PRIVATE_KEY`. Optional author keys are `ANTHROPIC_API_KEY` and `CONTEXT7_API_KEY`. The script only reads secret names; it rejects those credentials at repository scope. Missing environment secrets are reported separately because installing fail-closed branch protection can precede filling environment credentials. `configuration_ready` is configuration evidence, not an end-to-end run success claim.

Current dispatcher contract: main workflow inputs `pr`, `feedback_kind` (`none`, `issue_comment`, `review`, `review_comment`), and `feedback_id` (`0` for no feedback). Ordinary PR/default-branch updates dispatch `none/0`. Manual retry requires a configured human maintainer. PR issue comments run through the default-branch dispatcher. Review/review-comment events use a zero-permission, no-checkout ingress because those events can load PR-controlled YAML; a default-branch `workflow_run` continuation re-reads the run/workflow and feedback APIs. The title supplies only untrusted IDs; API author/PR association and configured human identity are mandatory. The central workflow re-reads feedback again and owns replay/freshness handling. Bot/unconfigured feedback is ignored and review threads are never automatically resolved.

## Minimal workable design

Use two evaluation workflows, plus a distinct writer entry point if automated edits are required:

1. A tiny `pull_request_target` dispatcher listens to `opened`, `synchronize`, `reopened`, `ready_for_review`, `converted_to_draft`, and relevant `edited` events. It runs trusted default-branch code only. It validates target repository identity, PR number, open state, and default base branch, then dispatches the evaluation workflow with `ref` equal to the literal current default branch. It must never execute PR content. The only necessary elevation is `GITHUB_TOKEN` `actions:write` for dispatch. Optional default-branch `push` handling can dispatch all open PRs to refresh base-sensitive results.
2. A `workflow_dispatch` evaluation workflow executes its own immutable default-branch revision. Capture `github.workflow_sha`; explicitly checkout that SHA for every orchestration script. A trusted prepare job fetches the PR via the API and fixes `(repository_id, PR number, head_repository_id, head_sha, base_ref, base_sha, workflow_sha, run_id, run_attempt)`. Reject a non-default branch invocation and a stale/mismatching tuple. Do not accept a head/base SHA supplied by a caller without independently resolving it.
3. A separate ephemeral GitHub-hosted test job executes the fixed PR head (or a reproducible merge of fixed head and base). It has no environment, model/API keys, App keys, publisher credentials, or privileged token. Use `persist-credentials: false`, explicit minimum permissions, and **`cache-mode: none`**. Trusted harness/configuration remains outside the untrusted checkout; never import a PR helper as orchestration. Do not use self-hosted runners. Private checkout needs a read token; if "no secrets" means literally no credentials available to the test process, execute it in an isolated container with no credential environment, host HOME, runner directories, or Docker socket mounted. Merely saying `contents:read` is not literal zero credentials.
4. Fresh privileged reviewer/publisher jobs use only the trusted orchestration SHA and environment-restricted credentials. They inspect PR text/diffs as data, never execute PR code, and never execute artifacts. A final publisher runs with `if: always()` and explicitly requires every required job's actual result to be `success`; missing, skipped, cancelled, malformed, or stale results are failures/action-required, not `neutral`/`skipped`. Re-fetch live PR head/base before publishing. Publish the external App check on **the PR head SHA**, not the dispatch/default-branch SHA. Record the exact head/base/workflow tuple in check `external_id` and output.
5. A separate writer App can create/update only controlled topic branches and draft PRs. Its token cannot publish checks, change workflows, change repository settings, or bypass either ruleset. Never run candidate code in the writer process. Constrain destinations and patch paths in trusted code; use the readback state and expected old head before updating a branch.

Why this design: it keeps PR YAML from controlling evaluation, avoids cross-run artifacts as a control channel, and avoids executing PR code under `pull_request_target`. It requires no webhook server, database, queue, or additional repository. Workflow dispatch run jobs are not themselves sufficient required PR checks; the external publisher App supplies those.

GitHub says `pull_request_target` uses the default branch's workflow, while `pull_request` uses the PR merge workflow; it warns against executing untrusted code with secrets, including downloaded artifacts. The current policy document says the planned default public-repository block does not apply to private repositories. [Securely using pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)

`github.workflow_sha` is the workflow file commit; `github.workflow_ref` identifies its path/ref. Pin trusted script checkout to the SHA, not a moving branch. [Contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context)

`POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches` requires Actions write. Its body is `{"ref":"main","inputs":{"pr_number":"123"}}`; `ref` accepts a branch or tag name, so select the known default branch and validate it inside the run. [Workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)

Current workflow syntax supports top-level or job-level `cache-mode` values `read`, `write`, `write-only`, and `none`, enforced through scoped cache tokens. `none` denies both restore and save. [Workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#cache-mode)

`workflow_dispatch` otherwise has cache write access in the default-branch scope. Merely omitting a cache action is not the desired boundary against arbitrary code. [Dependency caching reference](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#controlling-cache-access-with-cache-mode)

## Events, checks, drafts, and recursion

Do not assume a `GITHUB_TOKEN` push triggers follow-up CI. Dispatch and repository-dispatch are documented exceptions. Current documentation additionally says token-generated PR opened/synchronize/reopened events can create approval-required runs, so the older blanket claim that all token PR events never run is now inaccurate. Using the writer App avoids reliance on this special behavior. [Triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)

External App checks are evaluated even when created from dispatch orchestration. Native Actions job checks from dispatch/workflow_run do not satisfy branch-ruleset PR checks. Latest commit SHA matters; skipped and neutral checks can satisfy protection, so the factory must not publish those for incomplete validation. If a test merge commit has checks, GitHub can evaluate the merge commit rather than head. Avoid producing conflicting same-name native checks. [Troubleshooting required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)

Draft PRs cannot merge. Code-owner review requests happen when ready for review. Design: drafts may run cheap tests but should retain an incomplete/action-required factory gate until explicitly ready; include `ready_for_review` and `converted_to_draft` in event handling. [Pull requests](https://docs.github.com/en/pull-requests/reference/pull-requests#draft-pull-requests)

`workflow_run` is an alternative, not needed in the recommended minimum: its trusted continuation can access secrets even when the preceding workflow cannot. It fires regardless of predecessor conclusion; it requires its workflow on default branch; the chain is limited to three levels. Its workflow name filter alone is not sufficient provenance. [Workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)

## Provenance when reading checks, runs, and artifacts

Design invariants:

- Resolve all control state through GitHub API responses for the exact target repository. A comment, artifact manifest, model response, check title, branch name, or caller input is not authoritative provenance.
- Check identity: verify returned `app.id` equals the numeric publisher App ID, exact check name, exact head SHA, status/conclusion, current tuple, and expected external ID. App ID is not installation ID, client ID, bot user ID, or workflow ID.
- Run identity: verify repository ID, exact run ID/attempt, workflow ID and path, expected event, head repository, `head_sha`, branch/ref, and conclusion. A `pull_request` run's head SHA and a dispatch run's head SHA have different meaning; dispatch run SHA is orchestration/default branch, not evaluated PR head. Preserve the independent trusted PR tuple.
- Artifact identity: list artifacts for the exact authenticated run ID, require an exact artifact ID/name and non-expired bounded size, verify `workflow_run.id`, repository/head-repository IDs, expected run SHA, and `digest` if supplied. Artifact manifests are still untrusted. Extract outside executable workspace with traversal/link/size protections, then parse strict bounded JSON. Never load a Python module, shell fragment, executable, generated action, or package from the archive in a privileged job.
- Simplest evaluation avoids this artifact boundary: final publisher reads trusted `needs.<job>.result`; test output artifacts are diagnostic only. AI review outputs shared between privileged trusted jobs need schemas and tuple validation, but must never supply destination branch/check IDs or executable commands.

Checks API exposes `app`, `head_sha`, check suite, and PR associations; create uses `name`, `head_sha`, optional `external_id`/`details_url`, `status`, and `conclusion`. Creating/updating requires App Checks write. Fork PR associations can be empty, so do not infer authenticity from that list alone. [Checks API](https://docs.github.com/en/rest/checks/runs)

Workflow run responses include `id`, `workflow_id`, `path`, `event`, `head_sha`, `run_attempt`, repository/head-repository objects, and `referenced_workflows` with SHA/ref. These are API metadata; a workflow name in payload data is not a substitute. [Workflow runs API](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run)

Artifact API responses include `id`, `size_in_bytes`, `expired`, `digest`, and `workflow_run` with run/repository/head-repository IDs, branch, and SHA. A digest proves correspondence to stored bytes, not that their content is safe or approved. [Artifact API](https://docs.github.com/en/rest/actions/artifacts#get-an-artifact)

## Two Apps and credential placement

Recommended permissions:

| Identity | Required access | Explicitly absent |
|---|---|---|
| Reviewer/check publisher App | Contents read, Pull requests write, Checks write, Actions read | Contents write, Actions write, Workflows write, Administration, bypass |
| Branch writer App | Contents write, Pull requests write; implicit metadata read | Checks/statuses write, Actions write, Workflows write, Administration, bypass |
| Dispatcher GITHUB_TOKEN | Actions write, minimum contents read if using trusted scripts | App/model secrets, Contents write |
| Test-job GITHUB_TOKEN | None, or temporary Contents read solely for private checkout | Every write permission, environment secrets, App/model keys |

PR write is deliberately included for the user-requested acknowledgement/outcome/dispute comments and labels. It also permits reviews/merges at the API permission level; the separate human-only update ruleset and human CODEOWNERS requirement block App merges and substitute approvals. Check-source UI discovery documentation currently mentions `statuses:write` and a recent check; if required during bootstrap, document that permission explicitly instead of silently assuming Checks write is enough for the picker. REST rulesets directly expose `integration_id`; verify effective configuration and a real App-origin check.

Keep every App private key and model key in protected environments, never repository/organization secrets accessible to arbitrary same-repository PR workflows. A read-only default `GITHUB_TOKEN` is a default, not a maximum a modified workflow cannot request. The publisher App binding prevents native GitHub Actions from forging the factory gate. [Secure use reference](https://docs.github.com/en/actions/reference/security/secure-use)

Mint installation tokens scoped to the exact target `repository_ids` and explicit permission subset; verify returned repositories/permissions. They expire after one hour. Do not give these tokens to an LLM or untrusted test process. [Installation token generation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)

## Repository enforcement: two independent rulesets

Inference from the documented rule aggregation: use one ruleset for mandatory quality controls with **no bypass actors**, and a second for who may update default branch. Humans receive PR-only bypass of the second rule alone; neither human nor App bypasses quality controls. Repository admins can still edit/delete rulesets as administrators; no repository policy can make an administrator technically unable to change the policy. [Rule layering](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets#about-rule-layering)

Illustrative exact REST body for guardrails (replace App ID; check names must match implementation):

```json
{
  "name": "Factory mandatory review and checks",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": true,
        "require_last_push_approval": true,
        "required_approving_review_count": 1,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "do_not_enforce_on_create": false,
        "strict_required_status_checks_policy": true,
        "required_status_checks": [
          {"context": "factory/ready", "integration_id": 123456}
        ]
      }
    }
  ]
}
```

Second independent ruleset (replace with verified **human** numeric user ID):

```json
{
  "name": "Default branch updates by human PR merges only",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [
    {"actor_type": "User", "actor_id": 12345, "bypass_mode": "pull_request"}
  ],
  "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
  "rules": [
    {"type": "update", "parameters": {"update_allows_fetch_and_merge": false}}
  ]
}
```

Endpoint: `POST /repos/{owner}/{repo}/rulesets` (Administration write). Current API version shown by docs: `2026-03-10`. Current schema supports actor types `Integration`, `OrganizationAdmin`, `RepositoryRole`, `Team`, `DeployKey`, **`User`**. `OrganizationAdmin` does not apply to personal repositories. `actor_id` is required for Integration/RepositoryRole/Team/User. Bypass modes are `always`, `pull_request`, `exempt`; PR mode applies only to branch rulesets and not deploy keys. Do not substitute broad RepositoryRole bypass, which may include more identities than intended. [Rulesets API schema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)

Optional review-dismissal restriction is `pull_request.parameters.dismissal_restriction = {"enabled":true,"allowed_actors":[{"id":12345,"type":"User"}]}`. Supported dismissal actor types differ from bypass types: User, Team, IntegrationInstallation, RepositoryRole. Verify plan/API support before relying on the optional field. Same schema source above.

Strict checks require at least one configured context. Review approval can be made stale by PR diff/merge-base changes; CODEOWNER approval is separate from AI checks. Check expected source can be constrained to an App. [Available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

`bypass_mode: pull_request` prevents direct-push bypass while permitting that actor to bypass the particular ruleset when merging a PR. This is why quality requirements must be in the other, zero-bypass ruleset. [Creating rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository#granting-bypass-permissions-for-your-branch-or-tag-ruleset)

Use a base-branch `.github/CODEOWNERS` containing `* @VERIFIED_HUMAN` (and protect this file through that same wildcard). The human needs write access. GitHub uses CODEOWNERS from the PR base; putting an altered file in the PR cannot replace base owners for that PR. With one human owner, bot-authored PRs are reviewable; a PR authored by that same human needs another authorized reviewer/owner, rather than weakening enforcement. [Code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

## Environments: exact API settings

For each credential-bearing environment, use:

```http
PUT /repos/{owner}/{repo}/environments/factory-review
```

```json
{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}
```

Then create exactly the current default **branch**, not an equivalent tag:

```http
POST /repos/{owner}/{repo}/environments/factory-review/deployment-branch-policies
```

```json
{"name":"main","type":"branch"}
```

Repeat separately for the writer credential environment. Delete/reject unexpected extra branch/tag policies after reading existing state; do not merely add main alongside permissive patterns. Use exact branch restriction rather than "protected branches": that option can permit all branches if no branch protection exists. Default-branch renames require environment-policy reconciliation and should fail closed in the meantime. [Environment API](https://docs.github.com/en/rest/deployments/environments#create-or-update-an-environment), [deployment branch policy API](https://docs.github.com/en/rest/deployments/branch-policies#create-a-deployment-branch-policy), [deployment options](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments#deployment-branches-and-tags)

## Actions settings: exact API settings

```http
PUT /repos/{owner}/{repo}/actions/permissions
```

```json
{"enabled":true,"allowed_actions":"selected","sha_pinning_required":true}
```

```http
PUT /repos/{owner}/{repo}/actions/permissions/selected-actions
```

```json
{"github_owned_allowed":true,"verified_allowed":false,"patterns_allowed":[]}
```

```http
PUT /repos/{owner}/{repo}/actions/permissions/workflow
```

```json
{"default_workflow_permissions":"read","can_approve_pull_request_reviews":false}
```

All require Administration write. `allowed_actions` supports all/local_only/selected. Be careful: current API docs explicitly say `patterns_allowed` applies only to public repositories; do not promise a per-SHA action allowlist is enforced on a private personal repo. SHA pinning plus GitHub-owned-only is the simple enforceable proposal, subject to actual endpoint acceptance/readback. Defaults are not a substitute for explicit job permissions or App-bound check rules. [Actions permissions API](https://docs.github.com/en/rest/actions/permissions)

## Personal/private repository plan blockers

- **GitHub Pro or higher is required** for branch rulesets and CODEOWNERS enforcement in a private personal repository. GitHub Free private is a hard blocker to the requested enforcement. Branch/tag rulesets are available with Pro; push rulesets are documented for Team, so do not depend on push/file-path rulesets here. [Rulesets availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- Pro supports private environments, environment secrets, and deployment branches. Required deployment reviewers, wait timers, and other protection rules on Free/Pro/Team are public-only. Therefore do not promise a private personal environment approval gate. Use the repository's mandatory human CODEOWNER PR approval as the human merge gate. [Managing environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
- Need a real human with write access who can approve bot-authored PRs, real dedicated App installation IDs and key material, App check bootstrap, enforced active rulesets, default-branch environments, and successful endpoint readback before claiming the factory is operational. Do not fabricate or auto-substitute IDs.
- Bootstrapping the first protected workflow/CODEOWNERS revision is a real sequencing requirement. Prepare a reviewable bootstrap PR and install protections in a sequence the authorized owner can complete. Required App checks cannot be met by code that is only present on an unmerged PR; dispatch workflows must already exist on default branch. Do not label the draft scaffold as live enforcement.

## Verified release pins

Opened each official release page and followed its commit link on 2026-10-27. These were the latest releases returned then; the exact immutable commits below are suitable pinned references, subject to runner/version compatibility checks. Use only actions actually needed. No artifact actions are necessary if outputs remain within the trusted workflow and diagnostics are optional.

| Action | Release | Full SHA | Evidence |
|---|---|---|---|
| actions/checkout | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` | [Release](https://github.com/actions/checkout/releases/tag/v7.0.1), [commit](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1) |
| actions/setup-python | v7.1.0 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` | [Release](https://github.com/actions/setup-python/releases/tag/v7.1.0), [commit](https://github.com/actions/setup-python/commit/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0) |
| actions/upload-artifact | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` | [Release](https://github.com/actions/upload-artifact/releases/tag/v7.0.2), [commit](https://github.com/actions/upload-artifact/commit/cf430e030ddbb5b0abf93d22962f4752f3646cd9) |
| actions/download-artifact | v8.0.2 | `9000827ccba6bdab643e8b6fd33ac0654aef8333` | [Release](https://github.com/actions/download-artifact/releases/tag/v8.0.2), [commit](https://github.com/actions/download-artifact/commit/9000827ccba6bdab643e8b6fd33ac0654aef8333) |

Checkout v7 additionally blocks unsafe fork head checkouts in pull_request_target/workflow_run unless explicitly opted out. Do not opt out to execute untrusted code in a privileged job.
