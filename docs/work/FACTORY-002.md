# FACTORY-002 – Decide the product stack and define product checks

Status: **draft, not approved.** The stack is an open question for the maintainers; this file only frames the decision. While `status` is `draft`, the engine blocks every PR that references this task. A maintainer sets it to `approved`, with final `allowed_paths`, in a human-reviewed PR once the stack is decided.

```factory-task
{"status":"draft","kind":"factory","allowed_paths":["docs/decisions/","factory/checks.json","factory/Dockerfile","factory/config.json","tools/factory/verify.py","tools/factory/tests/"]}
```

requirements: []

*The paths above are provisional. The project manifest, lockfile and product source directories depend on the stack and are added when the task is approved.*

## Goal

The factory can check product PRs. Today it can only check itself: `tools/factory/verify.py` knows no product stack, `product_checks_ready` is `false` in `factory/config.json`, and the north star deliberately leaves stack, architecture and CI open (chapter 11.2). Finding F13 in the [factory review](../review/2026-10-28-factory-review.md).

## Non-goals

- No product feature, no data model, no product code beyond what a check needs to prove itself.
- No change to product scope; the north star and its open decision points (chapter 12) stay as they are.
- No choice of algorithms, model vendors or forecasting methods (north star 11.2).
- Not setting `product_checks_ready` to `true`; that happens only after a real smoke product PR has passed the new checks.

## Decision to take (open)

The maintainers decide, recorded as an ADR in `docs/decisions/`:

1. Language and runtime of the product.
2. Package manager and lockfile (installs must be reproducible and locked).
3. Test framework, linter, formatter and type checker.
4. How the Excel export and its recalculation behaviour (north star AIC-031 to AIC-033) are produced and tested, for example with golden files.
5. Which product checks run in the network-less factory container, and what the image needs for them.

Example from the review roadmap, **not a decision**: a Python stack with `pyproject.toml` and a uv lockfile, ruff, a type checker, pytest and Excel golden files.

Decision drivers from the repository: results must be deterministic and fully traceable (north star chapter 2, principles 3 and 8); confidential company data stays separated (AIC-044); product checks run without network and without secrets (factory policy); ADR-0003 (stdlib-only) applies to factory code only, not to the product.

## Implementation outline (after approval)

- Product checks as a declarative list in `factory/checks.json` (command, timeout, expected artifacts), executed by `verify.py` inside the factory container.
- The factory image gains the product toolchain at pinned versions.
- Trusted regression tests for the new `verify.py` behaviour.

## Acceptance criteria

1. AC-1: The stack decision shall be recorded as an ADR with status `Accepted` and the other code owner's approval (ADR-0001).
2. AC-2: When `verify.py` runs in the factory container, it shall execute every check declared in `factory/checks.json` without network access.
3. AC-3: If a declared check exits non-zero, exceeds its timeout or does not produce its expected artifact, then `verify.py` shall exit non-zero and name the failed check.
4. AC-4: If `factory/checks.json` is missing, invalid or empty, then `verify.py` shall not report product checks as passed.
5. AC-5: While no smoke product PR has passed the product checks in the real pipeline, `product_checks_ready` shall stay `false`.

## Verification

```sh
python3 -I -m unittest discover -s tools/factory/tests -v
python3 tools/factory/verify.py --root .
```

Expected output: unittest ends with `OK` including new tests for AC-2 to AC-4; `verify.py` prints a `PASS:` line for the product checks and exits 0. A negative probe with a deliberately failing declared check makes `verify.py` exit non-zero and name that check. Evidence for AC-5: the smoke product PR's run and check IDs in `factory/evidence.md`.

## Open questions

- All five points under "Decision to take" (maintainers).
- Does the first product task (for example a data model for positions and periods, review roadmap phase 2) wait for north star approval (F14), or is it scoped as a smoke task?
