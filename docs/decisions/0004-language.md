# ADR-0004: English as the repository language, north star excepted

- Status: Accepted (2026-10-28)
- Date: 2026-10-28
- Deciders: Gabriel (`Zerosteps1`)
- Related: finding F20 in the [factory review](../review/2026-10-28-factory-review.md)

## Context and problem statement

The repository mixes German and English: documentation and `factory/policy.md` are German, code and skills English, bot comments and `doctor.py` output German, and the review prompt combines the German policy with an English instruction block. This is inconsistent for LLM reviewers and authors and for future contributors.

## Decision drivers

- One language for everything a model reads as instruction or specification.
- No large translation effort without a content reason.
- Product documents written for humans stay readable for their audience.

## Considered options

1. English for code, prompts and specifications; the north star stays German.
2. German everywhere.
3. Keep the current mix.

## Decision outcome

Chosen option 1.

- **English** for code, skills, prompts, bot comments, specifications (work orders in `docs/work/`) and architecture (ADRs, factory documentation).
- **German** only for large documents written purely for humans, such as `AICEPEAK_NORDSTERN.md`.
- **Transition:** `README.md`, `CONTRIBUTING.md`, `factory/*.md` and `docs/work/*.md` switch to English at their next content change. There is no dedicated translation PR. `factory/policy.md` is the reviewer specification and becomes English. German bot comments in `tools/factory/engine.py` and German `doctor.py` output switch with the next change to that code.
- Quotations from German sources (for example north star IDs and headings) may stay German inside English text.

### Consequences

- Good: one instruction language for models; consistent review prompts; contributors without German can work on the factory.
- Bad / accepted cost: for a while the repository stays mixed, until each file's next content change.

### Confirmation

- New files under `docs/decisions/`, `docs/work/`, `docs/review/` and `factory/` are in English.
- Reviews flag new German text outside the north star as a P2 note.

## Pros and cons of the options

### Option 2: German everywhere

- Good: matches the north star and the maintainers' working language.
- Bad: vendor documentation, CLIs, skills and model instructions are English; mixing remains inside every prompt.

### Option 3: keep the mix

- Good: no effort.
- Bad: the inconsistency the finding describes stays.
