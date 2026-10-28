# ADR-0002: Fixed senior reviewer and both author clients

- Status: Proposed — pending human review and merge
- Date: 2026-10-28
- Deciders: verified maintainers; no acceptance recorded by this amendment
- Related: [FACTORY-001](../work/FACTORY-001.md); findings F10, F12, F34 in the [factory review](../review/2026-10-28-factory-review.md); [ADR-0005](0005-operating-model-without-api-billing.md)

## Context and problem statement

The existing policy fixes the gate reviewer to `gpt-6-astra` with effort `high`. The requested factory supports Codex and Claude Code as author clients. A proposal to require different model families must not silently remove Codex as an author or change the fixed reviewer.

The Codex author and reviewer may use the same model family. Review independence therefore requires a fresh session, separate instructions and evidence, no author reasoning transcript, and no author authority over the review result. A reviewer from another family can provide an additional opinion; that alone neither proves correctness nor changes the required gate.

The current companion implementation configures only Claude for automatic author work. The isolated Codex author still uses a Platform API key; the requested Business-authenticated author path remains unverified. These are implementation and activation limits, not a permanent Claude-only product decision. [ADR-0005](0005-operating-model-without-api-billing.md) records the authentication and billing distinctions.

## Decision drivers

- Preserve both requested author clients and the fixed Astra/high gate.
- Keep author and reviewer sessions and privileges separate.
- Make reviewer changes measurable before they affect acceptance.
- State unsupported runtime paths explicitly.

## Considered options

1. Keep the fixed gate, support both author clients as their isolated paths are verified, and allow optional advisory reviews from another family.
2. Require different model families and restrict authors to Claude.
3. Replace the gate with a panel of reviewers.

## Proposed decision

Option 1, subject to human review and merge:

- **Gate reviewer:** retain `gpt-6-astra`, effort `high`, with no silent fallback. Local advisory output does not substitute for the authenticated senior-review gate.
- **Author choice:** retain Codex and Claude Code in the intended interface. A verified author path must preserve isolation, credential placement and budget controls. Do not enable the Business Codex author until those controls are demonstrated; do not substitute a billable API path without explicit authorization.
- **Optional additional review:** a reviewer from another model family may supply advisory findings. It neither replaces Astra/high nor becomes a mandatory pairing rule through this ADR.
- **Reviewer changes:** proposed changes to the model, effort or prompt should include evaluation on a maintained set of representative PRs, with outcomes by severity. A model sunset requires an explicitly reviewed replacement; it does not authorize fallback.
- **Configuration:** consolidate duplicate reviewer identity declarations through a separately reviewed control change. This document does not alter the current schema or gate.

### Consequences and confirmation

The fixed gate remains a single reviewer, so its quality must be measured. Additional advisory review consumes time and quota and requires evaluation of its usefulness. Neither a different model family nor a passing local review proves merge readiness.

Before activation, verify the exact gate identity, a fresh reviewer session, the absence of author transcripts and writable tools, and each enabled author's isolated runtime. Record Codex Business author limitations until resolved. Any reviewer-policy change must be reviewed against the existing trusted policy, not accepted by its own new rule.

Option 2 is not adopted: the user did not authorize a mandatory family restriction. Option 3 is deferred; a panel would require a separate aggregation and evaluation decision.
