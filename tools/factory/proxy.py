#!/usr/bin/env python3
"""Per-job, fixed-destination credential broker. Never mount this process in a worker."""
from __future__ import annotations

import argparse
import hmac
import http.server
import json
import math
import os
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
    if prices is None and runner == "codex" and model == config.get("review_model"):
        source = config.get("pricing_usd_per_million", {})
        prices = {"input": source.get("review_input"), "output": source.get("review_output")}
    if not isinstance(prices, dict):
        raise Denied(f"author pricing for {runner} is not configured")
    limits = config["limits"]
    return {
        "runner": runner, "model": model,
        "input_price": positive(prices.get("input"), "author input price"),
        "output_price": positive(prices.get("output"), "author output price"),
        "max_cost": positive(limits.get("max_run_cost_usd", limits.get("max_cost_usd")), "max_run_cost_usd"),
        "max_output": int(positive(limits.get("author_output_tokens"), "author_output_tokens")),
        "timeout": min(3600, int(positive(limits.get("timeout_seconds"), "timeout_seconds"))),
    }


def check_payload_tree(value):
    """Disallow hosted tools/media/references whose cost the broker cannot bound."""
    if isinstance(value, dict):
        if any(key in value for key in ("image_url", "file_id", "file_url", "audio_url")):
            raise Denied("remote files and media are not supported by this budget policy")
        if value.get("type") in ("input_image", "image", "input_audio", "audio", "document", "input_file", "item_reference"):
            raise Denied("media inputs are not supported by this budget policy")
        if value.get("type") == "tool_search_output":
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
class BrokerPolicy:
    policy: dict
    started: float = field(default_factory=time.monotonic)
    reserved_cost: float = 0.0
    reserved_output: int = 0
    requests: int = 0
    context_requests: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def prepare(self, path: str, body: bytes) -> tuple[str, bytes, str]:
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
            return ("https://mcp.context7.com/mcp" if kind == "context7" else "https://developers.openai.com/mcp"), body, kind
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
            "codex": {"input", "instructions", "max_output_tokens", "parallel_tool_calls", "reasoning", "text", "store", "include", "truncation", "prompt_cache_key", "prompt_cache_retention", "safety_identifier", "user"},
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
        requested = data.get(output_key, 8192)
        if isinstance(requested, bool) or not isinstance(requested, int) or requested <= 0:
            raise Denied("invalid output token limit")
        with self.lock:
            remaining = self.policy["max_output"] - self.reserved_output
            output = min(requested, 8192, remaining)
            if output <= 0 or self.requests >= 64:
                raise Denied("author request/token budget exhausted")
            # Bytes conservatively bound text tokenizer input; reserve additional protocol
            # overhead and 2x input pricing for provider cache-write multipliers.
            estimate = ((len(body) + 8192) * self.policy["input_price"] * 2 + output * self.policy["output_price"]) / 1_000_000
            if self.reserved_cost + estimate > self.policy["max_cost"]:
                raise Denied("author cost budget exhausted")
            self.reserved_cost += estimate
            self.reserved_output += output
            self.requests += 1
        data[output_key] = output
        return upstream + ("?beta=true" if path.endswith("?beta=true") else ""), json.dumps(data, separators=(",", ":")).encode(), self.policy["runner"]


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
                upstream, forwarded, kind = policy.prepare(self.path, body)
                key = secrets.get(kind)
                if kind != "openai_docs" and not key:
                    raise Denied("upstream credential not configured")
                headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
                if kind == "claude":
                    headers["x-api-key"] = key
                    headers["anthropic-version"] = "2023-06-01"
                    beta = self.headers.get("anthropic-beta", "")
                    allowed_betas = {"claude-code-20250219", "prompt-caching-2024-07-31", "interleaved-thinking-2025-05-14", "fine-grained-tool-streaming-2025-05-14"}
                    selected = [item.strip() for item in beta.split(",") if item.strip() in allowed_betas]
                    if selected:
                        headers["anthropic-beta"] = ",".join(selected)
                elif kind != "openai_docs":
                    headers["Authorization"] = "Bearer " + key
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
                        self.wfile.write(chunk)
                        self.wfile.flush()
            except (Denied, ValueError) as exc:
                self.reply(403, str(exc))
            except urllib.error.HTTPError as exc:
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
    policy = BrokerPolicy(author_policy(json.loads(args.config.read_text()), args.runner))
    secrets = {"job": os.environ.get("FACTORY_PROXY_TOKEN", ""), "codex": os.environ.get("OPENAI_API_KEY"), "claude": os.environ.get("ANTHROPIC_API_KEY"), "context7": os.environ.get("CONTEXT7_API_KEY")}
    if len(secrets["job"]) < 32 or not secrets[args.runner] or not secrets["context7"]:
        raise SystemExit("broker credentials missing")
    server = http.server.ThreadingHTTPServer(("0.0.0.0", 8080), make_handler(policy, secrets))
    server.daemon_threads = True
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
