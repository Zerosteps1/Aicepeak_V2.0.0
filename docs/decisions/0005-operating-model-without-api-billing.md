# ADR-0005: Operating model without API billing (S1)

- Status: Accepted (2026-10-28)
- Date: 2026-10-28
- Deciders: Gabriel (`Zerosteps1`)
- Related: review report sections 4.4 and 5 ([factory review](../review/2026-10-28-factory-review.md)); findings F5, F28, F33, F34; [ADR-0002](0002-single-reviewer-and-model-pairing.md)

## Context and problem statement

The whole model path of the factory is built on API billing: `engine.review_stage` calls `api.openai.com` with `OPENAI_API_KEY`, the broker holds `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, and budgets are USD reservations computed from list prices. The maintainer does not want usage-billed operation and wants to use existing subscriptions: ChatGPT Business for Codex, and a Claude plan. The desired flow stays: the PR is created in a working session, an independent reviewer starts in a **new session** with GPT-6 Astra at effort high, findings go back to the author, the fix is re-reviewed, and humans merge.

The GitHub side (dispatcher, snapshot binding, deterministic tests, Publisher and Writer Apps, rulesets, ledger) does not depend on billing and stays.

## Decision drivers

- No usage-based API invoice.
- Only paths the vendors document and permit for this use; no unofficial endpoints, no shared accounts.
- Structured, schema-validated review that a ruleset can require.
- No credentials inside model workers.
- Reviewer and author from different model families (ADR-0002).

## Considered options

Paths A–H as evaluated in section 4.4 of the review report; combined into operating models S1–S4 (section 5).

## Decision outcome

Chosen: **S1 = reviewer through path D plus automatic correction through path A.**

**Reviewer (path D).** GPT-6 Astra, effort `high`, run by `tools/factory/local_review.py` as `codex exec --ephemeral --sandbox read-only --output-schema factory/review.schema.json` under a **ChatGPT Business access token** on the maintainer's **trusted machine**, in a new session: a fresh `CODEX_HOME` and `HOME`, no personal configuration, no memories, an empty working directory. The token reaches Codex only as the `CODEX_ACCESS_TOKEN` environment variable of that one process (no saved login). The session is tool-less: Codex 0.164.0 feature flags alone leave a code-mode `exec` tool with shell and patch access, so the reviewer also generates a model catalog without shell and patch tools, disables agents, and checks the model-visible tool surface with `codex debug prompt-input` before every run (fail closed). The result is validated against the schema and the SHA binding (`contracts.validate_review`) and published as `factory/senior-review` through the Publisher App. OpenAI documents access tokens for trusted automation under the workspace identity and excludes public GitHub runners, so the reviewer never runs on GitHub Actions. Usage is recorded as turn/token counters instead of USD and capped by `limits.max_reviews_per_pr`.

**Author (path A).** Claude Code behind the **existing credential broker**, billed to the Console organisation linked to the **Claude Team plan** and funded by the plan's monthly API credit (available since 2026-10-07, "never charged to your Claude plan", pooled up to 500 USD, stops when exhausted). The pipeline holds **no Anthropic key**: the author job's GitHub OIDC identity is exchanged through **Workload Identity Federation** for a short-lived Anthropic token. The broker performs and refreshes the exchange; the rule is pinned to this repository, the `factory-control` environment, `main` and `factory.yml`, with scope `workspace:inference`. The worker still holds no credential; the USD ledger stays for the author and settles against provider-reported usage. `--max-turns` and `--max-budget-usd` are added as a second brake. Automatic correction is enabled only after the shadow phase.

**No `OPENAI_API_KEY`.** It is removed from the pipeline, the broker configuration and `factory/github-settings.json` (PR B1).

**Credential placement.**

- Reviewer machine login keychain: the ChatGPT Business access token (short lifetime) and the Publisher App private key.
- Environment `factory-control` (default branch only, branch policy before secrets): `FACTORY_PUBLISHER_APP_PRIVATE_KEY`, `FACTORY_WRITER_APP_PRIVATE_KEY`, `CONTEXT7_API_KEY`. No `ANTHROPIC_API_KEY`; the federation IDs in `factory/config.json` are not secret.

**Interlock.** The pipeline leaves `factory/senior-review` in progress with an authenticated receipt; the local reviewer completes that check with the same receipt format as before. On `changes_requested` it starts a separate run with `gh workflow run factory.yml -f pr=N -f correction=<check_id>`. Its Correction gate re-verifies the Publisher receipt, the maintainer actor and the policy revision before it reserves an author round; author and push jobs verify that correction run. The GitHub review job disappears.

### Consequences

- Good: no API invoice; the factory's trust model stays intact; reviewer and author are different families (F34 resolved); `@codex review` (included in Business) is available as a free second opinion.
- Bad / accepted cost: the review depends on a running trusted machine; the reviewer consumes the maintainer's Codex seat window (GPT-6 Astra on a Business standard seat: about 5–45 messages per 5 hours, shared with interactive use), so consumption is measured during the shadow phase and a dedicated factory seat or flexible billing may be needed; author runs stop when the monthly credit is used up.
- Public list prices: ChatGPT Business 20 USD per user per month billed annually (from 2 users) or 25 USD monthly; Claude Team at Anthropic's list price, with a monthly API credit of 20 USD (Standard) or 100 USD (Premium) per seat.

### Confirmation

Before activation:

- The Console organisation is linked to the Team plan (7-day waiting period); the first author run shows a successful exchange in the Console's workload identity authentication history and appears as credit usage of the rule's workspace, not as an invoice.
- `python3 tools/factory/local_review.py --smoke` passes with the access token, and a review run on the smoke PR produces a schema-valid review that passes the binding check and appears as `factory/senior-review`; the run appears in the Codex usage dashboard.
- `grep -r OPENAI_API_KEY` finds no mandatory path after PR B1.
- `--max-budget-usd` triggers with a deliberately low value.

## Pros and cons of the options

| Option | Why not chosen |
|---|---|
| S2: Codex cloud review and `@codex fix` as gate | Advisory only, produces no check run a ruleset can require, review rules come from the PR-controlled `AGENTS.md`, depth not controllable. Kept as a free second opinion. |
| S3 / paths F–G: Hermes agent with Claude/Codex OAuth or Nous Portal | No structured output (only stream-json), Codex suitability not documented and relies on an unofficial backend path, Claude use only at discretion and billed at API prices; no gain. |
| S4: local reviewer, human corrections only | Not rejected as such: it is the first stage of S1 until automatic correction is enabled after the shadow phase. |
| Path E: broker swaps a job token for Codex OAuth and calls `chatgpt.com/backend-api` | Unofficial endpoint ("do not point it at ChatGPT's backend-api"); risk under Services Agreement 3.3(i) (circumventing usage limits). Excluded. |
| Codex author with a placeholder token exchanged by the broker | Credential in the worker, unofficial endpoint, and the same model family as the reviewer. Rejected. |
| Path C: personal `auth.json` (Plus/Pro) on a private runner | Documented as "advanced", explicitly not recommended and "not for public repositories"; the consumer terms forbid programmatic extraction of output. Emergency only. |
| Path B: Claude Code with `CLAUDE_CODE_OAUTH_TOKEN` | Allowed for "ordinary, individual usage" only; the token would live in the worker; no USD control. |
| ChatGPT auth on GitHub-hosted runners | OpenAI: "Do not use this workflow for public or open-source repositories." |
| Keep API billing (`OPENAI_API_KEY`) | Contradicts the maintainer's requirement. |

## More information

- `https://learn.chatgpt.com/docs/auth`, `https://learn.chatgpt.com/docs/auth/ci-cd-auth`, `https://learn.chatgpt.com/docs/cli/reference`, `https://learn.chatgpt.com/docs/non-interactive-mode`
- Implementation: PR B1 (Codex start, allowlist, local reviewer, pipeline without `OPENAI_API_KEY`) and PR B2 (broker settlement, limits, egress self-test, Claude author configuration), review report section 7.
- Open points: live test of `--output-schema` under a Business token; status of the Codex 5-hour window; reported 401 problems of `claude setup-token` in containers do not affect path A.
