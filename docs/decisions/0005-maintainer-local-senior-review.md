# ADR-0005: Maintainer-local senior review and federated Claude author

- Status: Accepted, as implemented on `main` by PR #9 and PR #11 (merged by Gabriel on 2026-10-28)
- Date: 2026-10-29
- Deciders: Gabriel (`Zerosteps1`); Felix (`truFelix-Zentru`, `ftrutschnig`) as co-maintainer
- Related: [policy](../../factory/policy.md), [configuration](../../factory/config.json), [clients](../../factory/clients.md), [evidence](../../factory/evidence.md)

This record exists because `engine.py`, `local_review.py`, `doctor.py`, `settings.py` and `factory.yml` cite "ADR-0005". It records the operating model already on `main`; it changes nothing.

## Context

The maintainers want an independent review by `gpt-6-astra` at effort `high` on every PR without a pay-per-use OpenAI API key. They also want bounded automatic corrections and a human merge decision. A ChatGPT Business access token is personal and must not reach GitHub-hosted runners or untrusted PR code.

## Decision

1. **Senior review runs on a maintainer's trusted machine.** The trusted pipeline on `main` runs deterministic tests and leaves `factory/senior-review` in progress with an authenticated receipt. A maintainer runs `python3 tools/factory/session.py watch --pr <n>` (or `local_review.py --pr <n>`) from a clean control checkout of the policy revision. The script claims the review through the serialized workflow, runs a fresh tool-less `codex exec` session with the maintainer's own `CODEX_ACCESS_TOKEN`, and submits the result as neutral evidence. Only the serialized workflow completes the gate. No `OPENAI_API_KEY` is used.
2. **Claude is the automatic author, not a reviewer.** When the gate returns `changes_requested` for a non-control change, the correction job runs Claude Code (`claude-sonnet-5-5`) in GitHub Actions behind the credential broker. It authenticates through Anthropic Workload Identity Federation and pushes through the writer App. This is Claude API usage in the configured Console workspace and is bounded by `limits` in `factory/config.json`. The native Claude reviewer role (`.claude/agents/factory-local-reviewer.md`) is advisory only.
3. **Codex as automatic author stays disabled** (`runners: ["claude"]`) until a Business-authenticated, broker-bounded path is proven.

## Consequences

- No review happens while no maintainer runs the watcher. Pending reviews are visible as the in-progress `factory/senior-review` check and, from PR #16 on, the `awaiting-senior-review` label.
- Each reviewer machine needs its own Business access token (keychain item `aicepeak-factory-codex-access-token`) and the publisher App key (`aicepeak-factory-publisher-key`). Felix needs both on his own machine.
- Review usage counts against the maintainer's Business workspace allowance. Author corrections are API usage, possibly covered by Team plan API credits; billing state must be checked in the Anthropic Console.
- Every merge to `main` changes the policy revision, so every open PR must be updated and reviewed again before it can merge.
