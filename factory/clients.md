# Isolated native clients

The shared sources are the four `.agents/skills/*/SKILL.md` files and `.agents/roles.json`. Codex discovers the shared skills directly. Claude gets generated native copies under `.claude/skills/`; `CLAUDE.md` imports `AGENTS.md`. Generated Codex roles use the **0.164.0** schema's `agents.<name>.config_file`. Claude's reviewer is explicitly local; it never impersonates the independent OpenAI review gate.

```sh
python3 tools/factory/clients.py sync --root .
python3 tools/factory/clients.py check --root .
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/factory/tests
```

`check` rejects adapter drift, extra skill/config files and symlinks. Changing a canonical skill requires regeneration and review. Protected factory changes require the manual proposal path below.

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

The documented Claude author configuration is `author_models.claude: "claude-sonnet-5-5"` with `author_pricing_usd_per_million.claude: {"input": 2, "output": 10}` (USD per million tokens, verified 2026-10-27). Anthropic documents Claude Code >=2.1.284 for this model; the pinned 2.1.311 meets that requirement. The broker's doubled input reservation also covers the documented 1-hour cache-write price of $4. This is a documented-compatible configuration, not an authenticated runtime result. Missing model/prices still fail closed. Codex may reuse reviewer pricing only when its author model equals the review model. Every author run is bounded by `limits.max_run_cost_usd` (fallback `max_cost_usd`); the orchestrator must reserve this ceiling against the whole task's budget.

## Boundary

1. Copy only bounded regular candidate files, excluding Git metadata, nested agent configuration, obvious credential files and dependency caches. Overlay trusted instructions, factory code and native configuration.
2. Initialize a fresh Git baseline with host/global hooks, filters and configuration disabled. Linked-worktree `.git` pointers are never followed.
3. Seed a 512 MiB Docker tmpfs volume through a trusted network-disabled helper. The model never gets a writable host bind mount.
4. Start a separate credential broker with fixed OpenAI, Anthropic and Context7 destinations. The worker has only an internal Docker network, restricted DNS, a read-only root filesystem, read-only trusted overlays and Git metadata, no capabilities, no Docker socket, and no host home or credentials. CPU, memory, PID, time and output limits apply.
5. Start a fresh native session. Codex disables user config, persisted sessions, plugins and memory; sanitized project files contain no hooks. Claude selects project settings, explicit MCP, no persistence and no auto-memory or non-managed hooks. Native shell permissions operate inside the outer Docker boundary.
6. A trusted network-disabled helper checks output files before extracting the patch. The original candidate is not modified; the launcher never commits a result, pushes, posts a comment or merges.

Organization requirements must be provisioned by the administrator in the approved execution image: Codex `/etc/codex/requirements.toml` (and any legacy `/etc/codex/managed_config.toml`), and Claude `/etc/claude-code/managed-settings.json` plus required managed hooks. The launcher neither reads host policy/personal files nor removes image policy. Fresh user directories and project-only settings are not an exemption from managed requirements. Codex no longer uses `--ignore-rules`; no rule exclusion is needed in this sanitized environment. Mandatory restrictions continue to constrain native execution. If they conflict with the reviewed container permissions or provider, execution must stop for administrator review; do not weaken policy or use a stock image to evade it. Cloud/account policy that cannot be delivered or checked in this isolated runtime is an activation blocker for organizations requiring it.

## Protected factory changes

The read-only control overlays deliberately prevent authors from editing `.agents`, native adapters, `AGENTS.md`, `CLAUDE.md`, `factory/` or `tools/factory/`, even when a task requests a factory change. There is no runtime unlock flag or automatic control remediation. The author can return a concise proposal and evidence in its final report. A maintainer then creates a separate branch in an ordinary checkout, applies the proposed control change, regenerates adapters, runs `check` and the trusted test harness against that candidate, and submits a manually managed PR for the required human/security review. Existing trusted-base gates remain in force. After acceptance, an authorized maintainer builds and approves the replacement execution image and activates the new trusted controls. Dependency update PRs follow this same path.

The broker accepts only its selected model and fixed routes; denies hosted tools, media, remote prompt/state/container references, model fallbacks and premium inference modes; and reserves a conservative text-input/output budget before every request. Reservations are not refunded, so a job can stop earlier than its actual bill would imply. Token and cost controls depend on configured prices; review them when changing models. Unknown provider request fields fail closed and require a reviewed compatibility update.

Both native clients include required documentation servers. Context7 (`https://mcp.context7.com/mcp`) permits only initialization/ping/discovery and `resolve-library-id`/`query-docs`. OpenAI Docs (`https://developers.openai.com/mcp`) permits `search_openai_docs`, `list_openai_docs`, and `fetch_openai_doc` plus the same protocol setup. Fetches accept only HTTPS public documentation URLs on developers.openai.com, platform.openai.com/docs/ or learn.chatgpt.com/docs/. Results are capped at 20 per call, and both servers share a 64-request job cap. Native configs authenticate to the broker with the disposable job token; OpenAI Docs receives no upstream credential. Before inference, generic MCP preflight initializes and discovers each required tool set. This preflight is separate from native client discovery and does not claim native tool execution succeeded.

## Verification status and limits

The implementation has local regression tests for configuration drift, inherited policy removal, linked Git pointers, symlink escape, patch extraction, secret environment separation, fresh-session flags, report filtering, route/model restrictions, remote-source rejection and budget exhaustion.

`smoke` creates a harmless host canary outside the mounted project and a project symlink to it. Inside the secret-free, network-disabled container it requires a successful project read, rejected direct/symlink canary reads, and rejected write access to trusted instructions. It asks the real Codex app server for `skills/list`, `config/read` and `configRequirements/read`, requiring the four canonical skill paths and reviewed provider/role/MCP configuration without starting a model turn. It runs Claude's native plugin validation on skill/agent directories and `doctor`; Claude authenticated startup discovery remains explicitly unverified. These checks establish only the exercised boundary, not a proof against every container escape. Tests use `FACTORY_CANDIDATE` to import candidate implementation and canonical sources under the trusted base harness, including `python -I`.

**Live validation is blocked in this setup:** the Docker socket returns permission denied and no provider/Context7 credentials are available. No image build, container execution, native model call or native MCP connection has passed here. `smoke` reports this as `blocked`, never as success. Connected Context7 tools were successfully exercised during research; that does not prove the isolated clients' connection.

`package.json` and `package-lock.json` are standard npm manifests for dependency-update tooling. The complete npm v3 lock includes both CLIs and all 14 optional native packages with vendor-published tarball SHA512 integrity; `client-tools.lock.json` records provenance. The Dockerfile uses `npm ci`; no checksums are invented. Version-update PRs must also update the CLI assertions, image tag and reviewed compatibility tests; updates do not activate themselves. The base image uses a version tag and apt resolves packages at build time; a trusted release build must record the base digest, package inventory and resulting image ID for archival reproducibility. Workers use the selected local image ID. Keep the strict broker allowlist and required MCP initialization under a real authenticated smoke test before activation.

## Official references

- [Codex 0.164.0 configuration schema](https://github.com/openai/codex/blob/rust-v0.164.0/codex-rs/core/config.schema.json): pinned role/config fields.
- [Codex non-interactive execution](https://developers.openai.com/codex/noninteractive): ephemeral runs, user-config exclusion, required MCP and final-message events.
- [Codex app-server](https://developers.openai.com/codex/app-server), [managed configuration](https://learn.chatgpt.com/docs/enterprise/managed-configuration): native discovery and administrator requirements.
- [Claude native skills](https://code.claude.com/docs/en/skills), [instruction imports](https://code.claude.com/docs/en/memory), [native agents](https://code.claude.com/docs/en/sub-agents): supported adapters and source discovery.
- [Claude CLI flags](https://code.claude.com/docs/en/cli-reference), [headless output](https://code.claude.com/docs/en/headless), [gateway connection](https://code.claude.com/docs/en/llm-gateway-connect), [MCP configuration](https://code.claude.com/docs/en/mcp): verified launch/auth/HTTP interfaces.
- [Claude installation](https://code.claude.com/docs/en/setup): explicit version installation and update controls; [container guidance](https://code.claude.com/docs/en/devcontainer).
- [Claude Sonnet 5.5 API model and prices](https://platform.claude.com/docs/en/models/sonnet-5-5/overview), [Claude Code model/version support](https://code.claude.com/docs/en/model-config), [managed settings](https://code.claude.com/docs/en/managed-settings).
- [Context7 clients and exact tools](https://context7.com/docs/resources/all-clients), [Codex integration](https://context7.com/docs/clients/codex): bearer authentication and documentation lookup workflow.
- [OpenAI Docs MCP](https://developers.openai.com/learn/docs-mcp): official public endpoint and client setup. Direct server initialize/tools-list/search/fetch were verified during setup on 2026-10-27; isolated native connections remain unverified.
