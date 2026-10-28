# Codex start through the factory broker

Status: correction proposal for human review. Trigger: a reported startup failure with Codex 0.164.0 after a fresh checkout.

Goal: the documented isolated Codex starts load the reviewed factory provider through a supported configuration layer.

Scope: interactive and unattended launcher, native smoke discovery, generated project adapter and start instructions. No product change, no global user configuration, no change to isolation, the MCP requirement, models, budgets or approval rules.

Acceptance:
- The effective Codex configuration uses the factory broker and only the reference to the disposable job token.
- The project adapter contains no provider keys that Codex ignores.
- The launcher creates only the required project trust entry in the new container Codex directory, without overwriting existing files; personal configuration stays excluded.
- Both author paths and native discovery use the same reviewed provider configuration.
- A native configuration check without a model call complements the regression tests; container and API tests that were not executed stay open.
- The instructions explain why a direct host start does not work and which launcher is required.

Sources: `AGENTS.md`, `factory/policy.md`, `factory/clients.md`, `tools/factory/clients.py` and the official Codex configuration reference linked in the clients document. No sources from earlier projects.

Adopting it is a protected factory change and follows the manual review path. This proposal does not declare itself the approved review baseline.
