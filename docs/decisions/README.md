# Architecture decision records

This directory holds the permanent decisions of the factory and, later, of the product, as required by `factory/policy.md` ("permanent decisions go into the repository"). Records follow a shortened [MADR](https://adr.github.io/madr/) layout and are written in English ([ADR-0004](0004-language.md)).

`docs/decisions/` is a protected control path (`factory/config.json`): records change only through a human-reviewed PR, and automatic corrections never edit them.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-maintainer-model.md) | Two code owners and how a PR gets a legitimate approval | Accepted (2026-10-28) |
| [0002](0002-single-reviewer-and-model-pairing.md) | Single gate reviewer, model-family pairing and model changes | Proposed |
| [0003](0003-stdlib-only.md) | Standard library only for security-critical factory code | Proposed |
| [0004](0004-language.md) | English as the repository language, north star excepted | Accepted (2026-10-28) |
| [0005](0005-operating-model-without-api-billing.md) | Operating model without API billing (S1) | Accepted (2026-10-28) |

## Process

1. Copy the template below into `NNNN-short-kebab-title.md`, using the next free number. Numbers are never reused.
2. Open the record with status `Proposed` in its own PR or in the PR that needs the decision.
3. A maintainer accepts it by merging it with status `Accepted (YYYY-MM-DD)`. A record written by one code owner needs the other code owner's approval ([ADR-0001](0001-maintainer-model.md)).
4. Accepted records are not rewritten. A changed decision gets a new record; the old one is set to `Superseded by ADR-NNNN`. Typos and broken links may be fixed in place.
5. Other possible states: `Rejected` (kept for the reasoning) and `Deprecated` (no longer relevant, no successor).

## Template

```markdown
# ADR-NNNN: Title as a short decision statement

- Status: Proposed | Accepted (YYYY-MM-DD) | Rejected | Deprecated | Superseded by ADR-NNNN
- Date: YYYY-MM-DD
- Deciders: verified maintainers by login
- Related: findings, tasks, other ADRs

## Context and problem statement

What forces the decision; facts with evidence (file, line, documentation link).

## Decision drivers

- Driver 1
- Driver 2

## Considered options

1. Option A
2. Option B

## Decision outcome

Chosen option: "Option A", because ...

### Consequences

- Good: ...
- Bad / accepted cost: ...

### Confirmation

How compliance is checked: test, deterministic check, review rule or manual step.

## Pros and cons of the options

### Option B

- Good: ...
- Bad: ...

## More information

Links, follow-up tasks, conditions for revisiting the decision.
```
