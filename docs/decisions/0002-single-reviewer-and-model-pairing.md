# ADR-0002: Single gate reviewer, model-family pairing and model changes

- Status: Proposed
- Date: 2026-10-28
- Deciders: verified maintainers
- Related: findings F10, F12, F34 in the [factory review](../review/2026-10-28-factory-review.md); [ADR-0005](0005-operating-model-without-api-billing.md)

## Context and problem statement

The gate reviewer is fixed to `gpt-6-astra` with effort `high` (`factory/config.json`, `factory/review.schema.json` `const`, `contracts.validate_review`, `verify.py`). The same model is also configured as the Codex author (`author_models.codex`), so in the Codex path a model reviews its own work. Research on LLM judges recommends a judge from a different model family than the author (self-preference bias) and a judge without access to the author's reasoning; the second point is already met, because the review never sees author transcripts. The model name is hard-coded in 14 places and there is no procedure for a model change or a model sunset, although "no fallback" is policy.

## Decision drivers

- One reviewer that a ruleset can require, with a strict JSON contract.
- Independence between author and reviewer.
- Changes to the reviewer must be measurable before they affect the gate.

## Considered options

1. One gate reviewer (`gpt-6-astra`, effort `high`), author from a different model family, model change only after an eval run.
2. A panel of reviewers from several families (PoLL-style jury) as the gate.
3. Keep the current configuration, where the Codex author and the reviewer can be the same model.

## Decision outcome

Proposed option 1.

- **Single gate reviewer:** `gpt-6-astra`, effort `high`, no fallback model. Under ADR-0005 it runs through `codex exec --output-schema` on the maintainer's trusted machine.
- **Pairing rule:** reviewer and author must belong to different model families. Under ADR-0005 the author is Claude Code, so `runners` becomes `["claude"]` (PR B2). A Codex author can be re-enabled only through a new ADR that changes the reviewer family or explains why the pairing rule does not apply. Config validation should enforce the rule (proposed for PR C).
- **Model change:** changing the review model, effort or review prompt requires an eval run on the golden PR set (F10) with precision and recall per priority recorded in the PR, plus an update of this ADR. A vendor sunset is handled the same way; there is no silent fallback.
- **Single source:** the model name should live only in `factory/config.json`, with the schema `const` generated from it (F12, PR C).

### Consequences

- Good: an independent reviewer; reviewer changes become measurable; a model sunset has a defined procedure.
- Bad / accepted cost: one reviewer is a single point of failure for review quality until the golden set exists; the eval set must be built and maintained (PR G).

### Confirmation

- `factory/config.json`: `review_model` family differs from every model in `author_models` for the runners listed in `runners`.
- A PR that changes the review model, effort or prompt links an eval run.

## Pros and cons of the options

### Option 2: panel of reviewers

- Good: panels beat single judges in the literature.
- Bad: several times the cost and quota; needs aggregation logic and a calibrated set first. Can be revisited after the shadow phase.

### Option 3: same model for author and reviewer

- Good: no configuration change.
- Bad: self-preference bias in exactly the step that gates merges.

## More information

Cohere PoLL: `https://arxiv.org/abs/2404.18796`. Shadow phase and golden set: review report sections 3.2 (F10) and 6.
