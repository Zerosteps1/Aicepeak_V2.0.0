# Verification status and pending activation

Status: 2026-10-28. **Factory implemented and on `main`; not activated and not ready for operation.** This record separates executed checks from pending live scenarios. Agents made no merge and no administrative remote change; humans merged PR #1 (factory bootstrap) and PR #2 (north star) on 2026-10-28.

## 2026-10-28 (PR B2, local, not live)

Executed locally for PR B2 (usage-based broker accounting, federated Claude author, egress self-test, Claude brakes):

- `python3 -I -m unittest discover -s tools/factory/tests`: **107 tests OK**, including a 30-turn session with 60 KB context per runner within budget, SSE and JSON usage parsing, the Workload Identity Federation exchange against a fake transport (fresh GitHub OIDC token per exchange, caching, URL and ID validation), OIDC request credentials reaching only the broker, and the fail-closed worker egress self-test.
- `python3 tools/factory/verify.py --root .`: all four PASS lines (actionlint 1.7.12, gitleaks 8.30.1).
- Claude Code 2.1.312 (one patch above the pinned 2.1.311) captured against a local capture server: all body fields allowlisted; `max_tokens: 128000` and six betas that the broker previously dropped (see [Clients](clients.md)). Redacted fixture: `tools/factory/tests/fixtures/claude-code-2.1.312-request.json`.

Not executed: the real token exchange (needs a GitHub Actions job on `main` in `factory-control` and the Console workload), Docker/container runs, real model calls. Automatic correction stays disabled.

## 2026-10-28 (PR B1, local, not live)

Executed locally on the maintainer's Mac for PR B1 (maintainer-local senior reviewer, pipeline without `OPENAI_API_KEY`, broker allowlist):

- `python3 -I -m unittest discover -s tools/factory/tests`: **95 tests OK**.
- `python3 tools/factory/clients.py check --root .`: passed.
- `python3 tools/factory/verify.py --root .`: all four PASS lines (structure, links and adapter drift; workflow syntax, cache isolation and Action SHAs; Gitleaks; trusted regression suite and candidate tests), with actionlint 1.7.12 darwin_arm64 (SHA-256 verified against the official release checksums) and Gitleaks 8.30.1 in the PATH.
- The reviewer command line was accepted by codex-cli 0.164.0 with `--strict-config`.
- The model-visible tool surface was captured against a local capture server and with `codex debug prompt-input`. Default configuration: `exec_command`, `apply_patch`, `view_image` and `spawn_agent`. Reviewer configuration: only `exec`, `wait` and `request_user_input`, with the MCP resource helpers nested in `exec` and no MCP server configured. Details in [Clients](clients.md#senior-reviewer-maintainer-local).
- `local_review.py --smoke` with a deliberately invalid token completed the version, catalog and tool-surface checks and failed at the model call with 401. Codex sent no credential for the malformed token, so acceptance of a real ChatGPT Business access token is **unverified**.

Not executed: any live GitHub run, Docker/container runs, real model calls, `settings.py apply`.

## Target and prerequisites (setup, 2026-10-27)

Public GitHub API actually read: `Zerosteps1/Aicepeak_V2.0.0`, repository ID `1436114884`, public, configured default `main`; branch list empty, contents endpoint 404. A repeated branch query at the end was still empty. Owner `Zerosteps1`, user ID `115100163`, confirmed by the user as Gabriel. Felix not yet named. The SSH origin is `git@github.com:Zerosteps1/Aicepeak_V2.0.0.git`.

The target repository contained no north star yet; `northstar_path:null` is the explicit blocker, not a substitute document. Since PR #2, `AICEPEAK_NORDSTERN.md` is in the repository, but `northstar_path` stays `null` until it is approved. No old projects, earlier work or personal knowledge collections were taken over for the factory. A document outside the target repository was not imported as a repository source.

`gh` and the GitHub connector provided no valid login; SSH/Git network access was not possible in this environment. Public HTTPS queries through the permitted curl call worked. Plan, Actions, environment and administration rights were therefore not verified with authentication. The repository is public; private use needs a new plan and feature check. **No rulesets have been activated by this setup.**

Checked locally: Git 2.50.1, gh 2.87.0, Codex 0.164.0, Claude Code 2.1.311, Python 3.15.2, Node 25.8.1, npm 11.11.0, Docker 29.1.3, Gitleaks 8.30.1. Actionlint 1.7.12 was downloaded from the official release and verified against its SHA256. Docker daemon not reachable. CLI help and native configuration sources are documented in [Clients](clients.md). The factory needs only the Python standard library plus pinned check and client tools; this does not determine a product stack.

## Executed local checks (setup, 2026-10-27)

- Python syntax, JSON/TOML, native adapter drift, internal documentation links, complete Action SHAs and controlled smoke calculation.
- Actionlint over all workflow files. The only compatibility treatment: the line `cache-mode: none`, documented by GitHub but not yet understood by Actionlint 1.7.12, is first checked exactly and removed only for its parser. All other fields are checked completely. No general filtering of linter errors.
- Gitleaks with a trusted rule file, an empty ignore file and inline exceptions disabled. One narrowly scoped AND exception covers only the public internal broker URL literal in `clients.py`, not a credential value.
- Unit and regression tests check the review contract, SHA/App/run binding, three rounds, monotonic budget despite force push, duplicate processing, draft to ready, missing model key, new human feedback, path and rename limits, a real Git rename, atomic ref update, settings diff and idempotence, and broker/worker boundaries. GitHub and provider transports are simulated; this is no live evidence.
- Negative probe: a deliberately broken candidate validation stays red in the isolated trusted suite despite `unittest.py`/`sitecustomize.py` in the candidate. Existing base tests explicitly load candidate code; missing tests do not count as success.
- Positive counter-example: a complete, correct review contract without artificial findings is accepted. A real paid Astra run of this counter-example is still pending.
- The doctor was run against the actual local state and reports open prerequisites. Additional diagnostic probes check, among other things, that even a seemingly complete local state produces no live approval and that secret values are not printed.
- The npm lockfile was built against actual public package metadata including integrity values and checked offline with a fresh temporary home without personal npm configuration.

Reproducible with `python3 -I -m unittest discover -s tools/factory/tests -v` and `python3 tools/factory/verify.py --root .`. If Actionlint is not in the PATH: `--actionlint /absolute/path/actionlint`. Final local run at setup: **67 tests passed**, full verifier exit 0, `git diff --check` exit 0. Doctor exit 2 (open prerequisites), model smoke exit 1 (missing API key; `engine.py model-smoke` was removed in PR B1), container smoke exit 2 (Docker access denied). This file claims no live tests that were not executed.

## Documentation and model access (setup, 2026-10-27)

The OpenAI Docs MCP `https://developers.openai.com/mcp` was queried directly with `initialize`, `tools/list`, `search_openai_docs` and `fetch_openai_doc`; server `openai-docs-mcp` 1.0.0. Context7 `resolve-library-id` and `query-docs` were used through the existing connector. Only generic technical questions, no private diffs or requirements. **This does not prove** reachability from the isolated clients; their MCP smoke is pending.

Centrally configured: `gpt-6-astra`, `reasoning.effort=high`, no fallback. At setup the actual command `python3 tools/factory/engine.py model-smoke` blocked before the network call because `OPENAI_API_KEY` was missing. Neither a successful model response nor API permission is claimed. PR B1 removed this API path. Before activation, `python3 tools/factory/local_review.py --smoke` must report model, effort and success on the reviewer Mac with the real access token.

## Independent review and resolved findings (setup)

An independent subagent was actually run with GPT-6 Astra / high. This is local review evidence and no proof of the central reviewer access, which is not yet set up.

First review: budget loss on force push, missing check of the rename source, rename treated as a copy by the writer, and a blocked draft to ready transition. Fixed with a PR-wide authenticated ledger, checks of both paths, complete delete/add capture and draft binding; targeted regressions exist.

Second review: test discovery through candidate imports, base tests without a candidate target, uncounted GitHub job reruns, cancellation with unchanged context, missing atomic expected-head check and a misleading dispatcher retry. Fixed with an isolated test start, an explicit candidate target, run-attempt binding and a fresh paid retry, serialized runs with targeted cancellation of stale runs, GraphQL `updateRefs.beforeOid` and exactly one human retry entry point. Author reports and answers to human questions are kept as reviewable PR feedback. The final independent re-review confirmed all fixes without a remaining evidenced blocker; it ran 65 tests itself successfully. Afterwards two local diagnostic regressions raised the suite to 67.

## Live acceptance after activation

| Scenario | Present / checked locally | Live evidence still required |
|---|---|---|
| Fresh checkout, same rules/skills | Adapter generation and drift check | Native discovery and actual skill execution in both clients |
| Isolated context | Worker/proxy boundaries and symlink negative tests | Container smoke: foreign harmless host content not readable; no foreign home mounts |
| Valid PR | Dispatcher and contract tests | Both App checks appear; `local_review.py` completes the pending senior review with Astra-high |
| Maintainer-local reviewer | Tool-surface preflight, event-stream check, receipt and publication tests; `--smoke` up to the model call | `--smoke` and a real review with a valid Business access token; usage shows in the Codex workspace, not on an API bill |
| Defect and fix | [Smoke work order](../docs/work/FACTORY-SMOKE.md), real Git patch probe | Real author fix, App push, new check run, clean counter-example |
| Human feedback | Identity/PR association, re-reading, changed context | Comment, inline comment and review, each with an understandable response |
| Old head/base/run | Negative tests and fresh binding check | A stale real check cannot merge; an old run is cancelled |
| Missing credentials/schema/API | Local fail-closed tests | A deliberately invalid token or schema keeps the review blocked |
| Control changed in PR | Base policy/orchestration and read-only author adapters | A real PR rule change does not influence its own check |
| Secret/identity boundary | Separate jobs, broker, App scope check | Tests without secrets; no Codex token on GitHub; an agent can neither update `main` nor merge |
| Foreign check with same name | Expected App ID in the ruleset, contract negative test | A foreign check App does not satisfy the required check |
| Budget/concurrency | Force push/rerun/duplicate/CAS regressions | Three rounds and a concurrent real update correctly lead to handoff |
| MCPs | Separate direct documentation queries | Both native clients reach only allowed servers; generic queries succeed |

Only after this evidence may the status "ready for operation" be set. Record successful GitHub run and check IDs and verified SHAs in the smoke PR, then add the lasting acceptance here through a PR.

## Tool and cost decision

Existing Codex/Claude CLIs, GitHub Actions/API, two narrowly scoped Apps, Python and small free check tools are sufficient. No additional AI review subscription, no agent platform and no product infrastructure were bought. The senior review uses the existing ChatGPT Business seat; there is no API billing for it. Docker serves only as the factory's process boundary. Context7 and OpenAI Docs provide public technical documentation; no project memory and no external indexing.

Initial limits: at most 3 automatic corrections, 5 USD reserved cost per author run and 25 USD per PR, 900 seconds execution limit, and at most 6 published senior reviews per PR. The author reservation is conservative; failed or cancelled runs do not release it automatically. Provider billing, requests already started and GitHub Actions usage must still be watched, as must the reviewer's share of the Codex seat window. Author prices are versioned in `factory/config.json`, sources in [Clients](clients.md) and [GitHub operation](github.md). A public repository does not mean free model calls. For private repositories, no blanket assumption of free code security or secret protection products.
