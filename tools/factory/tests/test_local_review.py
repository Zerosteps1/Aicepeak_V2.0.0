"""Local reviewer boundaries: tool-less Codex session, authenticated receipts, publication."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import local_review
from contracts import Blocked
from test_engine import Transport


def review_for(snapshot, outcome='changes_requested'):
    findings = [{'id': 'F-1', 'priority': 'P1', 'file': 'example.txt', 'line': 1, 'impact': 'i', 'evidence': 'e',
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
        for items in ([shell], [agents], [{'type': 'additional_tools', 'tools': [{'type': 'web_search'}]}]):
            with self.subTest(items=items), self.assertRaisesRegex(Blocked, 'tool'):
                local_review.check_tool_surface(items)

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


class Secrets(unittest.TestCase):
    def test_environment_wins_then_keychain_with_base64_pem(self):
        with patch.dict(os.environ, {'CODEX_ACCESS_TOKEN': 'from-env'}):
            self.assertEqual(local_review.secret('CODEX_ACCESS_TOKEN'), 'from-env')
        pem = '-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\n'
        found = subprocess.CompletedProcess([], 0, stdout=base64.b64encode(pem.encode()).decode() + '\n')
        with patch.dict(os.environ, {}, clear=True), patch.object(local_review.sys, 'platform', 'darwin'), \
                patch.object(local_review.subprocess, 'run', return_value=found) as run:
            self.assertEqual(local_review.secret('FACTORY_PUBLISHER_APP_PRIVATE_KEY'), pem)
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
        self.config.update(repository='fixture/repo', publisher_app_id=7, maintainers=[{'id': 1, 'login': 'test-human'}])
        self.transport = Transport(self.config)
        env = patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'FACTORY_RETRY': 'false'})
        env.start()
        self.addCleanup(env.stop)

    def pending(self):
        captured = {}
        with patch.object(engine, 'installation', return_value=self.transport), \
                patch.object(engine, 'emit', side_effect=lambda name, value: captured.update({name: value})):
            engine.snapshot_stage(argparse.Namespace(pr=1, feedback_kind='', feedback_id=0), self.config)
        snapshot = captured['snapshot']
        tests = {'repository': 'fixture/repo', 'head_sha': 'a' * 40, 'policy_sha': 'b' * 40, 'run_id': 1, 'ok': True, 'exit_code': 0, 'summary': 'ok'}
        with patch.dict(os.environ, {'SNAPSHOT_JSON': json.dumps(snapshot), 'TESTS_JSON': json.dumps(tests), 'TEST_JOB_RESULT': 'success'}), \
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
        self.transport.checks[snapshot['check_id']]['status'] = 'completed'
        with self.assertRaisesRegex(Blocked, 'no senior review awaiting'):
            local_review.pending_review(self.transport, 1, self.config)

    def test_published_review_feeds_the_correction_gate(self):
        snapshot = self.pending()
        check, record = local_review.pending_review(self.transport, 1, self.config)
        reviewer = {'host': 'maintainer-local', 'turns': 1, 'usage': {'output_tokens': 3}}
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
        check, record = local_review.pending_review(self.transport, 1, self.config)
        with patch.object(local_review.subprocess, 'run') as run:
            local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot), {}, dispatch=True)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ['gh', 'workflow', 'run'])
        self.assertIn(f"correction={snapshot['check_id']}", command)
        self.assertIn('--ref', command)

    def test_stale_pending_review_is_closed_without_a_verdict(self):
        snapshot = self.pending()
        check, record = local_review.pending_review(self.transport, 1, self.config)
        self.transport.pr['head']['sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'stale'):
            local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot), {}, dispatch=False)
        closed = self.transport.checks[snapshot['check_id']]
        self.assertEqual((closed['status'], closed['conclusion']), ('completed', 'failure'))
        self.assertIsNone(json.loads(closed['output']['text'])['review'])

    def test_review_limit_protects_the_seat_window(self):
        snapshot = self.pending()
        self.config['limits']['max_reviews_per_pr'] = 1
        check, record = local_review.pending_review(self.transport, 1, self.config)
        local_review.publish_review(self.transport, self.config, check, record, review_for(snapshot, 'pass'), {'turns': 1}, dispatch=False)
        with self.assertRaisesRegex(Blocked, 'review limit'):
            local_review.require_review_budget(self.transport, 1, self.config)

    def test_review_pr_builds_material_and_publishes_schema_valid_result(self):
        snapshot = self.pending()
        prompts = []

        def fake_codex(instructions, material, schema_path, config):
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
