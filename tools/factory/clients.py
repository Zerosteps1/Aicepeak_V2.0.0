#!/usr/bin/env python3
"""Generate native adapters and execute authors in disposable Docker workers."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import resource
import select
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
sys.dont_write_bytecode = True  # Keep trusted control checkouts clean during CLI use.
import tempfile
import threading
import time
import tomllib
import unicodedata
import urllib.request

try:
    from .proxy import author_policy, Denied
except ImportError:
    from proxy import author_policy, Denied

SKILLS = ("factory-start", "factory-change", "factory-review", "factory-fix-review")
CONTROL_PATHS = (".agents", ".claude", ".codex", ".mcp.json", "AGENTS.md", "CLAUDE.md", "factory", "tools/factory")
IGNORED_DIRS = {".git", ".agents", ".claude", ".codex", ".ssh", ".aws", ".azure", ".kube", "node_modules", ".venv", "__pycache__"}
IGNORED_FILES = {".git", "AGENTS.md", "AGENTS.override.md", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json", ".npmrc", ".netrc", ".pypirc"}
AUTHOR_TOOLS = "Bash,Read,Write,Edit,Glob,Grep,Agent,Skill"
# --allowedTools only pre-approves; --tools removes every other built-in tool (Agent, Bash, Edit, Write, ...).
REVIEW_TOOLS = "Read,Glob,Grep,Skill"
# The schema of an unattended run's final report (trusted copies under factory/), by run kind: a read-only run
# returns review findings, every other run an author report. The launcher renders the validated JSON to Markdown.
REPORT_SCHEMAS = {"author": "factory/author-report.schema.json", "review": "factory/review-findings.schema.json"}
CODEX_REPORT_SCHEMA = "/tmp/factory/report.schema.json"
STRUCTURED_OUTPUT_TOOL = "StructuredOutput"
REPORT_INSTRUCTIONS = {
    "author": "Final response: return the author report through the structured output: a summary, every changed file, "
              "each verification command with its actual outcome and evidence, the status of each acceptance criterion, "
              "an evidence-based response to each review item (addressed, disputed or blocked), proposals for read-only "
              "control paths and the open issues. If you dispute feedback or make no patch, say why in the summary. Keep it "
              "under 6000 bytes. Do not include private reasoning or raw transcripts.",
    "review": "Final response: return the findings through the structured output, each with file, line (0 when it has "
              "no single line), the problem, the evidence and a minimal fix. No findings means no problems; then say why "
              "in the summary. Keep it under 6000 bytes. Do not include private reasoning or raw transcripts.",
}
DOC_TOOLS = "mcp__context7__resolve-library-id,mcp__context7__query-docs,mcp__openai_docs__search_openai_docs,mcp__openai_docs__list_openai_docs,mcp__openai_docs__fetch_openai_doc"
LABEL = re.compile(r"[a-z0-9][a-z0-9.-]{0,62}=[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
STREAM_LINE_LIMIT = 4 * 1024 * 1024
EVENT_LOG_LIMIT = 2 * 1024 * 1024
EVENT_TARGETS = ("file_path", "notebook_path", "path", "pattern", "command", "skill", "query", "libraryName", "url")


class ClientError(ValueError):
    pass


class CommandFailed(ClientError):
    """Carries stdout for the caller's own diagnosis (the worker's final events); it is never shown raw."""
    def __init__(self, tool: str, returncode: int, detail: str, stdout: bytes = b""):
        super().__init__(f"{tool} failed ({returncode}): {detail}")
        self.tool, self.returncode, self.detail, self.stdout = tool, returncode, detail, stdout


# Every worker runs with --dns 127.0.0.1 on purpose (no name resolution beyond the broker alias),
# so Docker's warning about it is expected on every run and would hide the real failure.
DOCKER_DNS_WARNING = re.compile(r"(?m)^WARNING: Localhost DNS\b[^\n]*may fail in containers\.?[ \t\r]*(?:\n|$)")


def failure_detail(stderr: bytes) -> str:
    """Bounded stderr of a failed command; stderr can be model- or daemon-controlled."""
    return DOCKER_DNS_WARNING.sub("", stderr.decode(errors="replace"))[-2000:].strip()


def regular_read(path: Path, limit=2 * 1024 * 1024) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ClientError(f"expected bounded regular file: {path}")
    return path.read_bytes()


def pinned_clients() -> tuple[str, dict[str, str]]:
    """(image tag, `--version` output per runner) from the npm manifest that installs both CLIs, so a version bump in
    that one file changes the image, the worker check and every reviewer check. The worker container mounts only this
    file and proxy.py, so it reads the manifest's copy in the image."""
    for path in (Path(__file__).resolve().parents[2] / "factory/package.json", Path("/opt/factory-clients/package.json")):
        if path.is_file():
            pins = json.loads(regular_read(path, 100000))["dependencies"]
            codex, claude = pins["@openai/codex"], pins["@anthropic-ai/claude-code"]
            return (f"aicepeak-factory-clients:codex-{codex}-claude-{claude}",
                    {"codex": f"codex-cli {codex}", "claude": f"{claude} (Claude Code)"})
    raise ClientError("factory/package.json not found")


IMAGE, VERSIONS = pinned_clients()


def configuration(root: Path) -> dict:
    return json.loads(regular_read(root / "factory/config.json"))


def render_adapters(root: Path) -> dict[str, bytes]:
    try:  # host only: the worker container mounts no contracts.py, and it never renders adapters
        from .contracts import REVIEWER
    except ImportError:
        from contracts import REVIEWER
    config = configuration(root)
    result = {"CLAUDE.md": b"@AGENTS.md\n"}
    for name in SKILLS:
        raw = regular_read(root / ".agents/skills" / name / "SKILL.md")
        text = raw.decode()
        if not text.startswith(f"---\nname: {name}\n") or "\ndescription: " not in text.split("\n---", 1)[0]:
            raise ClientError(f"invalid canonical skill frontmatter: {name}")
        result[f".claude/skills/{name}/SKILL.md"] = raw
    roles = json.loads(regular_read(root / ".agents/roles.json"))
    for name, data in roles.items():
        if name not in ("author", "reviewer") or set(data) != {"description", "instructions", "skills"}:
            raise ClientError("invalid canonical role")
        if not all(skill in SKILLS for skill in data["skills"]):
            raise ClientError("role references an unknown skill")
        codex_name = "factory_author" if name == "author" else "factory_senior_reviewer"
        claude_name = "factory-author" if name == "author" else "factory-local-reviewer"
        model, effort = (config["author_models"]["codex"], "high") if name == "author" else (REVIEWER["model"], REVIEWER["effort"])
        # Codex roles cannot set sandbox_mode; the local reviewer inherits the session sandbox.
        codex = f'model = {json.dumps(model)}\nmodel_reasoning_effort = {json.dumps(effort)}\ndeveloper_instructions = {json.dumps(data["instructions"])}\n'
        result[f".codex/agents/{codex_name}.toml"] = codex.encode()
        tools = "Read, Glob, Grep, Bash, Edit, Write, Skill" if name == "author" else "Read, Glob, Grep, Skill"
        tools += ", mcp__context7__resolve-library-id, mcp__context7__query-docs, mcp__openai_docs__search_openai_docs, mcp__openai_docs__list_openai_docs, mcp__openai_docs__fetch_openai_doc"
        text = f"---\nname: {claude_name}\ndescription: {json.dumps(data['description'])}\ntools: {tools}\nmodel: inherit\nskills:\n"
        text += "".join(f"  - {skill}\n" for skill in data["skills"])
        text += f"---\n{data['instructions']}\n"
        if name == "reviewer":
            text += "This is a local Claude review. It is not the independent OpenAI senior-review gate.\n"
        result[f".claude/agents/{claude_name}.md"] = text.encode()
    if set(roles) != {"author", "reviewer"}:
        raise ClientError("both canonical roles are required")
    result[".claude/settings.json"] = (json.dumps({"autoMemoryEnabled": False, "disableAllHooks": True, "disableBundledSkills": True}, indent=2) + "\n").encode()
    result[".mcp.json"] = (json.dumps({"mcpServers": {name: {"type": "http", "url": f"http://credential-proxy:8080/{route}/mcp", "headers": {"Authorization": "Bearer ${FACTORY_PROXY_TOKEN}"}} for name, route in (("context7", "context7"), ("openai_docs", "openai-docs"))}}, indent=2) + "\n").encode()
    result[".codex/config.toml"] = f'''# Generated by tools/factory/clients.py sync. Use the isolated launcher.
model = {json.dumps(config['author_models']['codex'])}
model_reasoning_effort = "high"
approval_policy = "never"
sandbox_mode = "workspace-write"
web_search = "disabled"

[features]
plugin_hooks = false
plugins = false
remote_plugin = false
memories = false
memory_tool = false
remote_models = false
responses_websockets = false
responses_websockets_v2 = false

[memories]
generate_memories = false
use_memories = false

[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false

[mcp_servers.context7]
url = "http://credential-proxy:8080/context7/mcp"
bearer_token_env_var = "FACTORY_PROXY_TOKEN"
enabled_tools = ["resolve-library-id", "query-docs"]
startup_timeout_sec = 30
tool_timeout_sec = 60
required = true

[mcp_servers.openai_docs]
url = "http://credential-proxy:8080/openai-docs/mcp"
bearer_token_env_var = "FACTORY_PROXY_TOKEN"
enabled_tools = ["search_openai_docs", "list_openai_docs", "fetch_openai_doc"]
startup_timeout_sec = 30
tool_timeout_sec = 60
required = true

[agents]
max_concurrent_threads_per_session = 2
max_depth = 1

[agents.factory_author]
description = "Implement the authorized repository change and verify it."
config_file = "agents/factory_author.toml"

[agents.factory_senior_reviewer]
description = "Local Astra code review; independent server review still decides the gate."
config_file = "agents/factory_senior_reviewer.toml"
'''.encode()
    return result


def check(root: Path) -> dict:
    expected = render_adapters(root)
    errors = []
    for name, content in expected.items():
        path = root / name
        try:
            actual = regular_read(path)
            if actual != content:
                errors.append(f"adapter drift: {name}")
            if name.endswith(".json"):
                json.loads(actual)
            elif name.endswith(".toml"):
                tomllib.loads(actual.decode())
        except (OSError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    for dirname in (".agents/skills", ".claude/skills"):
        path = root / dirname
        names = {p.name for p in path.iterdir()} if path.is_dir() else set()
        if names != set(SKILLS):
            errors.append(f"unexpected/missing skills in {dirname}")
    for dirname in (".claude", ".codex", ".agents"):
        for path in (root / dirname).rglob("*"):
            if path.is_symlink():
                errors.append(f"symlink in client policy: {path.relative_to(root)}")
            if path.is_file() and path.relative_to(root).as_posix() not in expected and path.relative_to(root).as_posix() not in {".agents/roles.json", *(f".agents/skills/{n}/SKILL.md" for n in SKILLS)}:
                errors.append(f"unmanaged client policy: {path.relative_to(root)}")
    if errors:
        raise ClientError("; ".join(errors))
    return {"status": "passed", "canonical_skills": list(SKILLS), "generated_files": len(expected)}


def sync(root: Path):
    for name, content in render_adapters(root).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            raise ClientError(f"refusing symlink: {name}")
        path.write_bytes(content)
    return check(root)


def copy_regular_tree(source: Path, destination: Path, *, sanitize=False):
    """No links, sockets, special files, credentials, history, or inherited agents."""
    count = 0
    total = 0
    for base, directories, names in os.walk(source, followlinks=False):
        base_path = Path(base)
        for name in list(directories):
            path = base_path / name
            if path.is_symlink():
                raise ClientError(f"symlink directory rejected: {path}")
            if sanitize and name in IGNORED_DIRS:
                directories.remove(name)
        for name in names:
            source_path = base_path / name
            rel = source_path.relative_to(source)
            if sanitize and (name in IGNORED_FILES or name.startswith(".env") or name.endswith((".pem", ".key"))):
                continue
            info = source_path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ClientError(f"non-regular file rejected: {rel}")
            if any(ord(c) < 32 for c in rel.as_posix()):
                raise ClientError("control characters in file path")
            count += 1
            total += info.st_size
            if count > 50000 or total > 256 * 1024 * 1024 or info.st_size > 8 * 1024 * 1024:
                raise ClientError("candidate exceeds file/byte limits")
            target = destination / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
            target.chmod(0o755 if info.st_mode & 0o111 else 0o644)


def sanitized_copy(candidate: Path, trusted: Path, destination: Path):
    check(trusted)
    destination.mkdir()
    copy_regular_tree(candidate, destination, sanitize=True)
    for relative in CONTROL_PATHS:
        source, target = trusted / relative, destination / relative
        if not source.exists():
            raise ClientError(f"trusted control path missing: {relative}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copy_regular_tree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(regular_read(source))


def clean_env(docker_config: Path | None = None) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
    if docker_config is not None:
        env["DOCKER_CONFIG"] = str(docker_config)
        if os.environ.get("FACTORY_DOCKER_HOST"):
            env["DOCKER_HOST"] = os.environ["FACTORY_DOCKER_HOST"]
    return env


def command(args, *, cwd=None, env=None, timeout=60, input=None, capture=True, on_line=None):
    if not capture:
        result = subprocess.run(args, cwd=cwd, env=env or clean_env(), input=input, timeout=timeout, check=False)
        if result.returncode:
            raise ClientError(f"{Path(args[0]).name} failed ({result.returncode})")
        return b""
    # Disk-backed, kernel-bounded capture: model logs cannot exhaust parent RAM/disk.
    def cap_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    if on_line is not None:
        return stream_lines(args, cwd=cwd, env=env or clean_env(), timeout=timeout, input=input, on_line=on_line, preexec_fn=cap_output)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        result = subprocess.run(args, cwd=cwd, env=env or clean_env(), input=input, stdout=out, stderr=err, timeout=timeout, check=False, preexec_fn=cap_output)
        out.seek(0)
        err.seek(0)
        stdout = out.read(8 * 1024 * 1024)
        stderr = err.read(8 * 1024 * 1024)
    if result.returncode:
        # Keep errors bounded, and never include a command/env dump with credentials.
        raise CommandFailed(Path(args[0]).name, result.returncode, failure_detail(stderr), stdout)
    return stdout


def _feed(stream, data: bytes):
    try:
        stream.write(data)
    except OSError:
        pass  # The child exited early; its exit status reports the failure.
    finally:
        try:
            stream.close()
        except OSError:
            pass


def stream_lines(args, *, cwd, env, timeout, input, on_line, preexec_fn) -> bytes:
    """Hand each stdout line to on_line without keeping the stream. A volume limit
    never ends a run whose budget is already spent: oversized lines are skipped."""
    deadline = time.monotonic() + timeout
    with tempfile.TemporaryFile() as err:
        process = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=err, preexec_fn=preexec_fn)
        try:
            if input is not None:
                threading.Thread(target=_feed, args=(process.stdin, input), daemon=True).start()
            descriptor, buffer, skipping = process.stdout.fileno(), b"", False
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(args, timeout)
                if not select.select([descriptor], [], [], remaining)[0]:
                    continue
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    end = buffer.find(b"\n")
                    if end < 0:
                        if len(buffer) > STREAM_LINE_LIMIT:
                            buffer, skipping = b"", True
                        break
                    line, buffer = buffer[:end], buffer[end + 1:]
                    if skipping:
                        skipping = False
                    elif line.strip() and len(line) <= STREAM_LINE_LIMIT:
                        on_line(line)
            if buffer.strip() and not skipping and len(buffer) <= STREAM_LINE_LIMIT:
                on_line(buffer)
            process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except BaseException:
            process.kill()
            process.wait()
            raise
        finally:
            process.stdout.close()
        if process.returncode:
            err.seek(0)
            raise CommandFailed(Path(args[0]).name, process.returncode, failure_detail(err.read(8 * 1024 * 1024)))
    return b""


def printable(text: str, limit: int) -> str:
    """Model-chosen text must not drive the maintainer's terminal: escape control and format characters."""
    shown = "".join(c if unicodedata.category(c) not in ("Cc", "Cf") else f"\\u{ord(c):04x}" for c in text[:limit])
    return shown + ("..." if len(text) > limit else "")


def tool_summaries(event) -> list[str]:
    """Only the tool name and its target: model text and reasoning never reach the event log."""
    message = event.get("message") if isinstance(event, dict) and event.get("type") == "assistant" else None
    content = message.get("content") if isinstance(message, dict) else None
    lines = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name") if isinstance(block.get("name"), str) else "tool"
        data = block.get("input") if isinstance(block.get("input"), dict) else {}
        target = next((data[key] for key in EVENT_TARGETS if isinstance(data.get(key), str) and data[key].strip()), "")
        target = target.strip().splitlines()[0] if target.strip() else ""
        lines.append(printable(name, 64) + (" " + printable(target, 120) if target else ""))
    return lines


class EventSink:
    def __init__(self, path: Path, secrets: tuple[str, ...]):
        self.descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        self.secrets, self.result, self.written = secrets, None, 0

    def __call__(self, line: bytes):
        for secret in self.secrets:  # before any truncation can cut a credential in half
            line = line.replace(secret.encode(), b"[credential redacted]")
        try:
            event = json.loads(line)
        except ValueError:
            return
        if isinstance(event, dict) and event.get("type") == "result":
            self.result = line  # The last result describes the whole session, as in json output.
            return
        for text in tool_summaries(event):
            for secret in self.secrets:
                text = text.replace(secret, "[credential redacted]")
            self.write(time.strftime("%H:%M:%S ") + text + "\n")

    def write(self, text: str):
        data = text.encode()
        if self.written + len(data) > EVENT_LOG_LIMIT:
            data = b"" if self.written >= EVENT_LOG_LIMIT else b"[event log limit reached]\n"
            self.written = EVENT_LOG_LIMIT
        else:
            self.written += len(data)
        if data:
            os.write(self.descriptor, data)

    def close(self):
        os.close(self.descriptor)


def reported_cost(runner: str, output: bytes | None) -> float | None:
    """Claude's own estimate from its result message; the broker's caps stay authoritative."""
    if runner != "claude" or not output:
        return None
    try:
        value = json.loads(output).get("total_cost_usd")
    except (ValueError, AttributeError):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return round(float(value), 4)


def git(root: Path, *args) -> bytes:
    return command(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.attributesFile=/dev/null", *args], cwd=root)


def initialize_baseline(root: Path):
    if (root / ".git").exists() or (root / ".git").is_symlink():
        raise ClientError("fresh candidate unexpectedly contains Git metadata")
    git(root, "init", "--quiet")
    git(root, "config", "user.name", "Factory Worker")
    git(root, "config", "user.email", "factory-worker@invalid.local")
    git(root, "add", "--all", "--force")
    git(root, "commit", "--quiet", "--no-gpg-sign", "-m", "Isolated input")


def extract_patch(root: Path, max_bytes: int) -> bytes:
    # Enumerate again before host Git touches the output. The worker cannot change
    # .git, and the host Git process has no user/global filters or hooks.
    total = count = 0
    for base, directories, files in os.walk(root, followlinks=False):
        if ".git" in directories:
            directories.remove(".git")
        for name in [*directories, *files]:
            path = Path(base) / name
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                raise ClientError("worker produced a symlink or special file")
            if path.is_file():
                count += 1
                size = path.stat().st_size
                total += size
                if count > 50000 or size > 8 * 1024 * 1024 or total > 256 * 1024 * 1024:
                    raise ClientError("worker output exceeds file/byte limits")
    git(root, "add", "--all", "--force")
    patch = git(root, "diff", "--cached", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", "--", ".")
    if len(patch) > max_bytes:
        raise ClientError("worker patch exceeds configured limit")
    return patch


def initialize_codex_trust(codex_home: Path, workspace: Path):
    """Create only project trust in the fresh worker home; never load personal state."""
    # Codex evaluates project trust before session CLI overrides. The native
    # clients must read this disposable user layer to load the sanitized project.
    with (codex_home / "config.toml").open("x", encoding="utf-8") as config:
        config.write(f'[projects.{json.dumps(str(workspace))}]\ntrust_level = "trusted"\n')


def codex_provider_arguments() -> list[str]:
    """Supply broker routing above the project layer, which Codex filters."""
    overrides = (
        'model_provider="factory"',
        'model_providers.factory.name="Per-job factory broker"',
        'model_providers.factory.base_url="http://credential-proxy:8080/openai/v1"',
        'model_providers.factory.env_key="FACTORY_PROXY_TOKEN"',
        'model_providers.factory.wire_api="responses"',
        'model_providers.factory.requires_openai_auth=false',
        'model_providers.factory.supports_websockets=false',
        'model_providers.factory.request_max_retries=0',
        'model_providers.factory.stream_max_retries=0',
        'model_providers.factory.capabilities.remote_compaction="unsupported"',
        'model_providers.factory.capabilities.external_web_access=false',
    )
    return [argument for override in overrides for argument in ("-c", override)]


def worker_arguments(runner: str, model: str, interactive=False, max_turns: int | None = None, max_budget_usd: float | None = None, *, read_only=False, stream=False, report_schema: str | None = None) -> list[str]:
    """The native CLI command line. An unattended run with report_schema returns its final report as JSON matching
    that schema: Claude through --json-schema (the result's structured_output), Codex through --output-schema
    (the final agent message; _worker writes the schema to CODEX_REPORT_SCHEMA first)."""
    structured = report_schema is not None and not interactive
    if runner == "codex":
        args = ["codex"] + ([] if interactive else ["exec", "--ephemeral", "--strict-config", "--json"])
        args += ["--model", model, "--sandbox", "read-only" if read_only else "danger-full-access", "-c", 'approval_policy="never"']
        if structured:
            args += ["--output-schema", CODEX_REPORT_SCHEMA]
        return args + codex_provider_arguments() + ([] if interactive else ["-"])
    args = ["claude", "--model", model, "--setting-sources", "project", "--strict-mcp-config", "--mcp-config", "/work/.mcp.json", "--no-chrome", "--permission-mode", "dontAsk"]
    # --json-schema adds Claude Code's read-only StructuredOutput tool; name it so neither the tool restriction nor
    # dontAsk can withhold it.
    output_tool = "," + STRUCTURED_OUTPUT_TOOL if structured else ""
    if read_only:
        args += ["--tools", REVIEW_TOOLS + output_tool]
    args += ["--allowedTools", (REVIEW_TOOLS if read_only else AUTHOR_TOOLS) + output_tool + "," + DOC_TOOLS]
    if not interactive:
        args += ["-p", "--no-session-persistence", "--permission-prompts", "none", "--output-format", "stream-json" if stream else "json"]
        if stream:
            args += ["--verbose"]  # stream-json in print mode requires it.
        # Second brake inside the worker; the broker budget stays authoritative (Claude's estimate can overshoot).
        if max_turns:
            args += ["--max-turns", str(max_turns)]
        if max_budget_usd:
            args += ["--max-budget-usd", str(max_budget_usd)]
        if structured:
            args += ["--json-schema", report_schema]
    return args


STOP_HINTS = {"error_max_turns": "turn limit limits.author_max_turns reached",
              "error_max_budget_usd": "USD budget limits.max_run_cost_usd reached",
              "error_max_structured_output_retries": "no schema-valid final report"}


def native_failure(runner: str, output: bytes | None, secrets: tuple[str, ...] = ()) -> str | None:
    """Why the native CLI stopped, from its own final events: fixed fields and a bounded, redacted
    excerpt of its error text; never reasoning or a transcript. None when the output says nothing."""
    text, parts = None, []
    if runner == "claude":
        # Claude Code's result message (Agent SDK SDKResultMessage): subtype, num_turns, errors on the
        # error subtypes; an API error ends as subtype success with is_error, api_error_status and result.
        try:
            data = json.loads(output or b"")
        except ValueError:
            return None
        if not isinstance(data, dict) or data.get("type", "result") != "result":
            return None
        subtype = data.get("subtype")
        if isinstance(subtype, str) and re.fullmatch(r"[a-z_]{1,64}", subtype) and subtype != "success":
            parts.append(subtype + (": " + STOP_HINTS[subtype] if subtype in STOP_HINTS else ""))
        status = data.get("api_error_status")
        if type(status) is int:
            parts.append(f"API status {status}")
        turns = data.get("num_turns")
        if type(turns) is int and turns >= 0:
            parts.append(f"{turns} turns")
        errors = data.get("errors")
        if isinstance(errors, list) and any(isinstance(e, str) and e.strip() for e in errors):
            text = "; ".join(e.strip() for e in errors if isinstance(e, str) and e.strip())
        elif data.get("is_error") is True and isinstance(data.get("result"), str):
            text = data["result"]
        name = "Claude"
    else:
        # Codex exec --json: the last turn.failed error or error event.
        for line in (output or b"").decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            error = event.get("error") if event.get("type") == "turn.failed" else event if event.get("type") == "error" else None
            message = error.get("message") if isinstance(error, dict) else None
            if isinstance(message, str) and message.strip():
                text = message
        name = "Codex"
    if text is not None:
        for secret in secrets:  # before the excerpt can cut a credential in half
            text = text.replace(secret, "[credential redacted]")
        text = printable(" ".join(text.split()), 300)
    if not parts and not text:
        return None
    return f"{name} stopped" + (f" ({', '.join(parts)})" if parts else "") + (f": {text}" if text else "")


def bullet(text) -> str:
    """One Markdown list item: the text on one line, so a model's line breaks cannot start new list items."""
    return " ".join(str(text).split())


def render_author_report(report: dict) -> str:
    """The validated author report as the Markdown its consumers read; empty sections are left out."""
    sections = [bullet(report["summary"])]
    for title, items, line in (
            ("Changed files", report["changes"], lambda i: f"`{bullet(i['path'])}`: {bullet(i['what'])}"),
            ("Verification", report["verification"],
             lambda i: f"`{bullet(i['command'])}`: {i['outcome']} — {bullet(i['evidence'])}"),
            ("Acceptance criteria", report["acceptance"],
             lambda i: f"{bullet(i['criterion'])}: {i['status']} — {bullet(i['evidence'])}"),
            ("Review items", report["review_items"],
             lambda i: f"{bullet(i['item'])}: {i['response']} — {bullet(i['explanation'])}"),
            ("Control-path proposals", report["control_proposals"],
             lambda i: f"`{bullet(i['path'])}`: {bullet(i['change'])}"),
            ("Open issues", report["open_issues"], bullet)):
        if items:
            sections.append(title + ":\n" + "\n".join("- " + line(item) for item in items))
    return "\n\n".join(sections)


def render_review_findings(review: dict) -> str:
    """The validated findings as a numbered Markdown list, or "No problems found" with the reason."""
    if not review["findings"]:
        return "No problems found: " + bullet(review["summary"])
    lines = [bullet(review["summary"]), ""]
    for number, item in enumerate(review["findings"], 1):
        where = bullet(item["file"]) + (f":{item['line']}" if item["line"] > 0 else "")
        lines += [f"{number}. `{where}`: {bullet(item['problem'])}", f"   Evidence: {bullet(item['evidence'])}",
                  f"   Fix: {bullet(item['fix'])}"]
    return "\n".join(lines)


RENDERERS = {"author": render_author_report, "review": render_review_findings}


def structured_report(runner: str, output: bytes) -> object:
    """The JSON final report of an unattended run: Claude's structured_output, or Codex's final agent message."""
    if runner == "claude":
        data = json.loads(output)
        if not isinstance(data, dict) or data.get("is_error") or data.get("subtype", "success") != "success":
            raise ClientError("Claude did not return a successful result")
        return data.get("structured_output")
    text, completed = None, False
    for line in output.decode("utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") in ("turn.failed", "error"):
            raise ClientError("Codex reported a failed turn")
        if event.get("type") == "turn.completed":
            completed = True
        item = event.get("item", {})
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text")
    if not completed:
        raise ClientError("Codex returned no completed turn")
    try:
        return json.loads(text) if isinstance(text, str) else None
    except ValueError:
        return None


def final_report(runner: str, output: bytes, kind: str, schema: dict) -> tuple[str, bool]:
    """The run's schema-bound final report rendered to Markdown; never reasoning or a raw transcript."""
    report = structured_report(runner, output)
    if not isinstance(report, dict):
        raise ClientError("author returned no structured report")
    # Host only: the worker container mounts no contracts.py and never calls this.
    try:
        from .contracts import Blocked, validate
    except ImportError:
        from contracts import Blocked, validate
    try:
        validate(report, schema, "report")
    except Blocked:
        raise ClientError("author report does not match its schema") from None
    text = RENDERERS[kind](report)
    if not text.strip():
        raise ClientError("author returned no final report")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise ClientError("author report contains control characters")
    encoded = text.strip().encode("utf-8")
    truncated = len(encoded) > 7900
    if truncated:
        text = encoded[:7900].decode("utf-8", errors="ignore") + "\n[Report truncated at 7900 bytes.]"
    return text.strip() + "\n", truncated


def probe_mcp(token: str, route: str, expected: set[str], *, exact: bool):
    """Fail before inference if required native documentation tools are unavailable."""
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def send(payload):
        request = urllib.request.Request(f"http://credential-proxy:8080/{route}/mcp", data=json.dumps(payload).encode(), headers=headers, method="POST")
        with opener.open(request, timeout=30) as response:
            raw = response.read(1024 * 1024 + 1)
            if response.headers.get("Mcp-Session-Id"):
                headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            if len(raw) > 1024 * 1024:
                raise ClientError(f"{route} discovery response is too large")
            if not raw.strip():
                return {}
            if "text/event-stream" in response.headers.get("Content-Type", ""):
                records = [json.loads(line[5:].strip()) for line in raw.decode().splitlines() if line.startswith("data:")]
                return next((record for record in records if record.get("id") == payload.get("id")), {})
            return json.loads(raw)
    initialized = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "aicepeak-factory-preflight", "version": "1"}}})
    version = initialized.get("result", {}).get("protocolVersion")
    if not isinstance(version, str):
        raise ClientError(f"{route} initialization failed")
    headers["MCP-Protocol-Version"] = version
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    discovered = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {tool.get("name") for tool in discovered.get("result", {}).get("tools", [])}
    if not expected.issubset(names) or (exact and names != expected):
        raise ClientError(f"{route} did not expose the reviewed documentation tool set")


def broker_healthy() -> bool:
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open("http://credential-proxy:8080/healthz", timeout=5) as response:
            return response.status == 200
    except OSError:
        return False


def egress_self_test(connect=socket.create_connection, healthz=broker_healthy):
    """Fail closed unless the broker is the worker's only reachable destination."""
    for host in ("1.1.1.1", "api.openai.com", "api.anthropic.com"):
        try:
            connection = connect((host, 443), timeout=3)
        except OSError:
            continue
        connection.close()
        raise ClientError(f"worker egress is open ({host}:443); refusing to start the author")
    if not healthz():
        raise ClientError("credential broker unreachable from the worker")


def probe_documentation(token: str):
    probe_mcp(token, "context7", {"resolve-library-id", "query-docs"}, exact=True)
    probe_mcp(token, "openai-docs", {"search_openai_docs", "list_openai_docs", "fetch_openai_doc"}, exact=False)


def container_flags(name: str, *, worker=False, labels=()) -> list[str]:
    args = ["docker", "run", "--rm", "--init", "--name", name, "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=256", "--memory=4g", "--cpus=2", "--user", f"{os.getuid()}:{os.getgid()}", "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777"]
    for label in labels:
        args += ["--label", label]
    if worker:
        args += ["--dns", "127.0.0.1", "--workdir", "/work"]
    return args


def mount(source: Path, target: str, readonly=True) -> list[str]:
    if "," in str(source):
        raise ClientError("commas in mount paths are unsupported")
    return ["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")]


def inspect_codex_discovery(skills: dict, effective: dict) -> dict:
    rows = [row for row in skills.get("data", []) if row.get("cwd") == "/work"]
    if len(rows) != 1 or rows[0].get("errors"):
        raise ClientError("native Codex skill discovery failed")
    for name in SKILLS:
        matches = [item for item in rows[0].get("skills", []) if item.get("enabled") and item.get("name") == name]
        if len(matches) != 1 or matches[0].get("path") != f"/work/.agents/skills/{name}/SKILL.md" or matches[0].get("scope") != "repo":
            raise ClientError(f"Codex did not load the canonical project skill: {name}")
    config = effective.get("config", {})
    if config.get("model_provider") != "factory":
        raise ClientError("Codex did not load the reviewed provider; managed-policy mismatch requires administrator review")
    if not {"factory_author", "factory_senior_reviewer"}.issubset(config.get("agents", {})):
        raise ClientError("Codex did not load both configured native roles")
    if set(config.get("mcp_servers", {})) != {"context7", "openai_docs"}:
        raise ClientError("Codex MCP configuration differs from the reviewed factory configuration")
    return {"status": "passed", "project_skills": list(SKILLS), "roles": ["factory_author", "factory_senior_reviewer"], "mcp_configured": ["context7", "openai_docs"]}


def codex_native_discovery() -> dict:
    """Read native app-server state without thread/start or any model turn."""
    args = ["codex", "app-server", "--stdio", "--strict-config"]
    args += codex_provider_arguments()
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, env=os.environ, bufsize=0)
        buffer = b""
        total = 0
        deadline = time.monotonic() + 30
        def send(message):
            process.stdin.write(json.dumps(message).encode() + b"\n")
            process.stdin.flush()
        def request(identifier, method, params):
            nonlocal buffer, total
            send({"id": identifier, "method": method, "params": params})
            while time.monotonic() < deadline:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if value.get("id") == identifier:
                        if "error" in value:
                            raise ClientError(f"native Codex {method} rejected the smoke request")
                        return value.get("result", {})
                readable, _, _ = select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))
                if not readable:
                    break
                chunk = os.read(process.stdout.fileno(), 65536)
                total += len(chunk)
                if not chunk or total > 2 * 1024 * 1024 or errors.tell() > 2 * 1024 * 1024:
                    raise ClientError("native Codex discovery stopped or exceeded its output bound")
                buffer += chunk
            raise ClientError("native Codex discovery timed out")
        try:
            request(1, "initialize", {"clientInfo": {"name": "aicepeak_factory_smoke", "version": "1"}})
            send({"method": "initialized", "params": {}})
            skills = request(2, "skills/list", {"cwds": ["/work"], "forceReload": True})
            effective = request(3, "config/read", {"cwd": "/work", "includeLayers": False})
            requirements = request(4, "configRequirements/read", {})
            result = inspect_codex_discovery(skills, effective)
            result["managed_requirements_present"] = requirements.get("requirements") is not None
            return result
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()


def boundary_probe(project: Path, host_canary: Path) -> dict:
    if (project / ".factory-smoke-readable").read_text() != "factory smoke positive control\n":
        raise ClientError("smoke positive control is unreadable")
    for path in (host_canary, project / ".factory-smoke-outside-link"):
        try:
            path.read_bytes()
        except (FileNotFoundError, PermissionError):
            continue
        raise ClientError("outside-project canary was readable from the worker")
    try:
        with (project / "AGENTS.md").open("ab"):
            pass  # No bytes are written even if the protection is missing.
    except (PermissionError, OSError) as exc:
        if exc.errno not in (1, 13, 30):
            raise
    else:
        raise ClientError("trusted instructions are writable from the worker")
    return {"status": "passed", "project_read": "allowed", "outside_host_read": "denied", "symlink_escape": "denied", "trusted_instruction_write": "denied"}


def smoke_inside(host_canary: Path) -> dict:
    if Path.cwd() != Path("/work"):
        raise ClientError("smoke entrypoint requires the isolated /work mount")
    for key in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
        Path(os.environ[key]).mkdir(parents=True, exist_ok=True)
    initialize_codex_trust(Path(os.environ["CODEX_HOME"]), Path("/work"))
    boundary = boundary_probe(Path("/work"), host_canary)
    for runner, expected in VERSIONS.items():
        actual = command([runner, "--version"], env=os.environ, timeout=15).decode().strip()
        if actual != expected:
            raise ClientError(f"unexpected {runner} version in image")
    native_codex = codex_native_discovery()
    for directory in ("/work/.claude/skills", "/work/.claude/agents"):
        command(["claude", "--setting-sources", "project", "plugin", "validate", "--json", "--strict", directory], env=os.environ, timeout=30)
    command(["claude", "--setting-sources", "project", "doctor"], env=os.environ, timeout=30)
    return {"status": "passed", "cli_versions": VERSIONS, "boundary": boundary, "codex_native_discovery": native_codex, "claude_native_validation": "passed; doctor executed", "not_verified": ["Claude authenticated startup skill discovery", "provider inference", "native Context7 and OpenAI Docs connections"], "model_execution": "not attempted"}


def smoke(root: Path) -> dict:
    check(root)
    if not shutil.which("docker"):
        return {"status": "blocked", "reason": "Docker CLI not installed", "model_execution": "not attempted"}
    with tempfile.TemporaryDirectory(prefix="factory-smoke-") as directory:
        scratch = Path(directory)
        env = clean_env(scratch / "docker")
        (scratch / "docker").mkdir()
        container_name = "factory-smoke-" + secrets.token_hex(4)
        container_started = False
        try:
            command(["docker", "info", "--format", "{{.ServerVersion}}"], env=env, timeout=15)
            image_id = command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], env=env, timeout=15).decode().strip()
            if not image_id.startswith("sha256:") or len(image_id) != 71:
                raise ClientError("expected a content-addressed Docker image")
            staged = scratch / "work"
            sanitized_copy(root, root, staged)
            initialize_baseline(staged)
            outside = scratch / "outside-project-canary.txt"
            marker = "harmless factory boundary canary " + secrets.token_hex(16)
            outside.write_text(marker)
            (staged / ".factory-smoke-readable").write_text("factory smoke positive control\n")
            (staged / ".factory-smoke-outside-link").symlink_to(outside)
            args = container_flags(container_name, worker=True) + ["--network", "none"]
            args += mount(staged, "/work")
            args += mount(root / "tools/factory/clients.py", "/opt/factory/clients.py")
            args += mount(root / "tools/factory/proxy.py", "/opt/factory/proxy.py")
            for key, value in {"HOME": "/tmp/factory/home", "CODEX_HOME": "/tmp/factory/codex", "CLAUDE_CONFIG_DIR": "/tmp/factory/claude", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_UPDATES": "1", "FACTORY_PROXY_TOKEN": "smoke-placeholder-with-no-authority"}.items():
                args += ["--env", f"{key}={value}"]
            args += [image_id, "python3", "/opt/factory/clients.py", "_smoke", "--host-canary", str(outside)]
            container_started = True
            report = json.loads(command(args, env=env, timeout=120))
            if outside.read_text() != marker:
                raise ClientError("host canary was modified")
            return report
        except (ClientError, subprocess.TimeoutExpired, OSError) as exc:
            return {"status": "blocked", "reason": str(exc), "model_execution": "not attempted"}
        finally:
            if container_started:
                # Killing a timed-out Docker client does not stop its container.
                subprocess.run(["docker", "rm", "-f", container_name], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15, check=False)


def run(candidate: Path, trusted: Path, runner: str, prompt: bytes | None, output_patch: Path, *, interactive=False,
        labels=(), read_only=False, events: Path | None = None) -> dict:
    labels = tuple(labels)
    if len(labels) > 8 or not all(LABEL.fullmatch(label) for label in labels):
        raise ClientError("invalid Docker labels")
    if read_only and (interactive or prompt is None):
        raise ClientError("a read-only review needs a prompt")
    stream = events is not None and runner == "claude" and not interactive
    label_args = [value for label in labels for value in ("--label", label)]
    config = configuration(trusted)
    policy = author_policy(config, runner)
    check(trusted)
    # An unattended run returns a schema-bound final report; the trusted root supplies the schema.
    kind = None if interactive else ("review" if read_only else "author")
    schema = json.loads(regular_read(trusted / REPORT_SCHEMAS[kind], 100000)) if kind else None
    # In the pipeline the Claude author uses Workload Identity Federation: only the job's OIDC
    # request credential reaches the broker, which mints short-lived Anthropic tokens itself.
    federated = runner == "claude" and bool(os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"))
    provider_keys = ("ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN") if federated else ("OPENAI_API_KEY" if runner == "codex" else "ANTHROPIC_API_KEY",)
    missing = [name for name in (*provider_keys, "CONTEXT7_API_KEY") if not os.environ.get(name)]
    if missing:
        raise ClientError("missing proxy-only environment: " + ", ".join(missing))
    if not shutil.which("docker"):
        raise ClientError("Docker CLI not installed")
    if prompt is not None and len(prompt) > 200000:
        raise ClientError("prompt too large")
    with tempfile.TemporaryDirectory(prefix="aicepeak-factory-") as temp:
        scratch = Path(temp)
        work = scratch / "work"
        docker_config = scratch / "docker"
        docker_config.mkdir()
        env = clean_env(docker_config)
        command(["docker", "info", "--format", "{{.ServerVersion}}"], env=env, timeout=15)
        image_id = command(["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"], env=env, timeout=15).decode().strip()
        if not image_id.startswith("sha256:") or len(image_id) != 71:
            raise ClientError("expected a content-addressed Docker image")
        sanitized_copy(candidate, trusted, work)
        initialize_baseline(work)
        token = secrets.token_urlsafe(48)
        network = "factory-internal-" + secrets.token_hex(8)
        proxy_name = "factory-proxy-" + secrets.token_hex(8)
        worker_name = "factory-worker-" + secrets.token_hex(8)
        keeper_name = "factory-volume-keeper-" + secrets.token_hex(8)
        volume = "factory-work-" + secrets.token_hex(8)
        proxy_env = dict(env, FACTORY_PROXY_TOKEN=token)
        for name in (*provider_keys, "CONTEXT7_API_KEY"):
            proxy_env[name] = os.environ[name]
        try:
            command(["docker", "network", "create", "--internal", *label_args, network], env=env)
            command(["docker", "volume", "create", "--driver", "local", "--opt", "type=tmpfs", "--opt", "device=tmpfs", "--opt", f"o=size=512m,uid={os.getuid()},gid={os.getgid()},mode=0700", *label_args, volume], env=env)
            # volume-nocopy: otherwise each new container copies the image's /work owner
            # (1000:1000, 0755) onto the empty tmpfs root and the host-uid seed cannot write.
            work_mount = ["--mount", f"type=volume,source={volume},target=/work,volume-nocopy"]
            # Docker's local tmpfs driver discards data when its final mount is
            # released. Keep one trusted, network-disabled mount alive across
            # seeding, authoring and extraction.
            keeper = container_flags(keeper_name, labels=labels) + ["--detach", "--network", "none"]
            keeper += work_mount + [image_id, "python3", "-c", f"import time; time.sleep({policy['timeout'] + 180})"]
            command(keeper, env=env)
            seed = container_flags("factory-seed-" + secrets.token_hex(8), labels=labels) + ["--network", "none"]
            seed += work_mount + mount(work, "/input")
            seed += [image_id, "python3", "-c", "import shutil; shutil.copytree('/input', '/work', dirs_exist_ok=True)"]
            command(seed, env=env)
            proxy_args = container_flags(proxy_name, labels=labels) + ["--detach", "--network", "bridge", "--env", "FACTORY_PROXY_TOKEN", "--env", "CONTEXT7_API_KEY"]
            for name in provider_keys:
                proxy_args += ["--env", name]
            proxy_args += mount(trusted / "tools/factory/proxy.py", "/opt/factory/proxy.py")
            proxy_args += mount(trusted / "factory/config.json", "/run/factory-config.json")
            proxy_args += [image_id, "python3", "/opt/factory/proxy.py", "--config", "/run/factory-config.json", "--runner", runner]
            command(proxy_args, env=proxy_env)
            command(["docker", "network", "connect", "--alias", "credential-proxy", network, proxy_name], env=env)
            # Health check is executed by the trusted launcher, never by a model.
            ready = False
            for _ in range(20):
                result = subprocess.run(["docker", "exec", proxy_name, "python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=1).read()"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                if result.returncode == 0:
                    ready = True
                    break
                time.sleep(0.1)
            if not ready:
                raise ClientError("credential broker did not become ready")
            args = container_flags(worker_name, worker=True, labels=labels) + ["--network", network, "--interactive"]
            if interactive and sys.stdin.isatty():
                args += ["--tty"]
            # A review sees the same files but cannot change them; its own state lives on /tmp.
            args += [work_mount[0], work_mount[1] + ",readonly"] if read_only else work_mount
            for relative in (*CONTROL_PATHS, ".git"):
                args += mount(work / relative, "/work/" + relative)
            args += mount(trusted / "tools/factory/clients.py", "/opt/factory/clients.py")
            args += mount(trusted / "tools/factory/proxy.py", "/opt/factory/proxy.py")
            for name, value in {"FACTORY_PROXY_TOKEN": token, "CLAUDE_CONFIG_DIR": "/tmp/factory/claude", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_UPDATES": "1", "ANTHROPIC_BASE_URL": "http://credential-proxy:8080/anthropic", "ANTHROPIC_AUTH_TOKEN": token, "CODEX_HOME": "/tmp/factory/codex", "HOME": "/tmp/factory/home", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}.items():
                args += ["--env", f"{name}={value}"]
            args += [image_id, "python3", "/opt/factory/clients.py", "_worker", "--runner", runner, "--model", policy["model"],
                     "--max-turns", str(int(config["limits"].get("author_max_turns", 60))), "--max-budget-usd", str(policy["max_cost"])]
            if interactive:
                args += ["--interactive"]
            if read_only:
                args += ["--read-only"]
            if stream:
                args += ["--events"]
            if schema is not None:
                args += ["--report-schema", json.dumps(schema, separators=(",", ":"))]
            if prompt is not None:
                prompt += b"\n\n" + REPORT_INSTRUCTIONS[kind].encode()
            credentials = (token, *(proxy_env[name] for name in (*provider_keys, "CONTEXT7_API_KEY")))
            sink = EventSink(events, credentials) if stream else None
            try:
                native_output = command(args, env=env, timeout=policy["timeout"], input=prompt, capture=not interactive, on_line=sink)
            except CommandFailed as failure:
                # The native CLI's own final events say why it stopped; Docker's stderr rarely does.
                # The fixed "<tool> failed (<code>):" prefix stays first for engine.author_failure.
                reason = native_failure(runner, sink.result if sink else failure.stdout, credentials)
                if reason is None:
                    raise
                raise ClientError(f"{failure.tool} failed ({failure.returncode}): {reason}"
                                  + (f"; {failure.detail}" if failure.detail else "")) from None
            finally:
                if sink:
                    sink.close()
            if sink:
                if sink.result is None:
                    raise ClientError("author returned no final report")
                native_output = sink.result
            report, report_truncated = ("Interactive session completed; inspect the patch and verify it before use.\n", False) if interactive else final_report(runner, native_output, kind, schema)
            cost = None if interactive else reported_cost(runner, native_output)
            for secret in credentials:
                report = report.replace(secret, "[credential redacted]")
            output_patch.parent.mkdir(parents=True, exist_ok=True)
            report_path = Path(str(output_patch) + ".report.txt")
            if output_patch.is_symlink() or report_path.is_symlink():
                raise ClientError("patch and report outputs may not be symlinks")
            result = {"status": "completed", "runner": runner, "report": str(report_path), "report_truncated": report_truncated,
                      "reported_cost_usd": cost, "reserved_cost_ceiling_usd": policy["max_cost"], "publication": "none"}
            if read_only:
                result.update(patch=None, patch_sha256=None, patch_bytes=0, read_only=True)
            else:
                extract = container_flags("factory-extract-" + secrets.token_hex(8), worker=True, labels=labels) + ["--network", "none"]
                extract += work_mount
                extract += mount(trusted / "tools/factory/clients.py", "/opt/factory/clients.py")
                extract += mount(trusted / "tools/factory/proxy.py", "/opt/factory/proxy.py")
                extract += [image_id, "python3", "/opt/factory/clients.py", "_extract", "--max-bytes", str(int(config["limits"]["max_patch_bytes"]))]
                patch = command(extract, env=env)
                output_patch.write_bytes(patch)
                result.update(patch=str(output_patch), patch_sha256=hashlib.sha256(patch).hexdigest(), patch_bytes=len(patch))
            report_path.write_text(report, encoding="utf-8")
            report_path.chmod(0o600)
            return result
        finally:
            for name in (worker_name, proxy_name, keeper_name):
                subprocess.run(["docker", "rm", "--force", name], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            subprocess.run(["docker", "network", "rm", network], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            subprocess.run(["docker", "volume", "rm", "--force", volume], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)


def _cancelled(_signum, _frame):
    raise KeyboardInterrupt()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("image", help="print the author image tag that factory/package.json pins")
    for name in ("check", "sync", "smoke", "launch", "run"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, required=True)
        if name in ("launch", "run"):
            item.add_argument("--runner", choices=("codex", "claude"), required=True)
        if name == "run":
            item.add_argument("--policy-root", type=Path, required=True)
            item.add_argument("--prompt-file", type=Path, required=True)
            item.add_argument("--output-patch", type=Path, required=True)
            item.add_argument("--label", action="append", default=[], help="Docker label key=value for every container, network and volume of the run")
            item.add_argument("--read-only", action="store_true", help="review only: no file-changing tools, no patch")
            item.add_argument("--events-file", type=Path, help="append one line per author tool call (Claude only)")
    item = sub.add_parser("_worker")
    item.add_argument("--runner", choices=("codex", "claude"), required=True)
    item.add_argument("--model", required=True)
    item.add_argument("--interactive", action="store_true")
    item.add_argument("--max-turns", type=int)
    item.add_argument("--max-budget-usd", type=float)
    item.add_argument("--read-only", action="store_true")
    item.add_argument("--events", action="store_true")
    item.add_argument("--report-schema", help="JSON Schema of the final report (unattended runs)")
    item = sub.add_parser("_extract")
    item.add_argument("--max-bytes", type=int, required=True)
    item = sub.add_parser("_smoke")
    item.add_argument("--host-canary", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "image":
        print(IMAGE)
        return 0
    try:
        if args.command == "_smoke":
            print(json.dumps(smoke_inside(args.host_canary)))
            return 0
        if args.command == "_extract":
            if Path.cwd() != Path("/work") or not 0 < args.max_bytes <= 2 * 1024 * 1024:
                raise ClientError("invalid extraction context")
            sys.stdout.buffer.write(extract_patch(Path("/work"), args.max_bytes))
            return 0
        if args.command == "_worker":
            if Path.cwd() != Path("/work") or os.environ.get("FACTORY_PROXY_TOKEN") is None:
                raise ClientError("worker entrypoint is only valid in the factory container")
            for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR"):
                Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
            if args.runner == "codex":
                initialize_codex_trust(Path(os.environ["CODEX_HOME"]), Path("/work"))
            actual = command([args.runner, "--version"], env=os.environ).decode().strip()
            if actual != VERSIONS[args.runner]:
                raise ClientError("worker CLI version mismatch")
            egress_self_test()
            probe_documentation(os.environ["FACTORY_PROXY_TOKEN"])
            if args.report_schema is not None and args.runner == "codex" and not args.interactive:
                schema_file = Path(CODEX_REPORT_SCHEMA)
                schema_file.parent.mkdir(parents=True, exist_ok=True)
                schema_file.write_text(args.report_schema, encoding="utf-8")
            native = worker_arguments(args.runner, args.model, args.interactive, args.max_turns, args.max_budget_usd,
                                      read_only=args.read_only, stream=args.events, report_schema=args.report_schema)
            os.execvpe(native[0], native, os.environ)
        # A cancelling controller sends SIGTERM: unwind so `finally` removes containers, network and volume.
        signal.signal(signal.SIGTERM, _cancelled)
        root = args.root.resolve(strict=True)
        if args.command in ("check", "sync", "smoke"):
            result = globals()[args.command](root)
        elif args.command == "run":
            result = run(root, args.policy_root.resolve(strict=True), args.runner, regular_read(args.prompt_file, 200000), args.output_patch.absolute(),
                         labels=args.label, read_only=args.read_only, events=args.events_file.absolute() if args.events_file else None)
        else:
            output = Path(tempfile.mkdtemp(prefix="factory-launch-result-")) / "changes.patch"
            result = run(root, root, args.runner, None, output, interactive=True)
        print(json.dumps(result, indent=2))
        return 2 if result.get("status") == "blocked" else 0
    except KeyboardInterrupt:
        print(json.dumps({"status": "blocked", "reason": "cancelled"}), file=sys.stderr)
        return 130
    except (ClientError, Denied, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
