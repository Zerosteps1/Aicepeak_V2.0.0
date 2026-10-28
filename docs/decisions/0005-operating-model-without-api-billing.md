# ADR-0005: Subscription-backed review and bounded API authoring

- Status: Proposed — pending human review and merge
- Date: 2026-10-28
- Deciders: verified maintainers; no acceptance or activation recorded by this amendment
- Related: [FACTORY-001](../work/FACTORY-001.md); review report sections 4.4 and 5 ([factory review](../review/2026-10-28-factory-review.md)); findings F5, F28, F33, F34; [ADR-0002](0002-single-reviewer-and-model-pairing.md)

## Context and problem statement

The maintainer wants to use ChatGPT Business and the existing Claude plan while retaining both Codex and Claude Code. Authentication, consumption of included allowances, and additional billing are separate questions. This proposal cannot guarantee operation without an API invoice.

The intended review remains a fresh, independent session with `gpt-6-astra` at effort `high`, structured findings, bounded corrections, re-review and human merge. This ADR does not activate a runtime path or change required checks. Its earlier title remains in the filename to preserve existing links.

## Proposed operating model

**Reviewer.** Use the native Codex CLI on a trusted maintainer machine with a finite-lifetime Business access token. OpenAI documents `CODEX_ACCESS_TOKEN` for trusted non-interactive Codex workflows in Business and Enterprise workspaces; it represents the creator's workspace identity. It must not be exposed to untrusted PR execution. [OpenAI access-token documentation](https://learn.chatgpt.com/docs/enterprise/access-tokens)

The companion reviewer implementation uses a fresh disposable home and session, bounded review material, schema validation, a model catalog without shell/patch tools, and a preflight check of the model-visible tool surface. The provider token is confined to the tool-less reviewer process; publisher credentials remain outside it. A successful model response is separate from authenticated publication for the correct PR, head and trusted policy revision.

**Claude author.** The companion implementation configures Claude Code as the automatic author behind the isolated credential broker. In GitHub Actions, Workload Identity Federation exchanges the job's identity for a short-lived Anthropic token bound to a service account. The author worker receives only its disposable broker credential. WIF changes authentication; the Messages requests still consume Claude API usage in the configured Console organization and workspace. [Anthropic WIF documentation](https://platform.claude.com/docs/en/manage-claude/workload-identity-federation)

**Codex author.** Both author clients remain requested. The current isolated Codex author uses `OPENAI_API_KEY`; the Business-token author path is an explicit activation blocker. OpenAI now documents a ChatGPT gateway route, so a blanket claim that the backend route is unofficial is inaccurate. However, the proposed broker-only token topology and enforcement of the existing output cap and standard tier have not been verified against that backend. Keep the credential outside the author worker, and do not remove limits or silently switch billing paths to obtain a successful response. [OpenAI gateway documentation](https://learn.chatgpt.com/docs/enterprise/connect-to-a-gateway)

A different-family advisory reviewer is optional. It does not replace the fixed Astra/high gate or create a Claude-only mandate ([ADR-0002](0002-single-reviewer-and-model-pairing.md)).

## Billing and price evidence

Checked against the linked manufacturer sources on **2026-10-28**; prices and entitlements must be rechecked before activation.

- Eligible Claude Team plans provide monthly API credits of USD 20 per Standard seat or USD 100 per Premium seat, pooled up to USD 500. The credits are claimed into a linked Console organization. New subscribers become eligible after seven days on the plan; this is not a seven-day delay after linking. Credits cover Platform API use, not interactive Claude Code subscription sessions. [Claude monthly API credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans)
- When monthly credits are exhausted, purchased credits or auto-reload can fund further usage; invoiced organizations can incur their usual charges. Requests stop only when the organization has no other credits or applicable billing. Confirm the actual organization, balance, auto-reload and contract settings. A Team subscription or successful WIF login proves none of those conditions. [Credit exhaustion and billing](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-and-team-plans)
- Anthropic lists Sonnet 5.5 at USD 2 input and USD 10 output per million tokens, with USD 2.50 for 5-minute cache writes, USD 4 for 1-hour writes and USD 0.10 for cache reads. These are published API rates, not a promise of covered usage. The repaired broker rejects 1-hour cache writes until separately supported. [Anthropic cache pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

The broker's configured reservations and usage accounting govern admission within a job. They do not establish the provider's final invoice or the available subscription balance. Keep provider spend controls and billing verification separate. `--max-turns` and `--max-budget-usd` are additional client brakes, not proof of a zero-cost run. Business reviewer usage consumes workspace entitlements; this ADR makes no fixed message allowance or subscription-price promise.

## Evidence and remaining activation checks

Evidence recorded on **2026-10-28** in the companion control change's `docs/work/FACTORY-WIF-SMOKE.md`:

- Gabriel ran the reviewer smoke from [PR #5 revision `009c010`](https://github.com/Zerosteps1/Aicepeak_V2.0.0/blob/009c010aafc9881d3e29e00b65100092fe9a7cc2/tools/factory/local_review.py) in his macOS terminal and reported `status=passed`, `model=gpt-6-astra`, `effort=high`, `auth=CODEX_ACCESS_TOKEN`, one turn, 7,330 input and 15 output tokens. This is user-reported evidence of that local authentication/model path. It does not prove PR publication, Felix's setup or the isolated Codex author.
- Federation smoke [40684684126](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40684684126) passed on main commit `70bb59f722f9f0c260f2524e21c93a1290891b47`: GitHub identity, token exchange and a minimal `claude-sonnet-5-5` response, with 18 input and four output tokens. The recorded returned scope was `workspace:developer`. This proves neither the full author/container integration nor which balance paid for the request; least-privilege scope remains a separate check.

Before declaring the factory ready, obtain evidence for each enabled author's isolated runtime and limits, both maintainers' reviewer setup, serialized authenticated publication, and the real review/fix cycle. Confirm actual billing settings and current prices. Review and merge control changes under the existing trusted policy, then activate them through the authorized administrative path. Configuration flags alone are not live acceptance evidence.

## Alternatives and consequences

- Keep the fixed native Business reviewer and use human corrections while automatic authoring is not accepted. This is a valid staged deployment.
- Add Business-authenticated Codex authoring only after a trusted smoke proves the documented route, identity handling, enforced output limits, terminal usage and tool/follow-up behavior. A text-only success is insufficient. [Gateway compatibility checks](https://learn.chatgpt.com/docs/enterprise/gateway-compatibility)
- Continue an explicitly authorized Platform API author path when needed; disclose its billing basis. Do not present it as subscription authentication.

The proposed model avoids giving provider credentials to author shells, but still depends on trusted reviewer availability, workspace quotas, API funding and a verified implementation. No alternative in this ADR grants merge permission or promises no additional charges.
