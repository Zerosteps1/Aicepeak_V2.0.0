#!/usr/bin/env python3
"""Per-job, fixed-destination credential broker. Never mount this process in a worker."""
from __future__ import annotations

import argparse
import hmac
import http.server
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


class Denied(ValueError):
    pass


def positive(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Denied(f"{name} must be a positive number")
    if not math.isfinite(value) or value <= 0:
        raise Denied(f"{name} must be a positive finite number")
    return float(value)


def author_policy(config: dict, runner: str) -> dict:
    if runner not in ("codex", "claude"):
        raise Denied("unsupported runner")
    model = config.get("author_models", {}).get(runner)
    if not isinstance(model, str) or not model or len(model) > 100:
        raise Denied(f"author_models.{runner} is not configured")
    prices = config.get("author_pricing_usd_per_million", {}).get(runner)
    if not isinstance(prices, dict):
        raise Denied(f"author pricing for {runner} is not configured")
    limits = config["limits"]
    input_price = positive(prices.get("input"), "author input price")
    return {
        "runner": runner, "model": model,
        "input_price": input_price,
        "output_price": positive(prices.get("output"), "author output price"),
        # Without explicit cache prices, cached tokens are charged at the full input price.
        "cache_read_price": positive(prices.get("cache_read", input_price), "author cache read price"),
        "cache_write_price": positive(prices.get("cache_write", input_price), "author cache write price"),
        "max_cost": positive(limits.get("max_run_cost_usd", limits.get("max_cost_usd")), "max_run_cost_usd"),
        "max_output": int(positive(limits.get("author_output_tokens"), "author_output_tokens")),
        "request_output": int(positive(limits.get("author_request_output_tokens", 32000), "author_request_output_tokens")),
        "max_requests": int(positive(limits.get("author_requests", 200), "author_requests")),
        "timeout": min(3600, int(positive(limits.get("timeout_seconds"), "timeout_seconds"))),
    }


def check_payload_tree(value):
    """Disallow hosted tools/media/references whose cost the broker cannot bound."""
    if isinstance(value, dict):
        if any(key in value for key in ("image_url", "file_id", "file_url", "audio_url")):
            raise Denied("remote files and media are not supported by this budget policy")
        if value.get("type") in ("input_image", "image", "input_audio", "audio", "document", "input_file", "item_reference"):
            raise Denied("media inputs are not supported by this budget policy")
        # Codex 0.164.0 announces its tools incrementally as additional_tools input items.
        if value.get("type") in ("tool_search_output", "additional_tools"):
            for tool in value.get("tools", []):
                check_codex_tool(tool)
        for item in value.values():
            check_payload_tree(item)
    elif isinstance(value, list):
        for item in value:
            check_payload_tree(item)


def check_codex_tool(tool):
    if not isinstance(tool, dict):
        raise Denied("invalid tool definition")
    kind = tool.get("type")
    if kind in ("function", "custom"):
        return
    if kind == "namespace":
        children = tool.get("tools")
        if not isinstance(children, list) or any(not isinstance(child, dict) or child.get("type") not in ("function", "custom") for child in children):
            raise Denied("only client function/custom tools belong in a namespace")
        return
    if kind == "tool_search" and tool.get("execution") == "client":
        return
    raise Denied("hosted tools are not permitted")


@dataclass
class Reservation:
    cost: float
    output: int


@dataclass
class BrokerPolicy:
    """Admission by reservation, accounting by provider-reported usage.

    reserved_cost/reserved_output hold settled usage plus the reservations of requests
    still in flight; settle() swaps a reservation for the actual usage.
    """
    policy: dict
    started: float = field(default_factory=time.monotonic)
    reserved_cost: float = 0.0
    reserved_output: int = 0
    requests: int = 0
    context_requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def prepare(self, path: str, body: bytes) -> tuple[str, bytes, str, Reservation | None]:
        if time.monotonic() - self.started > self.policy["timeout"]:
            raise Denied("job deadline exceeded")
        if len(body) > 2 * 1024 * 1024:
            raise Denied("request too large")
        try:
            data = json.loads(body)
        except (UnicodeError, ValueError):
            raise Denied("request must contain valid JSON") from None
        if not isinstance(data, dict):
            raise Denied("JSON object required")
        if path in ("/context7/mcp", "/openai-docs/mcp"):
            kind = "context7" if path == "/context7/mcp" else "openai_docs"
            method = data.get("method")
            if method not in ("initialize", "notifications/initialized", "ping", "tools/list", "tools/call"):
                raise Denied("unsupported documentation MCP method")
            if method == "tools/call":
                params = data.get("params", {})
                allowed_tools = ("resolve-library-id", "query-docs") if kind == "context7" else ("search_openai_docs", "list_openai_docs", "fetch_openai_doc")
                if not isinstance(params, dict) or params.get("name") not in allowed_tools:
                    raise Denied("only reviewed documentation tools are allowed")
                arguments = params.get("arguments")
                if not isinstance(arguments, dict):
                    raise Denied("invalid documentation arguments")
                if kind == "context7":
                    required = ("libraryName", "query") if params["name"] == "resolve-library-id" else ("libraryId", "query")
                    if not all(isinstance(arguments.get(k), str) and 0 < len(arguments[k]) <= 8000 for k in required):
                        raise Denied("invalid Context7 arguments")
                else:
                    validate_openai_docs_arguments(params["name"], arguments)
            with self.lock:
                if self.context_requests >= 64:
                    raise Denied("documentation MCP request limit exceeded")
                self.context_requests += 1
            return ("https://mcp.context7.com/mcp" if kind == "context7" else "https://developers.openai.com/mcp"), body, kind, None
        allowed = {
            "codex": ("/openai/v1/responses", "https://api.openai.com/v1/responses", "max_output_tokens"),
            "claude": ("/anthropic/v1/messages", "https://api.anthropic.com/v1/messages", "max_tokens"),
        }
        route, upstream, output_key = allowed[self.policy["runner"]]
        if path != route and not (self.policy["runner"] == "claude" and path == route + "?beta=true"):
            raise Denied("route not permitted")
        if data.get("model") != self.policy["model"]:
            raise Denied("model not permitted")
        if any(data.get(k) for k in ("previous_response_id", "conversation", "background", "prompt", "container", "mcp_servers", "fallbacks")):
            raise Denied("remote persistence and background requests are not permitted")
        common = {"model", "tools", "tool_choice", "stream", "temperature", "top_p", "metadata", "service_tier"}
        provider_fields = {
            # Codex 0.164.0 always serializes client_metadata (trace keys only); stream_options and
            # prompt_cache_options are delivery/cache controls. Re-check this set on every CLI update.
            "codex": {"input", "instructions", "max_output_tokens", "parallel_tool_calls", "reasoning", "text", "store", "include", "truncation", "prompt_cache_key", "prompt_cache_retention", "prompt_cache_options", "stream_options", "client_metadata", "safety_identifier", "user"},
            "claude": {"messages", "system", "max_tokens", "thinking", "stop_sequences", "top_k", "speed", "output_config", "context_management"},
        }
        if set(data) - common - provider_fields[self.policy["runner"]]:
            raise Denied("unsupported provider request fields")
        check_payload_tree(data)
        for tool in data.get("tools", []):
            if not isinstance(tool, dict):
                raise Denied("invalid tool definition")
            if self.policy["runner"] == "codex":
                check_codex_tool(tool)
            if self.policy["runner"] == "claude" and tool.get("type", "custom") != "custom":
                raise Denied("hosted tools are not permitted")
        if self.policy["runner"] == "codex":
            data["store"] = False
            data["service_tier"] = "default"
        elif data.get("speed") not in (None, "standard"):
            raise Denied("premium inference speed is not permitted")
        elif data.get("service_tier") not in (None, "standard_only"):
            raise Denied("premium inference tier is not permitted")
        requested = data.get(output_key, self.policy["request_output"])
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise Denied("invalid output token limit")
        with self.lock:
            remaining = self.policy["max_output"] - self.reserved_output
            # A per-request ceiling, not a session cap: unused output is returned by settle().
            output = min(requested, self.policy["request_output"], remaining)
            if output <= 0 or self.requests >= self.policy["max_requests"]:
                raise Denied("author request/token budget exhausted")
            # About 3 bytes per token bounds JSON-heavy prompts; 1.25x covers a full cache write.
            input_tokens = (len(body) + 8192) / 3
            estimate = (input_tokens * max(self.policy["input_price"], self.policy["cache_write_price"]) * 1.25
                        + output * self.policy["output_price"]) / 1_000_000
            if self.reserved_cost + estimate > self.policy["max_cost"]:
                raise Denied("author cost budget exhausted")
            self.reserved_cost += estimate
            self.reserved_output += output
            self.requests += 1
        data[output_key] = output
        forwarded = json.dumps(data, separators=(",", ":")).encode()
        return upstream + ("?beta=true" if path.endswith("?beta=true") else ""), forwarded, self.policy["runner"], Reservation(estimate, output)

    def usage_cost(self, usage: dict) -> tuple[float, int]:
        def count(value):
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
        price = self.policy
        output = count(usage.get("output_tokens"))
        if price["runner"] == "codex":
            cached = count((usage.get("input_tokens_details") or {}).get("cached_tokens"))
            uncached = max(0, count(usage.get("input_tokens")) - cached)
            cost = uncached * price["input_price"] + cached * price["cache_read_price"]
        else:
            cost = (count(usage.get("input_tokens")) * price["input_price"]
                    + count(usage.get("cache_creation_input_tokens")) * price["cache_write_price"]
                    + count(usage.get("cache_read_input_tokens")) * price["cache_read_price"])
        return (cost + output * price["output_price"]) / 1_000_000, output

    def settle(self, reservation: Reservation | None, usage: dict | None):
        """Replace a reservation by reported usage. Unknown usage keeps the reservation charged."""
        if reservation is None or usage is None:
            return
        cost, output = self.usage_cost(usage)
        with self.lock:
            self.reserved_cost += cost - reservation.cost
            self.reserved_output += output - reservation.output


class UsageScanner:
    """Extract the provider usage block from a streamed (SSE) or plain JSON response."""

    def __init__(self, runner: str):
        self.runner = runner
        self.buffer = b""
        self.usage = None
        self.plain = b""

    def feed(self, chunk: bytes):
        if len(self.plain) < 16 * 1024 * 1024:
            self.plain += chunk
        self.buffer += chunk
        *lines, self.buffer = self.buffer.split(b"\n")
        for line in lines:
            if line.startswith(b"data:"):
                try:
                    self.event(json.loads(line[5:]))
                except ValueError:
                    continue

    def event(self, data):
        if not isinstance(data, dict):
            return
        if self.runner == "codex" and data.get("type") in ("response.completed", "response.incomplete", "response.failed"):
            usage = (data.get("response") or {}).get("usage")
        elif self.runner == "claude" and data.get("type") == "message_start":
            usage = (data.get("message") or {}).get("usage")
        elif self.runner == "claude" and data.get("type") == "message_delta":
            usage = data.get("usage")
        else:
            return
        if isinstance(usage, dict):
            self.usage = {**(self.usage or {}), **usage}

    def result(self) -> dict | None:
        if self.usage is None and self.plain.lstrip().startswith(b"{"):
            try:
                usage = json.loads(self.plain).get("usage")
                self.usage = usage if isinstance(usage, dict) else None
            except (ValueError, AttributeError):
                pass
        return self.usage


# Betas observed from Claude Code 2.1.312 (fixture); request fields stay allowlisted separately.
ALLOWED_BETAS = ("claude-code-20250219", "prompt-caching-2024-07-31", "interleaved-thinking-2025-05-14",
                 "fine-grained-tool-streaming-2025-05-14", "context-management-2025-06-27", "per-turn-control-2026-07-01",
                 "mid-conversation-tool-changes-2026-07-01", "thinking-token-count-2026-05-13", "advanced-tool-use-2025-11-20",
                 "effort-2025-11-24")


def forwarded_betas(header: str) -> str:
    return ",".join(item.strip() for item in header.split(",") if item.strip() in ALLOWED_BETAS)


def upstream_headers(kind: str, key: str, beta: str) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if kind == "claude":
        # Workload Identity Federation tokens are OAuth bearer tokens; API keys use x-api-key.
        if key.startswith("sk-ant-oat"):
            headers["Authorization"] = "Bearer " + key
        else:
            headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        if forwarded_betas(beta):
            headers["anthropic-beta"] = forwarded_betas(beta)
    elif kind != "openai_docs":
        headers["Authorization"] = "Bearer " + key
    return headers


class FederatedToken:
    """Short-lived Anthropic token from the job's GitHub OIDC identity (Workload Identity Federation)."""
    PATTERNS = {"organization_id": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                "service_account_id": r"svac_[A-Za-z0-9]+", "federation_rule_id": r"fdrl_[A-Za-z0-9]+"}

    def __init__(self, federation: dict, request_url: str, request_token: str, opener=None):
        for name, pattern in self.PATTERNS.items():
            if not isinstance(federation.get(name), str) or not re.fullmatch(pattern, federation[name]):
                raise Denied(f"anthropic_federation.{name} is not configured")
        workspace = federation.get("workspace_id")
        if workspace is not None and not (isinstance(workspace, str) and re.fullmatch(r"wrkspc_[A-Za-z0-9]+", workspace)):
            raise Denied("anthropic_federation.workspace_id is invalid")
        parsed = urllib.parse.urlsplit(request_url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".actions.githubusercontent.com") or not request_token:
            raise Denied("GitHub OIDC request endpoint missing or unexpected")
        self.federation, self.request_url, self.request_token = federation, request_url, request_token
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open
        self.token, self.expires = "", 0.0
        self.lock = threading.Lock()

    def fetch(self, request) -> dict:
        try:
            with self.opener(request, timeout=30) as response:
                return json.loads(response.read(65536))
        except urllib.error.HTTPError as exc:
            raise Denied(f"federated credential exchange failed (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise Denied("federated credential exchange unavailable") from None

    def get(self) -> str:
        with self.lock:
            if self.token and time.monotonic() < self.expires - 120:
                return self.token
            # GitHub identity tokens carry a jti and are single use: fetch a fresh one per exchange.
            audience = urllib.parse.quote("https://api.anthropic.com", safe="")
            identity = self.fetch(urllib.request.Request(f"{self.request_url}&audience={audience}",
                                                         headers={"Authorization": "Bearer " + self.request_token}))
            body = {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": identity.get("value", ""),
                    **{k: self.federation[k] for k in self.PATTERNS}}
            if self.federation.get("workspace_id"):
                body["workspace_id"] = self.federation["workspace_id"]
            minted = self.fetch(urllib.request.Request("https://api.anthropic.com/v1/oauth/token", data=json.dumps(body).encode(),
                                                       headers={"Content-Type": "application/json"}, method="POST"))
            token, lifetime = minted.get("access_token", ""), minted.get("expires_in")
            if not (isinstance(token, str) and token.startswith("sk-ant-oat")) or not isinstance(lifetime, int) or lifetime < 60:
                raise Denied("federated credential exchange returned no usable token")
            self.token, self.expires = token, time.monotonic() + lifetime
            return token


def validate_openai_docs_arguments(name: str, arguments: dict):
    fields = {"search_openai_docs": {"query", "limit", "cursor"}, "list_openai_docs": {"limit", "cursor"}, "fetch_openai_doc": {"url", "anchor"}}[name]
    if set(arguments) - fields:
        raise Denied("unsupported OpenAI Docs arguments")
    for key in ("query", "cursor", "anchor"):
        if key in arguments and (not isinstance(arguments[key], str) or not 0 < len(arguments[key]) <= 8000):
            raise Denied("invalid OpenAI Docs text argument")
    if name == "search_openai_docs" and "query" not in arguments:
        raise Denied("OpenAI Docs search requires a query")
    if "limit" in arguments and (isinstance(arguments["limit"], bool) or not isinstance(arguments["limit"], int) or not 1 <= arguments["limit"] <= 20):
        raise Denied("OpenAI Docs result limit must be 1..20")
    if name == "fetch_openai_doc":
        value = arguments.get("url")
        if not isinstance(value, str) or not 0 < len(value) <= 2048 or any(ord(c) < 33 for c in value):
            raise Denied("invalid OpenAI Docs URL")
        parsed = urllib.parse.urlsplit(value)
        allowed = parsed.hostname == "developers.openai.com" or (parsed.hostname in ("platform.openai.com", "learn.chatgpt.com") and parsed.path.startswith("/docs/"))
        if parsed.scheme != "https" or not allowed or parsed.username or parsed.password or parsed.port is not None or parsed.query or parsed.fragment:
            raise Denied("only public official OpenAI documentation URLs are allowed")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def make_handler(policy: BrokerPolicy, secrets: dict):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass  # Never log request paths, headers, prompts, or credentials.

        def reply(self, status: int, message: str):
            payload = json.dumps({"error": message}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(payload)
            self.close_connection = True

        def do_GET(self):
            if self.path == "/healthz":
                self.reply(200, "ready")
            else:
                self.reply(405, "only POST is supported")

        def do_DELETE(self):
            self.reply(405, "session deletion is not supported")

        def do_POST(self):
            token = self.headers.get("Authorization", "")
            if not hmac.compare_digest(token, "Bearer " + secrets["job"]):
                self.reply(401, "invalid job credential")
                return
            try:
                if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
                    raise Denied("encoded requests are not supported")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 2 * 1024 * 1024:
                    raise Denied("invalid request size")
                self.connection.settimeout(15)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise Denied("incomplete request")
                upstream, forwarded, kind, reservation = policy.prepare(self.path, body)
                credential = secrets.get(kind)
                key = credential.get() if isinstance(credential, FederatedToken) else credential
                if kind != "openai_docs" and not key:
                    raise Denied("upstream credential not configured")
                headers = upstream_headers(kind, key or "", self.headers.get("anthropic-beta", ""))
                scanner = UsageScanner(kind)
                if kind in ("context7", "openai_docs"):
                    for header in ("Mcp-Session-Id", "MCP-Protocol-Version"):
                        value = self.headers.get(header)
                        if value and len(value) <= 512 and all(32 <= ord(c) < 127 for c in value):
                            headers[header] = value
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                request = urllib.request.Request(upstream, data=forwarded, headers=headers, method="POST")
                with opener.open(request, timeout=min(policy.policy["timeout"], 120)) as response:
                    self.send_response(response.status)
                    self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                    self.send_header("Connection", "close")
                    if kind in ("context7", "openai_docs") and response.headers.get("Mcp-Session-Id"):
                        self.send_header("Mcp-Session-Id", response.headers["Mcp-Session-Id"])
                    self.end_headers()
                    self.close_connection = True
                    total = 0
                    while True:
                        chunk = response.read1(65536)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > 16 * 1024 * 1024 or time.monotonic() - policy.started > policy.policy["timeout"]:
                            break
                        scanner.feed(chunk)
                        self.wfile.write(chunk)
                        self.wfile.flush()
                policy.settle(reservation, scanner.result())
            except (Denied, ValueError) as exc:
                self.reply(403, str(exc))
            except urllib.error.HTTPError as exc:
                # A rejected request produced no tokens; return its reservation.
                policy.settle(locals().get("reservation"), {})
                self.reply(502, f"upstream rejected request ({exc.code})")
            except (urllib.error.URLError, TimeoutError, OSError):
                self.close_connection = True
                # Do not surface urllib exception text; it can contain sensitive URLs.
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runner", choices=("codex", "claude"), required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    policy = BrokerPolicy(author_policy(config, args.runner))
    secrets = {"job": os.environ.get("FACTORY_PROXY_TOKEN", ""), "codex": os.environ.get("OPENAI_API_KEY"), "claude": os.environ.get("ANTHROPIC_API_KEY"), "context7": os.environ.get("CONTEXT7_API_KEY")}
    if args.runner == "claude" and os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"):
        # In the pipeline the author authenticates through Workload Identity Federation, never a stored key.
        secrets["claude"] = FederatedToken(config.get("anthropic_federation") or {}, os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"],
                                           os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", ""))
    if len(secrets["job"]) < 32 or not secrets[args.runner] or not secrets["context7"]:
        raise SystemExit("broker credentials missing")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8080), make_handler(policy, secrets))
    server.daemon_threads = True
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
