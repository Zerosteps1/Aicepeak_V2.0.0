# GitHub operation and technical sources

Status: 2026-10-28. The factory is on `main`; both rulesets, App identities and the main-only credential environment are verified active. **The review-fix loop passed live on 2026-10-29 (PR #20); device, concurrency and identity probes are still pending.** Actual evidence and blockers are in [evidence.md](evidence.md), the operating entry points are in the [README](../README.md). This file describes the factory, not a product architecture.

## Inspect and apply settings

`factory/github-settings.json` holds the protection requirements; `factory/config.json` holds the verified identities, App IDs and the default branch. Missing App IDs block activation. Gabriel is recorded as `Zerosteps1`. Felix uses `truFelix-Zentru` (345378269) and `ftrutschnig` (306226744), both confirmed by Gabriel and verified with repository write access on 2026-10-28. They are one person, not two independent reviewers.

Nachtrag 28.10.2026: Gabriel hat Publisher-App `5510081` und Writer-App `5510093`
registriert und die Rechte gemäß Tabelle gesetzt. Die authentifizierte Prüfung
von App, Installation und exakten Rechten wurde mit dem korrigierten Inspector
in Gabriels Terminal erfolgreich ausgeführt; die übermittelte Ausgabe bestätigt
die Installationen `176168187` (Publisher) und `176168111` (Writer).
Ein zweiter lesender Lauf nach Gabriels Konfigurationsänderung bestätigte für
`factory-control` ausschließlich Branch `main`. Der letzte vollständige Abgleich aus Gabriels Terminal nach PR #11 bestätigt beide App-Secrets und `CONTEXT7_API_KEY`, keine Blocker und keine Konfigurationsabweichungen. Die Review-Umstellung ist auf `main`; die tatsächliche Review-Fix-Abnahme bleibt gesondert nachzuweisen.

Der App-Prüfweg sendet JWTs direkt per HTTPS als `Authorization: Bearer` und
erlaubt nur die beiden lesenden Identitäts-/Installationsabfragen. `gh` bleibt
der administrative Transport mit der eigenen menschlichen Anmeldung. JWTs
gehören nicht in Kommandozeilenargumente; `GH_TOKEN` allein wäre für App-JWTs
falsch, da gh 2.87.0 das Schema `token` verwendet.
[Geprüfter CLI-Quellstand](https://github.com/cli/cli/blob/v2.87.0/api/http_client.go).

Vor dem Setzen von App-Secrets zuerst `inspect` ausführen und für `factory-control`
die ausschließlich auf `main` begrenzte Branch-Policy nachweisen. Nicht pauschal
`apply` ausführen, um fehlende Secrets zu beheben: es aktiviert auch Pflichtchecks.
Der lokale Business-Reviewer ist über den zusammengeführten PR #9 und die
Reparatur #11 auf `main`; er benötigt keinen OpenAI-API-Schlüssel. GitHub
koordiniert und veröffentlicht, der Modelllauf erfolgt auf dem Maintainer-Gerät.
Die einmalig ausdrücklich genehmigte Installation von #11 ist abgeschlossen;
beide Pflichtchecks wurden wiederhergestellt. Sie ist kein allgemeiner Bypass.

```sh
python3 tools/factory/settings.py codeowners
python3 tools/factory/settings.py inspect
python3 tools/factory/settings.py diff
python3 tools/factory/settings.py apply
```

`codeowners` checks login, numeric ID and write permission through GitHub and writes the local CODEOWNERS file, which is merged through a PR. `inspect` and `diff` are read-only. `apply` changes only the managed settings, refuses known blockers and reads the state back. Other rulesets stay in place. Apps, secrets, plans and merges are never set up automatically.

Administration needs a separately authenticated human `gh` identity. The App check needs short-lived `FACTORY_PUBLISHER_APP_JWT` and `FACTORY_WRITER_APP_JWT` as secret environment variables: real App JWTs, not installation tokens. Generate them from App ID and private key following the [official JWT guide](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app). The checker neither writes nor prints them. It checks `/app`, the installation in the target repository, the exact permissions and that the App is not suspended. The automation creates its own short-lived installation tokens, limited to the target repository and the permissions it needs. [Installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)

| Identity | Permissions | Use |
|---|---|---|
| Publisher App | Contents read, Pull requests write, Checks write, Actions read, Metadata read | Authenticated checks, PR feedback, labels and budget ledger |
| Writer App | Contents write, Pull requests write, Metadata read | Only the validated patch onto the matching PR branch |
| Dispatcher `GITHUB_TOKEN` | Contents read, Pull requests read, Checks read, Actions write | Check metadata, cancel stale runs, start the central run |
| Test host (GitHub runner) | Read permissions listed per job | Fetch check material; no GitHub token in the model worker or test container |
| Senior reviewer (maintainer's Mac) | Publisher App installation token (key from the login keychain); the maintainer's own `gh` login for a correction dispatch | Read the pending receipt and publish the review; the Codex session gets no GitHub credential |

The Apps have no Administration, Workflow or bypass permissions. `contents:write` or PR write permissions alone do not forbid merges; the rulesets below enforce the identity boundary.

## Enforcement after activation

Two rulesets apply together on the actual default branch:

1. **Quality, maintainer bypass only:** PR required, resolved review threads, up-to-date base, protection against deletion and force push, and both required checks from `required_checks`, each bound to the expected publisher `integration_id` (see [required checks](#required-checks-and-activation)). The approved setting `require_second_human_review: false` requires zero additional approving reviews, no mandatory Codeowner approval and no separate last-push approval. Gabriel or Felix makes the human decision by merging. With `maintainer_check_bypass: true` (decided by Gabriel on 2026-10-28) the verified maintainer accounts are `pull_request`-mode bypass actors: they may merge a PR whose checks are red or missing, GitHub records the bypass, and Apps and bots never get one. CODEOWNERS still records ownership and can request optional reviews. Configurations without the setting retain the previous second-review requirement; invalid non-boolean values block activation.
2. **Updates by humans only:** default-branch updates are blocked; only verified human users get a PR-only bypass of this second rule. Apart from the maintainers' PR-merge bypass, the first rule stays mandatory. No agent or bot gets an exception, and there is no auto-merge.

The combination follows the documented [aggregation of rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets#about-rule-layering). Real negative probes remain necessary. Administrators can always change settings; the factory does not claim immutability against the repository administrator. [Rulesets API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset), [available rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

CODEOWNERS from the protected base identifies ownership for all files, in particular the rules and itself. A change inside a PR does not replace that PR's own owners. Under the approved single-maintainer merge policy, a PR Gabriel opens can be merged by Gabriel after the required checks and resolved threads; the same applies to Felix. CODEOWNERS does not enforce a second approval in this configuration. [CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

The environment `factory-control` allows exactly the default branch of type `branch`, no same-named tags or wildcards. It holds the required secrets `FACTORY_PUBLISHER_APP_PRIVATE_KEY` and `FACTORY_WRITER_APP_PRIVATE_KEY`. `CONTEXT7_API_KEY` is required for the configured automatic correction. There is no Anthropic key: the author job and the separately guarded federation-smoke job authenticates through Workload Identity Federation, see [Clients](clients.md). The federation rule `aicepeak-factory-author` (created 2026-10-28) matches subject `repo:Zerosteps1@115100163/Aicepeak_V2.0.0@1436114884:environment:factory-control`, audience `https://api.anthropic.com` and the claims `repository_owner=Zerosteps1`, `repository_owner_id=115100163`, `repository=Zerosteps1/Aicepeak_V2.0.0`, `repository_id=1436114884`, `ref=refs/heads/main`, `event_name=workflow_dispatch` and `workflow_ref=Zerosteps1/Aicepeak_V2.0.0/.github/workflows/factory.yml@refs/heads/main`. It is enabled for exactly one workspace, was live-tested with scope `workspace:developer` (an inference-only scope suffices for model calls) and a token lifetime of 10 minutes, and targets the service account `aicepeak-factory-author`; its IDs are in `factory/config.json` `anthropic_federation`. Failed exchanges show their reason in the Console's authentication history. There is no `OPENAI_API_KEY` and no Codex access token: the senior review runs on the maintainer's Mac, and GitHub-hosted runners never receive the Codex token. Same-named repository secrets are rejected as an unsafe state. Default `GITHUB_TOKEN`: read, no PR approval. Only GitHub-owned Actions, full SHA pins and `cache-mode: none`. [Environments](https://docs.github.com/en/rest/deployments/environments#create-or-update-an-environment), [branch policies](https://docs.github.com/en/rest/deployments/branch-policies#create-a-deployment-branch-policy), [Actions permissions](https://docs.github.com/en/rest/actions/permissions), [cache-mode](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#cache-mode)

**Strict order: deployment branch policy before secrets** (review finding F2). The first pipeline run created `factory-control` automatically without a deployment branch policy. A secret stored in that state would be available to workflows on any branch. Therefore:

1. Configure `factory-control` with Selected branches and tags → Branch `main` only. Do not enable unavailable required checks merely to create this environment boundary.
2. Run `settings.py inspect`: the environment must show the custom branch policy with exactly the default branch. Other ruleset changes may still appear in `diff` until activation.
3. Only then add the environment secrets.

`settings.py` does not enforce this order yet: `inspect` reports a missing policy as a pending change, not as a blocker. Follow the order manually.

The public target and the managed administrative settings were verified through GitHub and the maintainer's authenticated inspection. The reported plan is `null`; no private-plan entitlement is inferred from this public repository. `settings.py` blocks private activation without a documented matching plan. Recheck feature availability before changing visibility; additional environment review approvals are not assumed. [Availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [environment plans](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## Executable review and fix flow

`factory-dispatch.yml` handles PR creation, new commits, reopening, ready/draft, edits, human PR comments and default-branch updates. It loads only the pinned protected workflow revision. For reviews and inline comments, `factory-feedback.yml` provides only numeric references, without permissions, checkout or secrets. The trusted `workflow_run` dispatcher reads run, workflow, human author and PR association again from GitHub. Manipulated titles or comments formatted the same way are no authorization. [Events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [secure pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)

`factory.yml` runs only through `workflow_dispatch` on the protected default branch. A normal run is **snapshot → tests → publish**: `Snapshot` binds the PR and reserves the `factory/senior-review` check, `Deterministic tests` runs secret-free, and `Publish gates` creates `factory/deterministic`. No job calls a model and no job holds a model credential for review. Native dispatch job checks are not used as PR gates; the publisher App creates the separate factory checks on the checked PR head. [Required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks), [Checks API](https://docs.github.com/en/rest/checks/runs)

When the deterministic checks pass, `Publish gates` leaves `factory/senior-review` **in progress** ("Awaiting senior review") with a pending receipt: phase `awaiting_review`, the authenticated snapshot (repository, PR, head/base/policy SHA, run ID and attempt, files, work order, feedback digest, draft and control-change flags) and the test evidence. The check summary names the command for the maintainer. When the checks fail, the PR is a draft or the snapshot is stale, both checks are completed as `failure`, no review is requested and the PR is labeled `needs-author-action`. `Publish gates` also requires the PR head to contain the current `main` commit (compare API, `behind_by` 0). GitHub moves a PR's base SHA on every push even when `main` was not merged into the branch (PRs #4 and #5), so base equality alone does not prove that the tested head is what a merge produces; such a head fails with the hint to use "Update branch". Because every maintainer merge uses the ruleset bypass, which skips GitHub's own up-to-date and check rules, `session.py merge` re-verifies head, current `main`, both App-bound checks, the reviewed handoff and feedback, and open threads. Because GitHub's merge pins only the head, it serializes merges with the lock `refs/tags/factory-merge-lock` (ref creation is atomic; an existing ref is refused), re-reads `main` and the PR while holding it, and checks the merge commit's parents afterwards. The tag push it causes is ignored by the dispatcher, which acts only on `main`. The maintainer-local reviewer `python3 tools/factory/local_review.py --pr N` requests an exclusive claim through the serialized main workflow, then submits a separate neutral result record. Only that workflow finalizes the gate; see [Clients](clients.md#senior-reviewer-maintainer-local).

Every run binds repository, PR, head, base and policy SHA, run ID and run attempt. Check evidence is verified against authenticated GitHub run, workflow and job data. Test orchestration comes from the base; candidate code runs in a container without network, secrets, home or Docker socket. The publisher accepts no success JSON from the PR. Incomplete, skipped, cancelled or contradictory evidence does not approve. [Run API](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run), [workflow context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context)

Author work starts only from a separate correction dispatch for a published review:

```sh
gh workflow run factory.yml --ref main -f pr=123 -f correction=<check_id>
```

`local_review.py` sends this itself when a review requests changes and `automatic_correction` is `true`; a maintainer can also send it by hand. Every correction rechecks that this is still the latest authenticated review for the PR, including retries at the same commit. The run skips the snapshot and starts with the **Correction gate**, which refuses unless `automatic_correction` is `true` (the target configuration enables it; it takes effect only after the reviewed merge), the run is attempt 1, the triggering actor is a configured human maintainer, the check is an authentic, completed publisher `factory/senior-review` check of that PR with a valid `changes_requested` review, the PR changes no control paths, the run executes the reviewed policy revision, and head, base, handoff and feedback are still current. If `main` moved on after the review, the gate refuses; the next pipeline run and review come first. The gate then reserves an author round (`factory/author-reservation`, `limits.max_run_cost_usd`) bound to its own run ID.

The `Author correction` and `Push correction` jobs check that the reservation belongs to the current correction run. The allowlist runner gets no GitHub credentials. The writer checks run, artifact ID/digest, exactly one bounded patch, work order, allowed paths and current head; it runs no artifact programs. Changes to control rules are excluded. An App push should trigger the next check run; this actual follow-up trigger is part of the still open smoke evidence. [Artifacts](https://docs.github.com/en/rest/actions/artifacts#get-an-artifact), [follow-up triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)

Branch updates use the atomic [`updateRefs`](https://docs.github.com/en/graphql/reference/git#updaterefs) mutation with `beforeOid`, `afterOid` and `force:false`. This also rejects an intermediate reset to an ancestor. REST `force:false` alone would only check fast-forward. Source read; no real mutation executed yet.

## Required checks and activation

The reviewed target configuration requires both `factory/deterministic` and `factory/senior-review`, bound to publisher App 5510081. `automatic_correction: true` enables the validated Claude runner after merge; missing credentials, model errors, invalid evidence and exhausted budgets block rather than becoming skipped approvals. The earlier draft's advisory-only shadow phase is not the target state requested by the maintainer.

The current remote rulesets are active and match the versioned configuration. The maintainer's post-merge `diff` returned `changes: []`, `blockers: []`, no missing environment secrets and `configuration_ready: true`; the two rulesets were also read independently through the connector. This confirms administrative readiness, not full operation. Before operational acceptance complete the genuine review/correction/writer smoke and identity-negative probes. Keep normal checks enabled; the documented one-off bootstrap exception for #11 is closed.

## Feedback, retry and troubleshooting

Ordinary comments, reviews and inline comments of verified humans are read again in the next run. The review answers relevant questions; corrected or disputed findings receive the author report. New feedback invalidates old context. Human threads stay open until humans resolve them. An expanded scope first needs a reviewable work order approved in the repository.

A PR-wide, App-authenticated ledger references real check records and keeps budgets and rounds across rebase and force push. At most two automatic corrections (`limits.max_rounds`) and at most `limits.max_reviews_per_pr` claimed senior review attempts per PR, including dry-runs and failed attempts. The same context must not be processed twice. GitHub serializes review ownership/publication and correction writers. Only authenticated runs for old heads or bases are actively cancelled; pure title edits do not interrupt a valid run. Fresh state checks before every relevant stage, before publication and before the atomic push remain required as well. Provider requests that already started can incur costs until cancelled.

Without a new commit, a verified maintainer can deliberately start a new run:

```sh
gh workflow run factory.yml --ref main -f pr=123 -f retry=true
```

Replace `123` with the actual PR number. GitHub's "Re-run jobs" is refused so that old budget reservations are not reused. A retry resets neither rounds nor budget. Every new pipeline run leaves a new pending senior review; run `local_review.py --pr 123` again. With exhausted budget, conflicts, missing credentials or no progress: `needs-author-action` and the concrete launcher/skill path in the PR. No silent client switch.

Troubleshooting: first compare run/check ID and head, then the doctor and `settings.py inspect/diff`; check reviewer access separately with `python3 tools/factory/local_review.py --smoke` on the reviewer Mac. Rule changes, raised limits and lasting decisions need a PR and human approval. Never remove a protection rule to force a green result.

## Verified pins and updates

Verified on 2026-10-27 against official release and commit pages:

| Action | Version | SHA / source |
|---|---|---|
| checkout | v7.0.1 | [`3d3c42e5aac5ba805825da76410c181273ba90b1`](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1) |
| upload-artifact | v7.0.2 | [`cf430e030ddbb5b0abf93d22962f4752f3646cd9`](https://github.com/actions/upload-artifact/commit/cf430e030ddbb5b0abf93d22962f4752f3646cd9) |

Only these two Actions are used. Action, Docker and client package updates arrive as Dependabot PRs. Check-tool versions and SHA-256 sums are in `factory/tools.lock.json`; upgrading them needs an explicit factory work order and a new binary and workflow check. No product package managers or dummy checks. The sources cover technical contracts, not product requirements.
