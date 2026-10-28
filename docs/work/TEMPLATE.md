# TASK-ID – Short outcome-oriented title

Status: template; it authorizes nothing. Copy it to `docs/work/<TASK-ID>.md` (letters, digits, `-` and `_` only), replace every placeholder, set `status` to `approved` and delete the guidance in italics. A task authorizes work only after a human-reviewed PR has merged it to protected `main`. The factory reads the task from the protected base commit, so a task added in the same PR as its implementation is not found, and an `approved` text in your own PR does not count. Typical flow: PR 1 adds the task (handoff task `docs/work/FACTORY-001.md`, which allows `docs/work/`), PR 2 implements it and references it in its handoff.

```factory-task
{"status":"draft","kind":"product","allowed_paths":["REPLACE-WITH-EXACT-PATHS/"]}
```

*Block rules (`task_spec` in `tools/factory/engine.py`): exactly one block per file; exactly the keys `status`, `kind`, `allowed_paths`; no comments inside the JSON.*

- *`status`: the engine accepts only `approved`; any other value blocks every PR that references the task.*
- *`kind`: `factory` (factory work), `product` (blocked until `northstar_approved` and `product_checks_ready` are true in `factory/config.json`), or `smoke` (controlled fixtures only).*
- *`allowed_paths`: the smallest list of repository-relative files, or directory prefixes ending in `/`, the PR may touch. Every changed file and every rename source must match one entry. Paths in `protected_paths` of `factory/config.json` are control paths: they can be in scope for a manually managed PR, but automatic correction never edits them. Do not list the task file itself.*

requirements: [AIC-NNN]

*North star requirement IDs this task implements. Mandatory for `kind: product`; write `requirements: []` for factory and smoke tasks. Name only requirements that are actually affected.*

## Goal

*One or two sentences: the observable outcome for the user or maintainer once this task is done.*

## Non-goals

- *What this task deliberately does not change (neighbouring features, refactors, other requirements, product scope not in the north star).*

## Context and constraints

*Relevant existing files, decisions (`docs/decisions/`), north star sections and known risks. Mark unresolved decisions as open; do not fill them with defaults. Non-binding drafts such as `docs/architecture/` may be cited only as background.*

## Acceptance criteria

*One observable, testable statement per line, for example in EARS style ("When <trigger>, the <component> shall <response>." / "If <condition>, then the <component> shall <response>."). Include the negative cases that matter (wrong input, missing data, stale state).*

1. AC-1: When ..., the ... shall ....
2. AC-2: If ..., then the ... shall ....

## Verification

*Exact commands from the repository root and the output that proves success. A claim without command and output is not evidence.*

```sh
python3 -I -m unittest discover -s tools/factory/tests
python3 tools/factory/verify.py --root .
```

Expected output:

- unittest ends with `OK`;
- `verify.py` prints its `PASS:` lines and exits with code 0;
- *task-specific commands and their expected output, one per acceptance criterion.*

## Handoff

The PR that implements this task contains exactly one handoff block. `runner` is one of the `runners` in `factory/config.json` (currently only `claude`); `owner` is a configured maintainer login:

```factory-handoff
{"runner":"claude","task":"docs/work/TASK-ID.md","owner":"Zerosteps1"}
```

## Open questions

- *Questions that block or shape the implementation, with the person who decides.*
