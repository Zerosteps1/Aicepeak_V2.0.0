# ADR-0003: Standard library only for security-critical factory code

- Status: Proposed
- Date: 2026-10-28
- Deciders: verified maintainers
- Related: finding F18 in the [factory review](../review/2026-10-28-factory-review.md); `docs/work/FACTORY-001.md` ("Factory tools: Python standard library")

## Context and problem statement

About 2,600 lines of security-critical factory code under `tools/factory/` use only the Python standard library:

- a JSON Schema validator for a deliberately small subset (`contracts.validate`);
- GitHub App JWT signing through an `openssl` subprocess (`github_api.installation`);
- the HTTP credential broker (`proxy.py`);
- a GitHub REST/GraphQL client without retry or rate-limit handling (`github_api.py`).

This was a deliberate supply-chain decision: the trusted pipeline installs no third-party Python packages. It also means a high maintenance load for one or two people, and the custom parts have no external test oracle.

## Decision drivers

- Smallest possible supply-chain surface in the privileged jobs and the broker.
- Maintainability by a team of one or two.
- Correctness of the security-relevant parts.

## Considered options

1. Keep stdlib-only for security-critical factory code and add minimum mitigations.
2. Replace the custom parts with pinned, hash-locked third-party libraries (JSON Schema, JWT, HTTP client).
3. Replace parts with managed primitives (for example vendor-hosted review or gateways).

## Decision outcome

Proposed option 1, with these minimum mitigations from F18:

- GitHub client: honour `Retry-After` and rate-limit headers, and back off on secondary rate limits, with tests.
- JSON Schema validator: test it against fixtures produced with a reference implementation, so the subset behaves like the standard for every keyword it accepts. The reference implementation is used only to create fixtures, not at runtime.

Scope: the rule covers trusted factory code in `tools/factory/` and `.github/scripts/`. Separately pinned tools (Codex CLI, Claude Code, gitleaks, actionlint) are unaffected. The rule says nothing about the product stack ([FACTORY-002](../work/FACTORY-002.md)).

### Consequences

- Good: no third-party Python code in privileged jobs; the trusted base stays auditable as one repository.
- Bad / accepted cost: own maintenance of protocol details (schema subset, JWT, HTTP edge cases); fixes for rate limits and similar edge cases are our own work.

### Confirmation

- `verify.py` and the trusted test suite run with `python3 -I` and need no installed packages.
- Tests exist for `Retry-After`/secondary-rate-limit handling and for the schema fixtures.

## Pros and cons of the options

### Option 2: pinned third-party libraries

- Good: mature implementations, less own code.
- Bad: every dependency enters the privileged path and needs lockfile, hash pinning, update review and Dependabot handling.

### Option 3: managed primitives

- Good: least own code.
- Bad: vendor reviewers are advisory and produce no enforceable check (review report section 4.2); the broker and ledger have no vendor equivalent. Revisit when a measurable bottleneck appears (F27).

## More information

Review report sections 3.4 (F18) and 4.2.
