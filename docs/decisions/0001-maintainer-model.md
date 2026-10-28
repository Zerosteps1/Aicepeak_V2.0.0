# ADR-0001: Two code owners and how a PR gets a legitimate approval

- Status: Accepted (2026-10-28)
- Date: 2026-10-28
- Deciders: Gabriel (`Zerosteps1`)
- Related: finding F3 in the [factory review](../review/2026-10-28-factory-review.md), README activation steps 1, 2 and 7

## Context and problem statement

The desired ruleset (`tools/factory/settings.py`, `desired_state`) requires one approving review from a code owner (`required_approving_review_count: 1`, `require_code_owner_review: True`) and allows no bypass (`bypass_actors: []`). GitHub does not let pull request authors approve their own pull requests. Today Gabriel (`Zerosteps1`, ID `115100163`) is the only configured maintainer and the only code owner (`.github/CODEOWNERS`: `* @Zerosteps1`). Writer App commits do not change the PR author. As a result no PR opened by Gabriel can ever satisfy the ruleset; the factory needs two humans in practice.

## Decision drivers

- Keep the rulesets as designed: no bypass actors, no loosened approval rule.
- Every merge has a human approval by someone other than the PR author.
- Only verified identities (login and numeric ID) are maintainers.

## Considered options

1. Two verified code owners, each approving the other's PRs.
2. Add bypass actors or an admin bypass for the single owner.
3. Drop the code-owner approval requirement and rely on required checks only.

## Decision outcome

Chosen option 1.

- Felix joins as the second verified maintainer **before activation**. Felix's GitHub login and numeric user ID are verified first; then the account is added to `maintainers` in `factory/config.json`, and `.github/CODEOWNERS` is regenerated with `python3 tools/factory/settings.py codeowners`. Both changes go through one human-reviewed PR. `settings.py apply` runs only after that PR is merged.
- Both maintainers are code owners. **A PR opened by one code owner needs the approval of the other code owner.** Nobody approves their own PR, and no rule is loosened to make that possible.
- Dependabot PRs and PRs authored by an App identity are not authored by a human, so either code owner can approve them.

### Fallback when only one owner is available

GitHub's own guidance names two patterns for this situation. They are documented here and are **not active**:

- **AI-generated PRs under the Writer App identity.** If the trusted launcher (never a model worker) opens the PR with the Writer App, the PR author is the App and the available human is a legitimate approver. The Writer App already has `pull_requests: write` (`factory/github-settings.json`); opening PRs from the trusted launcher is not implemented yet and needs its own reviewed change.
- **Human PRs with required checks and thread resolution instead of a code-owner approval.** This needs a deliberate change of the ruleset desired state (a separate ADR and control PR, logged like any settings change), and is reverted when the second owner is available again.

### Consequences

- Good: rulesets stay strict; every merge has a second pair of eyes; the deadlock disappears.
- Bad / accepted cost: activation waits for Felix's verification; absence of one owner slows down the other owner's PRs.

### Confirmation

- `factory/config.json` lists two maintainers with verified IDs; `.github/CODEOWNERS` lists both and is generated, not hand-edited.
- `settings.py inspect` and `diff` show `require_code_owner_review: true` and no bypass actors after `apply`.
- The smoke PR shows that a PR opened by one owner cannot merge without the other owner's approval.

## Pros and cons of the options

### Option 2: bypass actors or admin bypass

- Good: one person can merge alone.
- Bad: removes the independent human check that the factory's trust model relies on; contradicts the policy ("no agent/bot bypasses") and the desired state.

### Option 3: required checks only

- Good: no second human needed.
- Bad: the LLM review is not yet calibrated (shadow phase); the deterministic gate alone does not replace a human approval for control changes.

## More information

GitHub documentation: "Pull request authors cannot approve their own pull requests." The fallback patterns are described in section 4.3 of the review report.
