"""Boundary tests: no Docker daemon, network, personal configuration, or credentials."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import types
import unittest
from unittest import mock

REPO = Path(os.environ.get("FACTORY_CANDIDATE", Path(__file__).resolve().parents[3])).resolve()
# The harness is trusted base code, while the implementation under test must
# come from the candidate even with python -I and previously imported modules.
_package = types.ModuleType("_factory_client_candidate")
_package.__path__ = [str(REPO / "tools/factory")]
sys.modules[_package.__name__] = _package
def _candidate_module(name):
    spec = importlib.util.spec_from_file_location(f"{_package.__name__}.{name}", REPO / "tools/factory" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module
proxy = _candidate_module("proxy")
clients = _candidate_module("clients")
CONFIG = {
    "author_models": {"codex": "gpt-6-astra", "claude": None},
    "review_model": "gpt-6-astra",
    "limits": {"max_cost_usd": 25, "max_run_cost_usd": 5, "author_output_tokens": 32000, "timeout_seconds": 900, "max_patch_bytes": 200000},
    "pricing_usd_per_million": {"review_input": 10, "review_output": 50},
    "author_pricing_usd_per_million": {"codex": {"input": 10, "output": 50}, "claude": None},
}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "trusted"
        self.root.mkdir()
        shutil.copytree(REPO / ".agents", self.root / ".agents")
        (self.root / "factory").mkdir()
        (self.root / "factory/config.json").write_text(json.dumps(CONFIG))
        (self.root / "factory/policy.md").write_text("Trusted policy")
        (self.root / "tools/factory").mkdir(parents=True)
        (self.root / "tools/factory/placeholder.py").write_text("# trusted")
        (self.root / "AGENTS.md").write_text("Trusted repository instructions")
        clients.sync(self.root)

    def test_four_canonical_skills_and_drift(self):
        self.assertEqual(clients.check(self.root)["canonical_skills"], list(clients.SKILLS))
        adapter = self.root / ".claude/skills/factory-review/SKILL.md"
        adapter.write_text(adapter.read_text() + "\nInjected policy")
        with self.assertRaisesRegex(clients.ClientError, "drift"):
            clients.check(self.root)

    def test_project_adapter_has_no_ignored_provider_routing(self):
        config = tomllib.loads((self.root / ".codex/config.toml").read_text())
        self.assertNotIn("model_provider", config)
        self.assertNotIn("model_providers", config)
        self.assertTrue(config["mcp_servers"]["context7"]["required"])
        self.assertTrue(config["mcp_servers"]["openai_docs"]["required"])

    def test_role_adapters_omit_keys_codex_ignores_for_roles(self):
        # Codex 0.164.0 discards sandbox_mode from role files; the line would only mislead readers.
        for name in ("factory_author", "factory_senior_reviewer"):
            role = tomllib.loads((self.root / f".codex/agents/{name}.toml").read_text())
            self.assertNotIn("sandbox_mode", role)

    def test_unmanaged_config_and_symlink_are_rejected(self):
        (self.root / ".claude/settings.local.json").write_text("{}")
        with self.assertRaisesRegex(clients.ClientError, "unmanaged"):
            clients.check(self.root)
        (self.root / ".claude/settings.local.json").unlink()
        (self.root / ".claude/unexpected").symlink_to("/tmp")
        with self.assertRaisesRegex(clients.ClientError, "symlink"):
            clients.check(self.root)

    def test_sanitization_replaces_candidate_policy_and_ignores_linked_git(self):
        candidate = Path(self.temp.name) / "candidate"
        candidate.mkdir()
        (candidate / ".git").write_text("gitdir: /host/other-repository/.git/worktrees/foo")
        (candidate / "AGENTS.md").write_text("Malicious instructions")
        (candidate / ".env").write_text("SYNTHETIC_SECRET=do-not-copy")
        (candidate / ".npmrc").write_text("registry=https://untrusted.example")
        (candidate / "source.py").write_text("print('hello')")
        (candidate / "nested/.claude").mkdir(parents=True)
        (candidate / "nested/.claude/settings.json").write_text('{"hooks":{}}')
        result = Path(self.temp.name) / "work"
        clients.sanitized_copy(candidate, self.root, result)
        self.assertFalse((result / ".git").exists())
        self.assertFalse((result / ".env").exists())
        self.assertFalse((result / ".npmrc").exists())
        self.assertFalse((result / "nested/.claude").exists())
        self.assertEqual((result / "AGENTS.md").read_text(), "Trusted repository instructions")
        self.assertEqual((result / "source.py").read_text(), "print('hello')")
        clients.initialize_baseline(result)
        self.assertTrue((result / ".git").is_dir())

    def test_symlink_cannot_import_host_content(self):
        candidate = Path(self.temp.name) / "candidate"
        candidate.mkdir()
        (candidate / "read-me").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(clients.ClientError, "non-regular"):
            clients.sanitized_copy(candidate, self.root, Path(self.temp.name) / "result")

    def test_existing_git_metadata_never_initialized(self):
        work = Path(self.temp.name) / "work"
        work.mkdir()
        (work / ".git").write_text("gitdir: /do/not/follow")
        with mock.patch.object(clients, "git") as git:
            with self.assertRaisesRegex(clients.ClientError, "metadata"):
                clients.initialize_baseline(work)
            git.assert_not_called()

    def test_smoke_never_mounts_outside_canary_or_provider_secrets(self):
        calls = []
        real_command = clients.command
        image_id = "sha256:" + "b" * 64
        def fake_command(args, **kwargs):
            if args[0] == "git":
                return real_command(args, **kwargs)
            calls.append((args, kwargs.get("env", {})))
            if args[1:3] == ["image", "inspect"]:
                return image_id.encode()
            if "_smoke" in args:
                canary = Path(args[args.index("--host-canary") + 1])
                self.assertTrue(canary.is_file())
                mounts = [args[i + 1] for i, value in enumerate(args) if value == "--mount"]
                self.assertEqual(len(mounts), 3)
                self.assertTrue(all(value.endswith(",readonly") for value in mounts))
                self.assertTrue(all(f"source={canary}" not in value and f"source={canary.parent}," not in value for value in mounts))
                self.assertEqual(args[args.index("--network") + 1], "none")
                return b'{"status":"passed","model_execution":"not attempted"}'
            return b""
        real_run = subprocess.run
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "never-in-smoke", "ANTHROPIC_API_KEY": "never-in-smoke", "CONTEXT7_API_KEY": "never-in-smoke"}), mock.patch.object(clients.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(clients, "command", side_effect=fake_command), mock.patch.object(clients.subprocess, "run", side_effect=lambda args, **kw: subprocess.CompletedProcess(args, 0) if args[0] == "docker" else real_run(args, **kw)):
            self.assertEqual(clients.smoke(self.root)["status"], "passed")
        self.assertNotIn("never-in-smoke", str(calls))

    def test_patch_contains_new_files_and_no_commit(self):
        work = Path(self.temp.name) / "work"
        work.mkdir()
        (work / "old.txt").write_text("before\n")
        clients.initialize_baseline(work)
        before = clients.git(work, "rev-parse", "HEAD")
        (work / "old.txt").write_text("after\n")
        (work / "new.txt").write_text("new\n")
        patch = clients.extract_patch(work, 10000)
        self.assertIn(b"new file mode", patch)
        self.assertIn(b"+after", patch)
        self.assertEqual(clients.git(work, "rev-parse", "HEAD"), before)

    def test_output_validation_precedes_git(self):
        work = Path(self.temp.name) / "work"
        work.mkdir()
        (work / "escape").symlink_to("/etc/passwd")
        with mock.patch.object(clients, "git") as git:
            with self.assertRaisesRegex(clients.ClientError, "symlink"):
                clients.extract_patch(work, 1000)
            git.assert_not_called()

    def test_run_uses_only_image_ids_and_secretless_worker_and_keeps_report(self):
        candidate = Path(self.temp.name) / "candidate"
        candidate.mkdir()
        (candidate / "app.py").write_text("pass\n")
        output = Path(self.temp.name) / "changes.patch"
        calls = []
        real_command = clients.command
        image_id = "sha256:" + "a" * 64
        events = b'\n'.join(json.dumps(event).encode() for event in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Disputed R1: no code change needed; test evidence attached."}},
            {"type": "turn.completed"},
        ])

        def fake_command(args, **kwargs):
            if args[0] == "git":
                return real_command(args, **kwargs)
            calls.append((args, kwargs.get("env", {})))
            if args[1:3] == ["image", "inspect"]:
                return image_id.encode()
            if "_worker" in args:
                return events
            return b""

        real_run = subprocess.run
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "upstream-only-test-value", "CONTEXT7_API_KEY": "context-only-test-value", "GH_TOKEN": "never-forward"}), mock.patch.object(clients.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(clients, "command", side_effect=fake_command), mock.patch.object(clients.subprocess, "run", wraps=real_run) as subprocess_run:
            # Only direct calls here are Docker health/cleanup; Git still needs the
            # real process runner through command().
            subprocess_run.side_effect = lambda args, **kw: subprocess.CompletedProcess(args, 0) if args[0] == "docker" else real_run(args, **kw)
            result = clients.run(candidate, self.root, "codex", b"Review R1", output)
        self.assertEqual(output.read_bytes(), b"")
        self.assertIn("Disputed R1", Path(result["report"]).read_text())
        worker = next((args, env) for args, env in calls if "_worker" in args)
        self.assertIn(image_id, worker[0])
        self.assertNotIn(clients.IMAGE, worker[0])
        self.assertNotIn("OPENAI_API_KEY", worker[1])
        self.assertNotIn("CONTEXT7_API_KEY", worker[1])
        self.assertNotIn("never-forward", str(calls))
        self.assertFalse(any("target=/work," in value and "type=bind" in value for value in worker[0]))
        self.assertTrue(any("volume-keeper" in str(args) and "none" in args for args, _ in calls))
        proxy_call = next((args, env) for args, env in calls if "/opt/factory/proxy.py" in args and "--config" in args)
        self.assertEqual(proxy_call[1]["OPENAI_API_KEY"], "upstream-only-test-value")
        self.assertNotIn("upstream-only-test-value", " ".join(proxy_call[0]))


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.policy = proxy.BrokerPolicy(proxy.author_policy(CONFIG, "codex"))

    def payload(self, **kwargs):
        return json.dumps({"model": "gpt-6-astra", "input": "test", **kwargs}).encode()

    def test_fixed_upstream_and_standard_tier(self):
        url, body, kind = self.policy.prepare("/openai/v1/responses", self.payload(service_tier="priority", store=True))
        self.assertEqual(url, "https://api.openai.com/v1/responses")
        self.assertEqual(kind, "codex")
        self.assertFalse(json.loads(body)["store"])
        self.assertEqual(json.loads(body)["service_tier"], "default")
        self.assertLessEqual(json.loads(body)["max_output_tokens"], 8192)

    def test_foreign_route_and_foreign_model_rejected(self):
        for route in ("https://evil.example", "/openai/v1/responses?url=https://evil.example", "/anthropic/v1/messages", "/openai/v1/models"):
            with self.subTest(route=route), self.assertRaises(proxy.Denied):
                self.policy.prepare(route, self.payload())
        with self.assertRaisesRegex(proxy.Denied, "model"):
            self.policy.prepare("/openai/v1/responses", self.payload(model="other"))

    def test_native_namespace_and_client_search_without_hosted_tools(self):
        tools = [{"type": "namespace", "name": "functions", "tools": [{"type": "function", "name": "exec"}]}, {"type": "tool_search", "execution": "client"}]
        self.policy.prepare("/openai/v1/responses", self.payload(tools=tools))
        tools[0]["tools"].append({"type": "web_search"})
        with self.assertRaises(proxy.Denied):
            self.policy.prepare("/openai/v1/responses", self.payload(tools=tools))
        with self.assertRaises(proxy.Denied):
            self.policy.prepare("/openai/v1/responses", self.payload(tools=[{"type": "tool_search", "execution": "server"}]))

    def test_remote_sources_and_hosted_tools_rejected(self):
        for field, value in {"prompt": {"id": "remote-template"}, "previous_response_id": "old", "mcp_servers": [{"url": "https://evil.example"}], "fallbacks": [{"model": "other"}], "container": "other-session", "background": True}.items():
            with self.subTest(field=field), self.assertRaises(proxy.Denied):
                self.policy.prepare("/openai/v1/responses", self.payload(**{field: value}))
        with self.assertRaisesRegex(proxy.Denied, "hosted"):
            self.policy.prepare("/openai/v1/responses", self.payload(tools=[{"type": "web_search"}]))
        with self.assertRaises(proxy.Denied):
            self.policy.prepare("/openai/v1/responses", self.payload(input=[{"type": "item_reference", "id": "old"}]))

    def test_output_and_cost_reservations_are_monotonic(self):
        tiny = copy.deepcopy(CONFIG)
        tiny["limits"]["author_output_tokens"] = 10
        broker = proxy.BrokerPolicy(proxy.author_policy(tiny, "codex"))
        _, body, _ = broker.prepare("/openai/v1/responses", self.payload())
        self.assertEqual(json.loads(body)["max_output_tokens"], 10)
        with self.assertRaisesRegex(proxy.Denied, "budget"):
            broker.prepare("/openai/v1/responses", self.payload())
        self.assertGreater(broker.reserved_cost, 0)
        tiny["limits"]["max_run_cost_usd"] = 0.000001
        broker = proxy.BrokerPolicy(proxy.author_policy(tiny, "codex"))
        with self.assertRaisesRegex(proxy.Denied, "cost"):
            broker.prepare("/openai/v1/responses", self.payload())
        self.assertEqual(broker.reserved_cost, 0)

    def test_unset_claude_and_invalid_prices_fail_closed(self):
        with self.assertRaisesRegex(proxy.Denied, "not configured"):
            proxy.author_policy(CONFIG, "claude")
        bad = copy.deepcopy(CONFIG)
        bad["author_pricing_usd_per_million"]["codex"]["input"] = float("nan")
        with self.assertRaises(proxy.Denied):
            proxy.author_policy(bad, "codex")
        self.assertEqual(proxy.author_policy(CONFIG, "codex")["max_cost"], 5)

    def test_only_documentation_mcp_calls(self):
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "resolve-library-id", "arguments": {"libraryName": "Python", "query": "json parsing"}}}
        url, _, kind = self.policy.prepare("/context7/mcp", json.dumps(call).encode())
        self.assertEqual(url, "https://mcp.context7.com/mcp")
        self.assertEqual(kind, "context7")
        call["params"]["name"] = "execute-command"
        with self.assertRaisesRegex(proxy.Denied, "documentation"):
            self.policy.prepare("/context7/mcp", json.dumps(call).encode())

    def test_openai_docs_fixed_route_tools_and_official_fetch_urls(self):
        def invoke(name, arguments):
            return self.policy.prepare("/openai-docs/mcp", json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).encode())
        url, _, kind = invoke("search_openai_docs", {"query": "Responses API", "limit": 3})
        self.assertEqual((url, kind), ("https://developers.openai.com/mcp", "openai_docs"))
        invoke("list_openai_docs", {"limit": 5})
        for value in ("https://developers.openai.com/codex/skills", "https://platform.openai.com/docs/api-reference/responses", "https://learn.chatgpt.com/docs/skills"):
            invoke("fetch_openai_doc", {"url": value})
        for value in ("http://developers.openai.com/codex/skills", "https://developers.openai.com.evil.example/doc", "https://user@developers.openai.com/codex/skills", "https://127.0.0.1/docs", "https://platform.openai.com/settings", "https://developers.openai.com:443/codex/skills"):
            with self.subTest(url=value), self.assertRaises(proxy.Denied):
                invoke("fetch_openai_doc", {"url": value})
        for name, arguments in (("get_openapi_spec", {}), ("fetch_openai_doc", {"url": "https://developers.openai.com/codex/skills", "headers": {}}), ("search_openai_docs", {"query": "test", "limit": 500})):
            with self.subTest(name=name), self.assertRaises(proxy.Denied):
                invoke(name, arguments)

    def test_openai_docs_upstream_receives_no_job_or_provider_credential(self):
        body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        handler_type = proxy.make_handler(self.policy, {"job": "job-token", "codex": "provider-token", "context7": "context-token"})
        handler = object.__new__(handler_type)
        handler.headers = {"Authorization": "Bearer job-token", "Content-Length": str(len(body)), "Mcp-Session-Id": "public-session"}
        handler.path = "/openai-docs/mcp"
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.connection = mock.Mock()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.headers = {"Content-Type": "application/json"}
        response.read1.side_effect = [b'{"result":{}}', b'']
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(proxy.urllib.request, "build_opener", return_value=opener):
            handler.do_POST()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://developers.openai.com/mcp")
        self.assertFalse(any(key.lower() in ("authorization", "x-api-key") for key in request.headers))
        self.assertNotIn("token", str(request.headers))
        handler.send_response.assert_called_once_with(200)

    def test_codex_0_164_0_request_body_is_accepted(self):
        # Shape of ResponsesApiRequest at rust-v0.164.0: client_metadata is always serialized.
        fixture = json.loads((Path(__file__).parent / "fixtures/codex-0.164.0-request.json").read_bytes())
        _, body, _ = self.policy.prepare("/openai/v1/responses", json.dumps(fixture).encode())
        self.assertEqual(json.loads(body)["client_metadata"], fixture["client_metadata"])
        for field, value in {"stream_options": {"reasoning_summary_delivery": "sequential_cutoff"}, "prompt_cache_options": {"ttl": "24h"}}.items():
            with self.subTest(field=field):
                self.policy.prepare("/openai/v1/responses", json.dumps({**fixture, field: value}).encode())

    def test_unknown_fields_media_and_expired_job_rejected(self):
        with self.assertRaisesRegex(proxy.Denied, "unsupported"):
            self.policy.prepare("/openai/v1/responses", self.payload(unknown_option=True))
        with self.assertRaises(proxy.Denied):
            self.policy.prepare("/openai/v1/responses", self.payload(input=[{"type": "input_image", "image_url": "https://example.com"}]))
        self.policy.started -= 1000
        with self.assertRaisesRegex(proxy.Denied, "deadline"):
            self.policy.prepare("/openai/v1/responses", self.payload())

    def test_claude_premium_and_remote_tools_rejected(self):
        config = copy.deepcopy(CONFIG)
        config["author_models"]["claude"] = "synthetic-test-model"
        config["author_pricing_usd_per_million"]["claude"] = {"input": 1, "output": 1}
        broker = proxy.BrokerPolicy(proxy.author_policy(config, "claude"))
        for change in ({"speed": "fast"}, {"service_tier": "auto"}, {"tools": [{"type": "web_search_20250305", "name": "web_search"}]}):
            payload = {"model": "synthetic-test-model", "messages": [], "max_tokens": 100, **change}
            with self.assertRaises(proxy.Denied):
                broker.prepare("/anthropic/v1/messages", json.dumps(payload).encode())


class LauncherTests(unittest.TestCase):
    def test_candidate_modules_and_canonical_inputs_share_root(self):
        self.assertEqual(Path(clients.__file__).resolve().parents[2], REPO)
        self.assertEqual(Path(proxy.__file__).resolve().parents[2], REPO)

    def test_codex_worker_routes_through_broker_when_project_provider_keys_are_ignored(self):
        for interactive in (False, True):
            with self.subTest(interactive=interactive):
                args = clients.worker_arguments("codex", "gpt-6-astra", interactive)
                overrides = [args[i + 1] for i, arg in enumerate(args) if arg == "-c"]
                config = tomllib.loads("\n".join(overrides))
                self.assertEqual(config.get("model_provider"), "factory")
                provider = config["model_providers"]["factory"]
                self.assertEqual(provider["base_url"], "http://credential-proxy:8080/openai/v1")
                self.assertEqual(provider["env_key"], "FACTORY_PROXY_TOKEN")
                self.assertFalse(provider["requires_openai_auth"])
                self.assertFalse(provider["supports_websockets"])
                self.assertEqual(provider["wire_api"], "responses")
                self.assertFalse(provider["capabilities"]["external_web_access"])
                self.assertEqual(provider["capabilities"]["remote_compaction"], "unsupported")
                self.assertEqual(provider["request_max_retries"], 0)
                self.assertEqual(provider["stream_max_retries"], 0)

    def test_headless_codex_can_read_the_launchers_disposable_trust_config(self):
        self.assertNotIn("--ignore-user-config", clients.worker_arguments("codex", "gpt-6-astra"))

    def test_disposable_trust_does_not_import_or_overwrite_user_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            clients.initialize_codex_trust(home, Path("/work"))
            path = home / "config.toml"
            self.assertEqual(tomllib.loads(path.read_text()), {"projects": {"/work": {"trust_level": "trusted"}}})
            before = path.read_bytes()
            with self.assertRaises(FileExistsError):
                clients.initialize_codex_trust(home, Path("/other"))
            self.assertEqual(path.read_bytes(), before)
            path.unlink()
            target = home / "existing-personal-config"
            target.write_text("do not change")
            path.symlink_to(target)
            with self.assertRaises(FileExistsError):
                clients.initialize_codex_trust(home, Path("/work"))
            self.assertEqual(target.read_text(), "do not change")

    def test_standard_npm_lock_matches_reviewed_cli_versions(self):
        package = json.loads((REPO / "factory/package.json").read_text())
        lock = json.loads((REPO / "factory/package-lock.json").read_text())
        self.assertEqual(package["dependencies"], lock["packages"][""]["dependencies"])
        self.assertEqual(package["dependencies"]["@openai/codex"], clients.VERSIONS["codex"].split()[1])
        self.assertEqual(package["dependencies"]["@anthropic-ai/claude-code"], clients.VERSIONS["claude"].split()[0])
        self.assertTrue(all(item["integrity"].startswith("sha512-") for key, item in lock["packages"].items() if key))

    def test_native_discovery_requires_canonical_project_skills_and_config(self):
        skills = {"data": [{"cwd": "/work", "errors": [], "skills": [{"name": name, "enabled": True, "scope": "repo", "path": f"/work/.agents/skills/{name}/SKILL.md"} for name in clients.SKILLS]}]}
        config = {"config": {"model_provider": "factory", "agents": {"factory_author": {}, "factory_senior_reviewer": {}}, "mcp_servers": {"context7": {}, "openai_docs": {}}}}
        self.assertEqual(clients.inspect_codex_discovery(skills, config)["status"], "passed")
        config["config"]["model_provider"] = "organization-required-provider"
        with self.assertRaisesRegex(clients.ClientError, "administrator"):
            clients.inspect_codex_discovery(skills, config)
        config["config"]["model_provider"] = "factory"
        skills["data"][0]["skills"][0]["path"] = "/tmp/unreviewed/SKILL.md"
        with self.assertRaisesRegex(clients.ClientError, "canonical"):
            clients.inspect_codex_discovery(skills, config)

    def test_boundary_probe_detects_read_escape_and_writable_control(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "work"
            project.mkdir()
            (project / ".factory-smoke-readable").write_text("factory smoke positive control\n")
            (project / "AGENTS.md").write_text("unchanged")
            outside = root / "harmless-canary"
            outside.write_text("harmless")
            (project / ".factory-smoke-outside-link").symlink_to(outside)
            with self.assertRaisesRegex(clients.ClientError, "canary was readable"):
                clients.boundary_probe(project, outside)
            outside.unlink()
            with self.assertRaisesRegex(clients.ClientError, "instructions are writable"):
                clients.boundary_probe(project, outside)
            self.assertEqual((project / "AGENTS.md").read_text(), "unchanged")

    def test_sonnet_author_accepts_standard_client_tools_with_explicit_prices(self):
        config = copy.deepcopy(CONFIG)
        config["author_models"]["claude"] = "claude-sonnet-5-5"
        config["author_pricing_usd_per_million"]["claude"] = {"input": 2, "output": 10}
        broker = proxy.BrokerPolicy(proxy.author_policy(config, "claude"))
        payload = {"model": "claude-sonnet-5-5", "messages": [{"role": "user", "content": "test"}], "max_tokens": 100, "thinking": {"type": "adaptive"}, "tools": [{"name": "Read", "input_schema": {"type": "object"}}]}
        url, _, kind = broker.prepare("/anthropic/v1/messages", json.dumps(payload).encode())
        self.assertEqual(url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(kind, "claude")
        self.assertEqual(broker.policy["max_cost"], 5)

    def test_preflight_discovers_both_documentation_servers_before_inference(self):
        seen = []
        def respond(request, **kwargs):
            value = json.loads(request.data)
            seen.append((request.full_url, value["method"]))
            if value["method"] == "initialize":
                result = {"protocolVersion": "2025-03-26"}
            elif value["method"] == "tools/list":
                names = ("resolve-library-id", "query-docs") if "/context7/" in request.full_url else ("search_openai_docs", "list_openai_docs", "fetch_openai_doc", "get_openapi_spec")
                result = {"tools": [{"name": name} for name in names]}
            else:
                result = {}
            response = mock.MagicMock()
            response.__enter__.return_value = response
            response.headers = {"Content-Type": "application/json"}
            response.read.return_value = json.dumps({"id": value.get("id"), "result": result}).encode()
            return response
        opener = mock.Mock()
        opener.open.side_effect = respond
        with mock.patch.object(clients.urllib.request, "build_opener", return_value=opener):
            clients.probe_documentation("test-job-token")
        self.assertEqual([method for _, method in seen], ["initialize", "notifications/initialized", "tools/list"] * 2)
        self.assertEqual({url for url, _ in seen}, {"http://credential-proxy:8080/context7/mcp", "http://credential-proxy:8080/openai-docs/mcp"})

    def test_final_report_omits_reasoning_and_keeps_dispute(self):
        output = b'\n'.join(json.dumps(event).encode() for event in [
            {"type": "item.completed", "item": {"type": "reasoning", "text": "PRIVATE DO NOT PUBLISH"}},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Disputed R1: test proves the proposed change would regress behavior."}},
            {"type": "turn.completed", "usage": {"output_tokens": 42}},
        ])
        report, truncated = clients.final_report("codex", output)
        self.assertIn("Disputed R1", report)
        self.assertNotIn("PRIVATE", report)
        self.assertFalse(truncated)
        report, _ = clients.final_report("claude", b'{"result":"No patch: requirement conflicts with approved scope.","is_error":false}')
        self.assertIn("No patch", report)

    def test_report_bounds_errors_and_nontext(self):
        report, truncated = clients.final_report("claude", json.dumps({"result": "ä" * 8000}).encode())
        self.assertLess(len(report.encode()), 8192)
        self.assertTrue(truncated)
        for output in (b'{"result":null}', b'{"result":"failure","is_error":true}', b'{"result":"bad\\u001b[0m"}'):
            with self.assertRaises(clients.ClientError):
                clients.final_report("claude", output)

    def test_native_flags_fresh_sessions_and_explicit_sources(self):
        codex = clients.worker_arguments("codex", "gpt-6-astra")
        self.assertIn("--ephemeral", codex)
        self.assertNotIn("--ignore-user-config", codex)
        self.assertNotIn("--ignore-rules", codex)
        self.assertNotIn("resume", codex)
        claude = clients.worker_arguments("claude", "example-model")
        self.assertIn("--no-session-persistence", claude)
        self.assertIn("--strict-mcp-config", claude)
        self.assertIn("project", claude)
        self.assertIn("mcp__openai_docs__fetch_openai_doc", claude[claude.index("--allowedTools") + 1])
        self.assertNotIn("--bare", claude)

    def test_process_environment_does_not_inherit_secrets(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic", "GH_TOKEN": "synthetic", "ANTHROPIC_API_KEY": "synthetic"}):
            env = clients.clean_env(Path("/tmp/empty-docker-config"))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)

    def test_worker_container_flags(self):
        flags = clients.container_flags("test", worker=True)
        self.assertIn("--read-only", flags)
        self.assertIn("--cap-drop=ALL", flags)
        self.assertIn("--security-opt=no-new-privileges", flags)
        self.assertIn("127.0.0.1", flags)
        self.assertFalse(any("docker.sock" in flag for flag in flags))


if __name__ == "__main__":
    unittest.main()
