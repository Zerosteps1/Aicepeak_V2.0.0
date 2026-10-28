"""Local reviewer boundaries: tool-less Codex session, authenticated receipts, publication."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import threading
import http.server
import signal
import time
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import local_review
from contracts import Blocked
from test_local_review_queue import QueueTransport, reviewer as reviewer_metadata
import local_review_queue as queue


def review_for(snapshot, outcome='changes_requested'):
    findings = [{'id': 'F-1', 'kind': 'defect', 'confidence': 'high', 'priority': 'P1', 'file': 'example.txt', 'line': 1, 'impact': 'i', 'evidence': 'e',
                 'requirement': 'r', 'minimal_fix': 'm', 'verification': 'v'}] if outcome == 'changes_requested' else []
    binding = {k: snapshot[k] for k in ('repository', 'pr', 'head_sha', 'base_sha', 'policy_sha', 'run_id', 'run_attempt')}
    return {**binding, 'model': 'gpt-6-astra', 'effort': 'high', 'scope': ['example.txt'], 'evidence': [],
            'limitations': [], 'complete': True, 'outcome': outcome, 'summary': 's', 'findings': findings}


TOOL_ITEM = {'type': 'additional_tools', 'role': 'developer', 'tools': [{'type': 'namespace', 'name': 'functions', 'tools': [
    {'type': 'function', 'name': 'exec', 'description': 'Run JavaScript. declare const tools: { read_mcp_resource(args: {}): Promise<unknown> }'},
    {'type': 'function', 'name': 'wait', 'description': 'Waits on a yielded exec cell.'}]}]}


class ToolLessSession(unittest.TestCase):
    def test_codex_arguments_disable_tools_and_user_state(self):
        args = local_review.codex_arguments(Path('/r/schema.json'), Path('/r/out.json'), Path('/r/work'), Path('/r/catalog.json'), 'policy')
        self.assertEqual(args[:2], ['codex', 'exec'])
        for flag in ('--ephemeral', '--ignore-user-config', '--ignore-rules', '--strict-config', '--skip-git-repo-check', '--json'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
        self.assertEqual(args[args.index('--output-schema') + 1], '/r/schema.json')
        overrides = [args[i + 1] for i, arg in enumerate(args) if arg == '-c']
        for expected in ('agents.enabled=false', 'model_catalog_json="/r/catalog.json"', 'web_search="disabled"',
                         'project_doc_max_bytes=0', 'model_reasoning_effort="high"', 'approval_policy="never"'):
            self.assertIn(expected, overrides)
        for feature in local_review.TOOL_FEATURES:
            self.assertIn(f'features.{feature}=false', overrides)
        self.assertEqual(args[-1], '-')
        self.assertFalse(any('dangerously' in arg for arg in args))

    def test_child_environment_holds_only_the_access_token_and_fresh_homes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'OPENAI_API_KEY': 'x', 'GH_TOKEN': 'x', 'FACTORY_PUBLISHER_APP_PRIVATE_KEY': 'x'}):
            env = local_review.child_env(Path(tmp), 'workspace-token')
        self.assertEqual(set(env), {'PATH', 'HOME', 'CODEX_HOME', 'TMPDIR', 'CODEX_ACCESS_TOKEN'})
        self.assertTrue(env['HOME'].startswith(tmp) and env['CODEX_HOME'].startswith(tmp))

    def test_reviewer_catalog_removes_shell_and_patch_tools(self):
        catalog = {'models': [{'slug': 'other'}, {'slug': 'gpt-6-astra', 'shell_type': 'unified_exec', 'apply_patch_tool_type': 'freeform',
                                                  'experimental_supported_tools': ['clock'], 'context_window': 272000}]}
        result = local_review.reviewer_catalog(catalog)
        self.assertEqual(result, {'models': [{'slug': 'gpt-6-astra', 'shell_type': 'disabled', 'apply_patch_tool_type': None,
                                              'experimental_supported_tools': [], 'context_window': 272000}]})
        with self.assertRaisesRegex(Blocked, 'gpt-6-astra'):
            local_review.reviewer_catalog({'models': [{'slug': 'other'}]})

    def test_tool_surface_preflight_allows_only_the_isolated_script_tool(self):
        local_review.check_tool_surface([{'type': 'message'}, TOOL_ITEM])
        shell = json.loads(json.dumps(TOOL_ITEM))
        shell['tools'][0]['tools'][0]['description'] += ' declare const tools: { exec_command(args: {}): Promise<unknown> }'
        agents = json.loads(json.dumps(TOOL_ITEM))
        agents['tools'].append({'type': 'namespace', 'name': 'collaboration', 'tools': [{'type': 'function', 'name': 'spawn_agent'}]})
        for items in ([shell], [agents], [{'type': 'additional_tools', 'tools': [{'type': 'web_search'}]}], [{'type': 'message'}], [TOOL_ITEM, TOOL_ITEM]):
            with self.subTest(items=items), self.assertRaisesRegex(Blocked, 'tool'):
                local_review.check_tool_surface(items)

    def test_code_mode_host_stays_disabled(self):
        # The JavaScript exec tool remains visible; with its host disabled every call fails closed.
        self.assertIn('code_mode_host', local_review.TOOL_FEATURES)

    @unittest.skipUnless(shutil.which('codex') and subprocess.run(['codex', '--version'], capture_output=True, text=True).stdout.strip() == local_review.CODEX_VERSION,
                         'needs the pinned Codex CLI')
    def test_reviewer_session_cannot_execute_code_requested_by_the_model(self):
        """A fake model asks the real CLI to read a file outside the workspace through code-mode exec."""
        tmp = Path(tempfile.mkdtemp(prefix='reviewer-exec-'))
        self.addCleanup(shutil.rmtree, tmp, True)
        canary = tmp / 'outside' / 'canary.txt'
        canary.parent.mkdir()
        canary.write_text('CANARY-7f3a9')
        requests = []
        script = f'const r = await tools.exec_command({{cmd: "cat {canary}"}}); text(JSON.stringify(r));'

        class Model(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(404)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                item = ({'type': 'custom_tool_call', 'id': 'ctc_1', 'call_id': 'call_1', 'name': 'exec', 'namespace': 'functions', 'input': script, 'status': 'completed'}
                        if len(requests) == 1 else
                        {'type': 'message', 'id': 'msg_1', 'role': 'assistant', 'status': 'completed', 'content': [{'type': 'output_text', 'text': '{"status":"OK"}', 'annotations': []}]})
                usage = {'input_tokens': 1, 'input_tokens_details': {'cached_tokens': 0}, 'output_tokens': 1, 'output_tokens_details': {'reasoning_tokens': 0}, 'total_tokens': 2}
                events = [{'type': 'response.created', 'response': {'id': 'r'}}, {'type': 'response.output_item.done', 'output_index': 0, 'item': item},
                          {'type': 'response.completed', 'response': {'id': 'r', 'usage': usage}}]
                payload = b''.join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Model)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        env = local_review.child_env(tmp, 'unused')
        env.pop('CODEX_ACCESS_TOKEN')
        models = subprocess.run(['codex', 'debug', 'models'], env=env, cwd=tmp / 'work', capture_output=True, timeout=60)
        catalog = tmp / 'catalog.json'
        catalog.write_text(json.dumps(local_review.reviewer_catalog(json.loads(models.stdout))))
        schema = tmp / 'schema.json'
        schema.write_text(json.dumps({'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['OK']}}, 'required': ['status'], 'additionalProperties': False}))
        provider = ['model_provider="fake"', 'model_providers.fake.name="fake"', f'model_providers.fake.base_url="http://127.0.0.1:{server.server_address[1]}/v1"',
                    'model_providers.fake.wire_api="responses"', 'model_providers.fake.requires_openai_auth=false', 'model_providers.fake.supports_websockets=false',
                    'model_providers.fake.request_max_retries=0', 'model_providers.fake.stream_max_retries=0']
        args = local_review.codex_arguments(schema, tmp / 'out.json', tmp / 'work', catalog, 'Return only the schema.')
        args = args[:-1] + [value for override in provider for value in ('-c', override)] + ['-']
        result = subprocess.run(args, input=b'Return status OK.', env=env, cwd=tmp / 'work', capture_output=True, timeout=120)
        self.assertEqual(len(requests), 2, result.stderr[-500:])
        self.assertNotIn(b'CANARY-7f3a9', requests[1])
        self.assertIn(b'code-mode host is disabled', requests[1])

    def test_events_count_usage_and_reject_any_tool_use(self):
        lines = [{'type': 'thread.started', 'thread_id': 't-1'}, {'type': 'item.completed', 'item': {'type': 'error', 'message': 'notice'}},
                 {'type': 'error', 'message': 'Reconnecting... 2/5'}, {'type': 'item.completed', 'item': {'type': 'reasoning'}},
                 {'type': 'item.completed', 'item': {'type': 'agent_message'}},
                 {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'cached_input_tokens': 4, 'output_tokens': 3}}]
        raw = '\n'.join(json.dumps(line) for line in lines).encode()
        self.assertEqual(local_review.parse_events(raw), {'thread_id': 't-1', 'turns': 1, 'usage': {'input_tokens': 10, 'cached_input_tokens': 4, 'output_tokens': 3}})
        for event in ({'type': 'item.started', 'item': {'type': 'command_execution'}}, {'type': 'item.completed', 'item': {'type': 'mcp_tool_call'}},
                      {'type': 'item.completed', 'item': {'type': 'something_new'}}):
            with self.subTest(event=event), self.assertRaisesRegex(Blocked, 'tool'):
                local_review.parse_events(json.dumps(event).encode())
        with self.assertRaisesRegex(Blocked, 'turn failed'):
            local_review.parse_events(json.dumps({'type': 'turn.failed', 'error': {'message': 'usage limit'}}).encode())


class ActiveCancellation(unittest.TestCase):
    def run_child(self, source, freshness, timeout=2):
        with tempfile.TemporaryDirectory() as directory:
            env = local_review.child_env(Path(directory), 'fake-review-seat-token')
            return local_review.run_review_process([sys.executable, '-c', source], b'review material',
                env=env, cwd=directory, timeout=timeout, freshness=freshness)

    def test_stale_before_start_never_spawns_a_model(self):
        with patch.object(local_review.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(Blocked, 'stale head'):
                self.run_child('raise SystemExit(99)', lambda: (_ for _ in ()).throw(Blocked('stale head')))
        spawn.assert_not_called()

    def test_completed_child_output_and_minimal_environment_are_preserved(self):
        checks = []
        source = "import json,os,sys; print(json.dumps(dict(os.environ))); print(sys.stdin.read(), file=sys.stderr)"
        result = self.run_child(source, lambda: checks.append('current'))
        self.assertEqual(result.returncode, 0)
        env = json.loads(result.stdout)
        # Python/macOS add locale metadata after process startup.
        self.assertEqual(set(env) - {'LC_CTYPE', '__CF_USER_TEXT_ENCODING'}, {'PATH', 'HOME', 'CODEX_HOME', 'TMPDIR', 'CODEX_ACCESS_TOKEN'})
        self.assertEqual(env['CODEX_ACCESS_TOKEN'], 'fake-review-seat-token')
        self.assertEqual(result.stderr, b'review material\n')
        self.assertGreaterEqual(len(checks), 2)

    def test_new_head_kills_a_waiting_real_child_before_it_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            completed = Path(directory) / 'completed'
            checks = []
            source = ("import os,pathlib,time; pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid())); "
                      "time.sleep(30); pathlib.Path(" + repr(str(completed)) + ").write_text('too late')")

            def fresh():
                checks.append('poll')
                if pidfile.exists():
                    raise Blocked('stale head')

            started = time.monotonic()
            with patch.object(local_review, 'REVIEW_POLL_SECONDS', 0.05):
                with self.assertRaisesRegex(Blocked, 'stale head'):
                    self.run_child(source, fresh)
            self.assertLess(time.monotonic() - started, 3)
            self.assertFalse(completed.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)
            self.assertGreaterEqual(len(checks), 2)

    def test_deadline_kills_a_real_process_tree_including_a_term_ignoring_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'pids.json'
            grandchild = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
            source = ("import json,os,pathlib,signal,subprocess,sys,time; "
                      "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                      "child=subprocess.Popen([sys.executable,'-c'," + repr(grandchild) + "]); "
                      "pathlib.Path(" + repr(str(pidfile)) + ").write_text(json.dumps([os.getpid(),child.pid])); time.sleep(30)")
            started = time.monotonic()
            with patch.object(local_review, 'REVIEW_POLL_SECONDS', 0.05), \
                    patch.object(local_review, 'REVIEW_TERMINATE_SECONDS', 0.1):
                with self.assertRaisesRegex(Blocked, 'deadline'):
                    self.run_child(source, lambda: None, timeout=0.3)
            self.assertLess(time.monotonic() - started, 3)
            pids = json.loads(pidfile.read_text())
            for pid in pids:
                for _ in range(30):
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.02)
                else:
                    self.fail(f'reviewer descendant {pid} survived cancellation')

    def test_nonzero_parent_exit_also_kills_its_remaining_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            child = "import time; time.sleep(30)"
            source = ("import pathlib,subprocess,sys; child=subprocess.Popen([sys.executable,'-c'," + repr(child)
                      + "],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); pathlib.Path(" + repr(str(pidfile))
                      + ").write_text(str(child.pid)); sys.exit(3)")
            result = self.run_child(source, lambda: None)
            self.assertEqual(result.returncode, 3)
            pid = int(pidfile.read_text())
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail('child survived failed reviewer process')

    def test_successful_parent_exit_also_cleans_up_its_child(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            source = ("import pathlib,subprocess,sys; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],"
                      "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); pathlib.Path(" + repr(str(pidfile))
                      + ").write_text(str(child.pid))")
            result = self.run_child(source, lambda: None)
            self.assertEqual(result.returncode, 0)
            pid = int(pidfile.read_text())
            for _ in range(30):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.02)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail('child survived successful reviewer process')

    def test_cleanup_preserves_an_unrelated_child_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'unrelated-exited'
            other = subprocess.Popen([sys.executable, '-c',
                'import pathlib,sys; pathlib.Path(' + repr(str(marker)) + ').write_text("exiting"); sys.exit(17)'])
            try:
                for _ in range(200):
                    if marker.exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                time.sleep(0.05)
                self.assertEqual(self.run_child('pass', lambda: None).returncode, 0)
                self.assertEqual(other.wait(timeout=5), 17)
            finally:
                if other.poll() is None:
                    other.kill()
                    other.wait(timeout=5)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux kernel child-subreaper state')
    def test_linux_subreaper_state_is_restored_and_overlap_rejected(self):
        import ctypes
        prctl = ctypes.CDLL(None).prctl
        prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
        def state():
            value = ctypes.c_int()
            self.assertEqual(prctl(37, ctypes.addressof(value), 0, 0, 0), 0)
            return value.value
        original = state()
        try:
            for prior in (0, 1):
                self.assertEqual(prctl(36, prior, 0, 0, 0), 0)
                with self.assertRaisesRegex(RuntimeError, 'scope fixture'):
                    with local_review.review_child_scope():
                        self.assertEqual(state(), 1)
                        with self.assertRaisesRegex(Blocked, 'already supervised'):
                            with local_review.review_child_scope():
                                self.fail('overlapping scope was admitted')
                        self.assertEqual(state(), 1)
                        raise RuntimeError('scope fixture')
                self.assertEqual(state(), prior)
        finally:
            self.assertEqual(prctl(36, original, 0, 0, 0), 0)

    def test_controller_sigterm_reaches_the_separate_reviewer_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            child = "import os,pathlib,time; pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid())); time.sleep(30)"
            wrapper = ("import pathlib,sys; sys.path.insert(0," + repr(str(Path(local_review.__file__).parent)) + ")\n"
                       "import local_review\ntry:\n local_review.run_review_process([sys.executable,'-c'," + repr(child) + "], b'', "
                       "env=local_review.child_env(pathlib.Path(" + repr(directory) + "),'fake-token'), "
                       "cwd=" + repr(directory) + ", timeout=30, freshness=lambda: None)\n"
                       "except local_review.Blocked:\n print('BLOCKED: cancelled',file=sys.stderr); sys.exit(1)\n")
            process = subprocess.Popen([sys.executable, '-c', wrapper], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(200):
                    if pidfile.exists():
                        break
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists(), 'wrapper did not start the reviewer')
                process.terminate()
                _, stderr = process.communicate(timeout=5)
                self.assertNotEqual(process.returncode, 0)
                self.assertNotIn(b'fake-token', stderr)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(pidfile.read_text()), 0)
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=2)

    def test_stalled_freshness_check_is_bounded_and_stops_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            release = threading.Event()
            self.addCleanup(release.set)
            source = "import os,pathlib,time; pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid())); time.sleep(30)"

            def fresh():
                if pidfile.exists():
                    release.wait(10)

            started = time.monotonic()
            with patch.object(local_review, 'REVIEW_POLL_SECONDS', 0.05):
                with self.assertRaisesRegex(Blocked, 'freshness check timed out'):
                    self.run_child(source, fresh)
            self.assertLess(time.monotonic() - started, 3)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)
            release.set()


class Secrets(unittest.TestCase):
    def test_environment_wins_then_keychain_with_base64_multiline_value(self):
        with patch.dict(os.environ, {'CODEX_ACCESS_TOKEN': 'from-env'}):
            self.assertEqual(local_review.secret('CODEX_ACCESS_TOKEN'), 'from-env')
        # This exercises multiline transport; key validity belongs to App authentication.
        fixture = 'not-a-key first line\nnot-a-key second line\n'
        found = subprocess.CompletedProcess([], 0, stdout=base64.b64encode(fixture.encode()).decode() + '\n')
        with patch.dict(os.environ, {}, clear=True), patch.object(local_review.sys, 'platform', 'darwin'), \
                patch.object(local_review.subprocess, 'run', return_value=found) as run:
            self.assertEqual(local_review.secret('FACTORY_PUBLISHER_APP_PRIVATE_KEY'), fixture)
        self.assertIn(local_review.KEYCHAIN['FACTORY_PUBLISHER_APP_PRIVATE_KEY'], run.call_args.args[0])
        missing = subprocess.CompletedProcess([], 44, stdout='')
        with patch.dict(os.environ, {}, clear=True), patch.object(local_review.sys, 'platform', 'darwin'), \
                patch.object(local_review.subprocess, 'run', return_value=missing):
            with self.assertRaisesRegex(Blocked, local_review.KEYCHAIN['CODEX_ACCESS_TOKEN']):
                local_review.secret('CODEX_ACCESS_TOKEN')


class TrustedCheckout(unittest.TestCase):
    def test_reviewer_runs_only_from_the_clean_policy_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-C', tmp, *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            (Path(tmp) / 'policy.md').write_text('policy\n')
            git('add', 'policy.md')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
            head = git('rev-parse', 'HEAD')
            with patch.object(local_review, 'ROOT', Path(tmp)):
                local_review.require_trusted_checkout(head)
                with self.assertRaisesRegex(Blocked, 'policy revision'):
                    local_review.require_trusted_checkout('f' * 40)
                (Path(tmp) / 'policy.md').write_text('edited\n')
                with self.assertRaisesRegex(Blocked, 'policy revision'):
                    local_review.require_trusted_checkout(head)


class Publication(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'factory/config.json').read_text())
        self.config.update(repository='fixture/repo', publisher_app_id=7, automatic_correction=False, maintainers=[{'id': 1, 'login': 'test-human'}])
        self.transport = QueueTransport(self.config)
        self.next_run = 100
        dispatcher = patch.object(local_review, 'dispatch_review', side_effect=self.dispatch)
        dispatcher.start()
        self.addCleanup(dispatcher.stop)
        env = patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'FACTORY_RETRY': 'false'})
        env.start()
        self.addCleanup(env.stop)

    def dispatch(self, config, pr, check_id, claim_id, result_id=0):
        run_id = self.next_run
        self.next_run += 1
        self.transport.add_run(run_id)
        with patch.dict(os.environ, {'GITHUB_RUN_ID': str(run_id)}):
            return queue.coordinate(self.transport, config, pr, check_id, claim_id, result_id)

    def claim(self, snapshot):
        self.dispatch(self.config, 1, snapshot['check_id'], '1' * 32)
        return queue.verified_gate(self.transport, 1, snapshot['check_id'], self.config)

    def pending(self, head='a' * 40, tests_ok=True, run_id=1):
        self.transport.add_run(run_id, ['Snapshot', 'Deterministic tests', 'Publish gates'])
        self.transport.pr['head']['sha'] = head
        os.environ['GITHUB_RUN_ID'] = str(run_id)
        captured = {}
        with patch.object(engine, 'installation', return_value=self.transport), \
                patch.object(engine, 'emit', side_effect=lambda name, value: captured.update({name: value})):
            engine.snapshot_stage(argparse.Namespace(pr=1, feedback_kind='', feedback_id=0), self.config)
        snapshot = captured['snapshot']
        tests = {'repository': 'fixture/repo', 'head_sha': head, 'policy_sha': 'b' * 40, 'run_id': run_id, 'ok': tests_ok, 'exit_code': 0 if tests_ok else 1, 'summary': 'ok'}
        with patch.dict(os.environ, {'SNAPSHOT_JSON': json.dumps(snapshot), 'TESTS_JSON': json.dumps(tests), 'TEST_JOB_RESULT': 'success' if tests_ok else 'failure'}), \
                patch.object(engine, 'installation', return_value=self.transport), patch.object(engine, 'verify_run'):
            engine.publish_stage(self.config)
        return snapshot

    def test_pending_review_requires_an_authentic_publisher_receipt(self):
        snapshot = self.pending()
        check, record = local_review.pending_review(self.transport, 1, self.config)
        self.assertEqual((check['id'], record['phase'], record['snapshot']), (snapshot['check_id'], 'awaiting_review', snapshot))
        self.transport.checks[snapshot['check_id']]['external_id'] = 'fixture/repo:1:forged'
        with self.assertRaisesRegex(Blocked, 'unauthenticated'):
            local_review.pending_review(self.transport, 1, self.config)
        self.transport.checks[snapshot['check_id']]['external_id'] = engine.bind(snapshot)
        self.transport.checks[snapshot['check_id']]['status'] = 'completed'
        with self.assertRaisesRegex(Blocked, 'no senior review awaiting'):
            local_review.pending_review(self.transport, 1, self.config)

    def test_local_result_never_writes_the_senior_gate(self):
        snapshot = self.pending()
        check, record = self.claim(snapshot)
        self.transport.calls.clear()
        result_id = local_review.submit_result(self.transport, self.config, check, record,
                                              review_for(snapshot, 'pass'), reviewer_metadata(), dispatch=False)
        writes = [c for c in self.transport.calls if c[0] == 'PATCH']
        self.assertEqual(writes, [], 'local reviewer must never mutate the shared senior gate')
        self.assertEqual(self.transport.checks[result_id]['conclusion'], 'neutral')
        self.assertEqual(self.transport.checks[check['id']]['status'], 'in_progress')

    def test_published_review_feeds_the_correction_gate(self):
        snapshot = self.pending()
        check, record = self.claim(snapshot)
        reviewer = reviewer_metadata()
        with patch.object(local_review.subprocess, 'run') as run:
            outcome = local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot), reviewer, dispatch=True)
        self.assertEqual(outcome, 'changes_requested')
        run.assert_not_called()  # automatic_correction is false during the shadow phase
        published = self.transport.checks[snapshot['check_id']]
        saved = json.loads(published['output']['text'])
        self.assertEqual((published['status'], published['conclusion'], saved['phase'], saved['reviewer']), ('completed', 'failure', 'completed', reviewer))
        self.assertIn('needs-author-action', self.transport.comments[-1]['body'])
        self.config['automatic_correction'] = True
        self.transport.runs[2] = {'triggering_actor': {'type': 'User', 'id': 1}}
        captured = {}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': '2'}), patch.object(engine, 'installation', return_value=self.transport), \
                patch.object(engine, 'emit', side_effect=lambda name, value: captured.update({name: value})):
            engine.correction_stage(argparse.Namespace(pr=1, check_id=snapshot['check_id']), self.config)
        self.assertTrue(captured['author']['enabled'])

    def test_changes_requested_dispatches_correction_only_when_enabled(self):
        self.config['automatic_correction'] = True
        snapshot = self.pending()
        check, record = self.claim(snapshot)
        with patch.object(local_review.subprocess, 'run') as run:
            local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot), reviewer_metadata(), dispatch=True)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'workflow', 'run'])
        self.assertIn(f"correction={snapshot['check_id']}", command)
        self.assertIn('--ref', command)

    def test_stale_pending_review_cannot_write_a_verdict(self):
        snapshot = self.pending()
        check, record = self.claim(snapshot)
        self.transport.pr['head']['sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'stale'):
            local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot), reviewer_metadata(), dispatch=False)
        closed = self.transport.checks[snapshot['check_id']]
        self.assertEqual(closed['status'], 'in_progress')
        self.assertNotEqual(closed.get('conclusion'), 'success')
        self.assertIsNone(json.loads(closed['output']['text'])['review'])

    def test_review_limit_protects_the_seat_window(self):
        snapshot = self.pending()
        self.config['limits']['max_reviews_per_pr'] = 1
        check, record = self.claim(snapshot)
        local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot, 'pass'), reviewer_metadata(), dispatch=False)
        with self.assertRaisesRegex(Blocked, 'review limit'):
            local_review.require_review_budget(self.transport, 1, self.config)

    def test_previous_findings_survive_a_head_that_failed_its_tests(self):
        first = self.pending()
        check, record = self.claim(first)
        local_review.publish_review(self.transport, self.config, check, record, review_for(first), reviewer_metadata(), dispatch=False)
        self.pending(head='c' * 40, tests_ok=False, run_id=2)  # completes its check without a review
        latest = self.pending(head='d' * 40, run_id=3)
        material = engine.review_material(self.transport, latest, self.config, {})
        previous = material.split('PREVIOUS FINDINGS: re-check fixes at this head\n', 1)[1].split('\n\n', 1)[0]
        self.assertEqual(json.loads(previous)['findings'][0]['id'], 'F-1')

    def test_publish_comment_does_not_repeat_candidate_test_output(self):
        self.pending()
        self.assertNotIn('ok', self.transport.comments[-1]['body'].split('\n\n')[1:2])

    def test_review_pr_builds_material_and_publishes_schema_valid_result(self):
        snapshot = self.pending()
        prompts = []

        def fake_codex(instructions, material, schema_path, config, freshness=None):
            freshness()
            prompts.append((instructions, material))
            return review_for(snapshot, 'pass'), {'thread_id': 't', 'turns': 1, 'usage': {}}
        with patch.object(local_review, 'require_trusted_checkout'), patch.object(local_review, 'run_codex', side_effect=fake_codex):
            outcome = local_review.review_pr(self.transport, 1, self.config, dispatch=False, dry_run=False)
        self.assertEqual(outcome, 'pass')
        self.assertIn('APPROVED WORK ORDER', prompts[0][1])
        self.assertIn('trusted_test_evidence', prompts[0][1])
        self.assertEqual(self.transport.checks[snapshot['check_id']]['conclusion'], 'success')


if __name__ == '__main__':
    unittest.main()
