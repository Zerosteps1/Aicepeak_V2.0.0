# Isolated native clients

The shared sources are the four `.agents/skills/*/SKILL.md` files and `.agents/roles.json`. Codex discovers the shared skills directly. Claude gets generated native copies under `.claude/skills/`; `CLAUDE.md` imports `AGENTS.md`. Generated Codex roles use the **0.164.0** schema's `agents.<name>.config_file`. Claude's reviewer is explicitly local; it never impersonates the independent OpenAI review gate.

```sh
python3 tools/factory/clients.py sync --root .
python3 tools/factory/clients.py check --root .
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/factory/tests
```

`check` rejects adapter drift, extra skill/config files and symlinks. Changing a canonical skill requires regeneration and review. Use the normal factory change process for protected policy changes.

## Build and run

Build only from the trusted checkout. Both CLI versions are pinned; runtime resolves the local image to its immutable SHA256 ID before starting containers.

```sh
docker build -f factory/Dockerfile \
  -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
python3 tools/factory/clients.py launch --root . --runner codex
```

The unattended interface is:

```sh
python3 tools/factory/clients.py run \
  --root /path/to/candidate --policy-root /path/to/trusted-base \
  --runner codex --prompt-file /path/to/task.txt \
  --output-patch /path/to/changes.patch
```

`run` returns JSON with `patch`, its SHA256, `report`, `report_truncated` and the author cost reservation ceiling. The report is `changes.patch.report.txt`, valid UTF-8 below 8 KiB. It contains only final user-facing text, including disagreements or reasons for an empty patch. Raw transcripts and reasoning events are discarded. The orchestrator independently validates the patch and report before publishing either. `launch` is interactive and returns a patch artifact without changing the original checkout.

Provide `OPENAI_API_KEY` **or** `ANTHROPIC_API_KEY`, plus `CONTEXT7_API_KEY`, only to the trusted launcher environment through the execution platform's secret facility. Do not put values in repository files or CLI arguments. The launcher passes only the selected provider secret to the separate broker, and only a disposable job credential to workers. It does not read personal configs or credential stores. `FACTORY_DOCKER_HOST` can explicitly select a Docker endpoint; the launcher uses an empty Docker config directory.

Claude fails closed until an exact `author_models.claude` and `author_pricing_usd_per_million.claude` are configured. Prices must be positive input/output USD per million tokens. Codex may reuse reviewer pricing only when its author model equals the review model. Every author run is bounded by `limits.max_run_cost_usd` (fallback `max_cost_usd`); the orchestrator must reserve this ceiling against the whole task's budget.

## Boundary

1. Copy only bounded regular candidate files, excluding Git metadata, nested agent configuration, obvious credential files and dependency caches. Overlay trusted instructions, factory code and native configuration.
2. Initialize a fresh Git baseline with host/global hooks, filters and configuration disabled. Linked-worktree `.git` pointers are never followed.
3. Seed a 512 MiB Docker tmpfs volume through a trusted network-disabled helper. The model never gets a writable host bind mount.
4. Start a separate credential broker with fixed OpenAI, Anthropic and Context7 destinations. The worker has only an internal Docker network, restricted DNS, a read-only root filesystem, read-only trusted overlays and Git metadata, no capabilities, no Docker socket, and no host home or credentials. CPU, memory, PID, time and output limits apply.
5. Start a fresh native session. Codex disables user config, persisted sessions, hooks, plugins and memory. Claude selects project settings, explicit MCP, no persistence and no auto-memory/hooks. Native shell permissions operate inside the outer Docker boundary.
6. A trusted network-disabled helper checks output files before extracting the patch. The original candidate is not modified; the launcher never commits a result, pushes, posts a comment or merges.

The broker accepts only its selected model and fixed routes; denies hosted tools, media, remote prompt/state/container references, model fallbacks and premium inference modes; and reserves a conservative text-input/output budget before every request. Reservations are not refunded, so a job can stop earlier than its actual bill would imply. Token and cost controls depend on the configured prices; review them when changing models. Unknown provider request fields fail closed and require a reviewed compatibility update. Context7 permits only MCP initialization/ping/discovery and `resolve-library-id`/`query-docs`, with a request cap. The direct official endpoint is `https://mcp.context7.com/mcp`; native configs reach it through the broker using the job token.

## Verification status and limits

The implementation has local regression tests for configuration drift, inherited policy removal, linked Git pointers, symlink escape, patch extraction, secret environment separation, fresh-session flags, report filtering, route/model restrictions, remote-source rejection and budget exhaustion.

**Live validation is blocked in this setup:** the Docker socket returns permission denied and no provider/Context7 credentials are available. No image build, container execution, native model call or native MCP connection has passed here. `smoke` reports this as `blocked`, never as success. Connected Context7 tools were successfully exercised during research; that does not prove the isolated clients' connection.

`client-tools.lock.json` is a complete npm v3 lock for both CLIs and all 14 optional native packages, including vendor-published tarball SHA512 integrity. The Dockerfile uses `npm ci`; no package checksums are invented. The base image currently uses a version tag and apt resolves packages at build time; a trusted release build must record the base digest, package inventory and resulting image ID for archival reproducibility. Workers run the selected local image ID rather than pulling a mutable tag. Keep the strict broker payload allowlist and required MCP initialization under a real authenticated smoke test before activation.

## Official references

- [Codex 0.164.0 configuration schema](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/core/config.schema.json): pinned role/config fields.
- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive): ephemeral runs, user-config exclusion, required MCP and final-message events.
- [Claude native skills](https://code.claude.com/docs/en/skills), [instruction imports](https://code.claude.com/docs/en/memory), [native agents](https://code.claude.com/docs/en/sub-agents): supported adapters and source discovery.
- [Claude CLI flags](https://code.claude.com/docs/en/cli-reference), [headless output](https://code.claude.com/docs/en/headless), [gateway connection](https://code.claude.com/docs/en/llm-gateway-connect), [MCP configuration](https://code.claude.com/docs/en/mcp): verified launch/auth/HTTP interfaces.
- [Claude installation](https://code.claude.com/docs/en/setup): explicit version installation and update controls; [container guidance](https://code.claude.com/docs/en/devcontainer).
- [Context7 clients and exact tools](https://context7.com/docs/resources/all-clients), [Codex integration](https://context7.com/docs/clients/codex): bearer authentication and documentation lookup workflow.
