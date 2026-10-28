# TASK-ID – Short outcome-oriented title

Status: template. Copy this file to `docs/work/<TASK-ID>.md` (letters, digits, `-` and `_` only), replace every placeholder and delete the guidance in italics. A task authorizes work only after a human-reviewed PR has merged it to protected `main`: the factory reads the task from the protected base commit, so a task added in the same PR as its implementation is not found, and an `approved` text in your own PR does not count.

```factory-task
{"status":"approved","kind":"product","allowed_paths":["REPLACE-WITH-EXACT-PATHS/"]}
```

*Block rules (`task_spec` in `tools/factory/engine.py`): exactly one block per file; exactly the three keys `status`, `kind`, `allowed_paths`; no comments inside the JSON.*

- *`status`: the engine accepts only `approved`. Use `draft` for a task that is merged for discussion but must not authorize work yet; every PR that references it is then blocked.*
- *`kind`: `factory` (factory work), `product` (blocked until the north star is configured and approved and `product_checks_ready` is true), or `smoke` (controlled fixtures only).*
- *`allowed_paths`: the smallest list of repository-relative files, or directory prefixes ending in `/`, the PR may touch. Every changed file and every rename source must match one entry. Paths in `protected_paths` of `factory/config.json` are control paths: they can be in scope for a manually managed PR, but automatic correction never edits them.*

*This template authorizes nothing real: its only path is a placeholder and `product` tasks are blocked until product prerequisites exist.*

requirements: [AIC-NNN, AIC-NNN]

*North star requirement IDs this task implements. Mandatory for `kind: product`; write `requirements: []` for factory and smoke tasks. Name only requirements that are actually affected; the review compares the change with these sections and with the [product constitution](../CONSTITUTION.md).*

## Goal

*One or two sentences: the observable outcome for the user or maintainer once this task is done.*

## Non-goals

- *What this task deliberately does not change (neighbouring features, refactors, other requirements, product scope not in the north star).*

## Context and constraints

*Relevant existing files, decisions (`docs/decisions/`), north star sections and known risks. Mark unresolved decisions as open; do not fill them with defaults.*

## Acceptance criteria

*EARS style: one observable, testable statement per line. Patterns:*

- *Ubiquitous: "The `<component>` shall `<response>`."*
- *Event-driven: "When `<trigger>`, the `<component>` shall `<response>`."*
- *State-driven: "While `<state>`, the `<component>` shall `<response>`."*
- *Unwanted behaviour: "If `<condition>`, then the `<component>` shall `<response>`."*
- *Optional feature: "Where `<feature is enabled>`, the `<component>` shall `<response>`."*

1. AC-1: When ..., the ... shall ....
2. AC-2: If ..., then the ... shall ....

*Each criterion maps to at least one check below. Include the negative cases that matter (wrong input, missing data, stale state).*

## Verification

*Exact commands from the repository root and the output that proves success. A claim without command and output is not evidence.*

```sh
python3 -I -m unittest discover -s tools/factory/tests -v
python3 tools/factory/clients.py check --root .
python3 tools/factory/verify.py --root .
```

Expected output:

- unittest ends with `OK` (state the expected test count once known);
- `verify.py` prints its `PASS:` lines and exits with code 0;
- *task-specific commands and their expected output, one per acceptance criterion.*

*For `kind: product`, add the product checks defined by [FACTORY-002](FACTORY-002.md) once they exist.*

## Handoff

The PR that implements this task contains exactly one handoff block. `runner` is one of the `runners` in `factory/config.json`; `owner` is a configured verified maintainer:

```factory-handoff
{"runner":"claude","task":"docs/work/TASK-ID.md","owner":"verified-maintainer-login"}
```

## Open questions

- *Questions that block or shape the implementation, with the person who decides.*
