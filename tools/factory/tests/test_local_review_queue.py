"""Two devices share GitHub state; only the serialized trusted workflow publishes gates."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import local_review
import local_review_queue as queue
from contracts import Blocked
from test_engine import Transport


class QueueTransport(Transport):
    def __init__(self, config):
        super().__init__(config)
        self.jobs = {}
        self.add_run(1, ['Snapshot', 'Deterministic tests', 'Publish gates'])
        self.fail_final_patch = False

    def add_run(self, number, names=None):
        self.runs[number] = {'id': number, 'run_attempt': 1, 'repository': {'full_name': 'fixture/repo'},
                             'event': 'workflow_dispatch', 'head_sha': 'b' * 40, 'head_branch': 'main',
                             'workflow_id': 10, 'triggering_actor': {'type': 'User', 'id': 1, 'login': 'test-human'}}
        self.jobs[number] = [{'name': name, 'status': 'completed', 'conclusion': 'success'}
                             for name in (names or ['Review coordination'])]

    def request(self, method, path, data=None):
        if method == 'GET' and path == '/repos/fixture/repo/actions/workflows/10':
            return {'path': self.config['workflow']}
        if self.fail_final_patch and method == 'PATCH' and data.get('status') == 'completed':
            raise Blocked('transport lost before publication')
        return super().request(method, path, data)

    def pages(self, path, field=None):
        if '/jobs?' in path:
            return copy.deepcopy(self.jobs[int(path.split('/runs/')[1].split('/')[0])])
        return super().pages(path, field)


def review_for(snapshot, outcome='changes_requested'):
    findings = [{'id': 'F-1', 'kind': 'defect', 'confidence': 'high', 'priority': 'P1', 'file': 'example.txt', 'line': 1, 'impact': 'i', 'evidence': 'e',
                 'requirement': 'r', 'minimal_fix': 'm', 'verification': 'v'}] if outcome == 'changes_requested' else []
    return {**{k: snapshot[k] for k in ('repository', 'pr', 'head_sha', 'base_sha', 'policy_sha', 'run_id', 'run_attempt')},
            'model': 'gpt-6-astra', 'effort': 'high', 'scope': ['example.txt'], 'evidence': [], 'limitations': [],
            'complete': True, 'outcome': outcome, 'summary': 's', 'findings': findings}


def reviewer():
    return {**queue.REVIEWER_IDENTITY, 'thread_id': 'thread-1', 'turns': 1, 'usage': {'input_tokens': 10, 'output_tokens': 3}}


class Coordination(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'factory/config.json').read_text())
        self.config.update(repository='fixture/repo', publisher_app_id=7, maintainers=[{'id': 1, 'login': 'test-human'}])
        self.gh = QueueTransport(self.config)
        env = patch.dict(os.environ, {'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'FACTORY_RETRY': 'false'})
        env.start()
        self.addCleanup(env.stop)
        self.snapshot = self.pending()
        self.next_run = 2

    def pending(self, run_id=1, retry=False):
        self.gh.add_run(run_id, ['Snapshot', 'Deterministic tests', 'Publish gates'])
        captured = {}
        with patch.dict(os.environ, {'GITHUB_RUN_ID': str(run_id), 'FACTORY_RETRY': str(retry).lower()}), \
                patch.object(engine, 'installation', return_value=self.gh), \
                patch.object(engine, 'emit', side_effect=lambda name, value: captured.update({name: value})):
            engine.snapshot_stage(argparse.Namespace(pr=1, feedback_kind='', feedback_id=0), self.config)
            snapshot = captured['snapshot']
            tests = {'repository': 'fixture/repo', 'head_sha': snapshot['head_sha'], 'policy_sha': 'b' * 40,
                     'run_id': run_id, 'ok': True, 'exit_code': 0, 'summary': 'ok'}
            with patch.dict(os.environ, {'SNAPSHOT_JSON': json.dumps(snapshot), 'TESTS_JSON': json.dumps(tests), 'TEST_JOB_RESULT': 'success'}):
                engine.publish_stage(self.config)
        return snapshot

    def dispatch(self, config, pr, check_id, claim_id, result_id=0):
        run_id = self.next_run
        self.next_run += 1
        self.gh.add_run(run_id)
        with patch.dict(os.environ, {'GITHUB_RUN_ID': str(run_id)}):
            return queue.coordinate(self.gh, config, pr, check_id, claim_id, result_id)

    def claim(self, claim_id='1' * 32, snapshot=None):
        snapshot = snapshot or self.snapshot
        return self.dispatch(self.config, 1, snapshot['check_id'], claim_id)

    def result(self, outcome='changes_requested', claim_id='1' * 32, error='', dry_run=False):
        check, record = queue.verified_gate(self.gh, 1, self.snapshot['check_id'], self.config)
        return local_review.submit_result(self.gh, self.config, check, record,
                                         None if error else review_for(self.snapshot, outcome),
                                         {} if error else reviewer(), dispatch=False, error=error, dry_run=dry_run)

    def finalize(self, result_id, claim_id='1' * 32, snapshot=None):
        snapshot = snapshot or self.snapshot
        return self.dispatch(self.config, 1, snapshot['check_id'], claim_id, result_id)

    def record(self):
        return engine.receipt(self.gh.checks[self.snapshot['check_id']])

    def test_only_one_device_gets_the_claim_and_only_its_blocking_result_publishes(self):
        # Both devices saw the same awaiting check. Their workflow requests execute in PR order.
        self.claim()
        with self.assertRaisesRegex(Blocked, 'owned'):
            self.claim('2' * 32)
        result_id = self.result()
        self.assertEqual(self.finalize(result_id), 'changes_requested')
        saved = copy.deepcopy(self.gh.checks[self.snapshot['check_id']])
        with self.assertRaises(Blocked):
            self.finalize(result_id, '2' * 32)
        self.assertEqual(self.gh.checks[self.snapshot['check_id']], saved)
        self.assertEqual(saved['conclusion'], 'failure')
        self.assertEqual(self.record()['review']['findings'][0]['id'], 'F-1')

    def test_notification_failure_after_gate_completion_is_resumable(self):
        self.claim()
        result_id=self.result()
        original=self.gh.request
        def failed_comment(method,path,data=None):
            if method=='POST' and path.endswith('/comments'):
                raise Blocked('comment unavailable')
            return original(method,path,data)
        with patch.object(self.gh, 'request', side_effect=failed_comment):
            with self.assertRaisesRegex(Blocked, 'comment unavailable'):
                self.finalize(result_id)
        self.assertEqual(self.record()['phase'],'completed')
        before=len(self.gh.comments)
        self.assertEqual(self.finalize(result_id),'changes_requested')
        self.assertGreater(len(self.gh.comments), before)
        after=len(self.gh.comments)
        self.finalize(result_id)
        self.assertEqual(len(self.gh.comments), after)

    def test_duplicate_claim_dispatch_and_finalization_are_idempotent(self):
        first = self.claim()
        self.assertEqual(self.claim(), first)
        result_id = self.result()
        self.finalize(result_id)
        before = copy.deepcopy(self.gh.checks)
        comments = len(self.gh.comments)
        self.assertEqual(self.finalize(result_id), 'changes_requested')
        self.assertEqual(self.gh.checks, before)
        self.assertEqual(len(self.gh.comments), comments)

    def test_concurrent_local_devices_only_invoke_one_model(self):
        rendezvous, workflow_lock = threading.Barrier(2), threading.Lock()

        def dispatch(config, pr, check_id, claim_id, result_id=0):
            if not result_id:
                rendezvous.wait(timeout=5)  # Both devices already read the same pending receipt.
            with workflow_lock:
                try:
                    self.dispatch(config, pr, check_id, claim_id, result_id)
                except Blocked:
                    # Real dispatch acknowledges enqueueing; the failed workflow owns no claim.
                    pass

        def device():
            try:
                return local_review.review_pr(self.gh, 1, self.config, dispatch=False, dry_run=False)
            except Blocked:
                return 'lost claim'

        with patch.object(local_review, 'require_trusted_checkout'), \
                patch.object(local_review, 'dispatch_review', side_effect=dispatch), \
                patch.object(local_review, 'run_codex', return_value=(review_for(self.snapshot),
                    {'thread_id': 't', 'turns': 1, 'usage': {}})) as model, ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(device) for _ in range(2)]
            outcomes = [future.result(timeout=10) for future in futures]
        self.assertEqual(sorted(outcomes), ['changes_requested', 'lost claim'])
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.gh.checks[self.snapshot['check_id']]['conclusion'], 'failure')
        self.assertEqual(self.record()['review']['findings'][0]['id'], 'F-1')

    def test_completed_result_replay_cannot_report_pass_after_head_changes(self):
        self.claim()
        result_id = self.result('pass')
        self.finalize(result_id)
        before = copy.deepcopy(self.gh.checks)
        self.gh.pr['head']['sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'stale'):
            self.finalize(result_id)
        self.assertEqual(self.gh.checks, before)

    def test_result_size_limit_is_checked_before_upload_or_gate_update(self):
        self.claim()
        before = copy.deepcopy(self.gh.checks)
        check, record = queue.verified_gate(self.gh, 1, self.snapshot['check_id'], self.config)
        with self.assertRaisesRegex(Blocked, 'too large'):
            local_review.submit_result(self.gh, self.config, check, record, None, {}, False, error='x' * 60000)
        self.assertEqual(self.gh.checks, before)

    def test_a_second_result_cannot_replace_a_completed_blocking_review(self):
        self.claim()
        blocking, passing = self.result(), self.result('pass')
        self.finalize(blocking)
        with self.assertRaisesRegex(Blocked, 'already completed'):
            self.finalize(passing)
        self.assertEqual(self.gh.checks[self.snapshot['check_id']]['conclusion'], 'failure')
        self.assertTrue(self.record()['review']['findings'])

    def test_claims_reserve_review_limit_even_without_a_result(self):
        self.config['limits']['max_reviews_per_pr'] = 1
        self.claim()
        retry = self.pending(20, retry=True)
        with self.assertRaisesRegex(Blocked, 'review limit'):
            self.claim('2' * 32, retry)
        self.assertEqual(self.record()['claim']['id'], '1' * 32)

    def test_fresh_maintainer_retry_supersedes_the_old_owner(self):
        self.claim()
        result_id = self.result('pass')
        retry = self.pending(20, retry=True)
        self.claim('2' * 32, retry)
        with self.assertRaisesRegex(Blocked, 'superseded'):
            self.finalize(result_id)
        self.assertNotEqual(self.gh.checks[self.snapshot['check_id']].get('conclusion'), 'success')
        self.assertEqual(engine.receipt(self.gh.checks[retry['check_id']])['claim']['id'], '2' * 32)

    def test_old_sha_and_new_human_feedback_never_publish_a_pass(self):
        self.claim()
        result_id = self.result('pass')
        self.gh.pr['head']['sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'stale'):
            self.finalize(result_id)
        self.assertNotEqual(self.gh.checks[self.snapshot['check_id']].get('conclusion'), 'success')
        self.gh.pr['head']['sha'] = 'a' * 40
        with patch.object(engine, 'all_feedback', return_value=[{'body': 'new feedback'}]):
            with self.assertRaisesRegex(Blocked, 'feedback changed'):
                self.finalize(result_id)
        self.assertNotEqual(self.gh.checks[self.snapshot['check_id']].get('conclusion'), 'success')

    def test_error_and_dry_run_results_finish_with_failure_and_keep_the_slot(self):
        self.claim()
        result_id = self.result(error='Local model invocation failed.')
        self.assertEqual(self.finalize(result_id), 'blocked')
        self.assertIsNone(self.record()['review'])
        self.assertEqual(self.gh.checks[self.snapshot['check_id']]['conclusion'], 'failure')
        retry = self.pending(20, retry=True)
        self.snapshot = retry
        self.claim('2' * 32)
        result_id = self.result('pass', dry_run=True)
        self.assertIsNone(engine.receipt(self.gh.checks[result_id])['review'])
        self.assertEqual(self.finalize(result_id, '2' * 32), 'blocked')
        self.assertIsNone(self.record()['review'])
        self.config['limits']['max_reviews_per_pr'] = 2
        with self.assertRaisesRegex(Blocked, 'review limit'):
            queue.require_review_budget(self.gh, 1, self.config)

    def test_publication_network_failure_can_retry_without_another_model_call(self):
        self.claim()
        result_id = self.result('pass')
        self.gh.fail_final_patch = True
        with self.assertRaisesRegex(Blocked, 'transport lost'):
            self.finalize(result_id)
        self.assertEqual(self.record()['phase'], 'review_claimed')
        self.gh.fail_final_patch = False
        self.assertEqual(self.finalize(result_id), 'pass')

    def test_failed_local_dispatch_keeps_result_and_provides_recovery_ids(self):
        self.claim()
        check, record = queue.verified_gate(self.gh, 1, self.snapshot['check_id'], self.config)
        with patch.object(local_review, 'dispatch_review', side_effect=subprocess.CalledProcessError(1, ['gh'])):
            with self.assertRaisesRegex(Blocked, 'review_check=.*review_claim=.*review_result='):
                local_review.publish_review(self.gh, self.config, check, record, review_for(self.snapshot), reviewer(), False)
        results = [c for c in self.gh.checks.values() if c['name'] == queue.RESULT_NAME]
        self.assertEqual(len(results), 1)
        self.assertEqual(self.gh.checks[check['id']]['status'], 'in_progress')
        self.assertEqual(self.finalize(results[0]['id']), 'changes_requested')

    def test_result_app_claim_snapshot_model_and_run_tampering_are_rejected(self):
        self.claim()
        result_id = self.result('pass')
        original = copy.deepcopy(self.gh.checks[result_id])
        mutations = [('app', {'id': 8}), ('head_sha', 'c' * 40), ('external_id', 'forged'),
                     ('name', 'factory/senior-review'), ('details_url', 'https://github.com/other'), ('conclusion', 'success')]
        for field, value in mutations:
            with self.subTest(field=field):
                self.gh.checks[result_id] = {**copy.deepcopy(original), field: value}
                with self.assertRaises(Blocked):
                    self.finalize(result_id)
        for field, value in [('snapshot_digest', 'forged'), ('check_id', 99), ('claim', {'id': '2' * 32}),
                             ('reviewer', {**reviewer(), 'model': 'other'})]:
            with self.subTest(field=field):
                record = engine.receipt(original)
                record[field] = value
                self.gh.checks[result_id] = {**copy.deepcopy(original), 'output': {'text': json.dumps(record)}}
                with self.assertRaises(Blocked):
                    self.finalize(result_id)
        self.gh.checks[result_id] = original
        self.gh.runs[2]['head_sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'workflow revision'):
            self.finalize(result_id)
        self.assertNotEqual(self.gh.checks[self.snapshot['check_id']].get('conclusion'), 'success')

    def test_claim_requires_verified_source_jobs_and_fresh_main_maintainer_run(self):
        self.gh.jobs[1][1]['conclusion'] = 'failure'
        with self.assertRaisesRegex(Blocked, 'trusted job'):
            self.claim()
        self.gh.jobs[1][1]['conclusion'] = 'success'
        for field, value in [('event', 'push'), ('head_branch', 'other'), ('head_sha', 'c' * 40),
                             ('run_attempt', 2), ('triggering_actor', {'type': 'Bot', 'id': 1, 'login': 'test-human'})]:
            with self.subTest(field=field):
                self.gh.add_run(40)
                self.gh.runs[40][field] = value
                with patch.dict(os.environ, {'GITHUB_RUN_ID': '40'}), self.assertRaises(Blocked):
                    queue.coordinate(self.gh, self.config, 1, self.snapshot['check_id'], '1' * 32)
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}), self.assertRaisesRegex(Blocked, 'rerun'):
            self.claim()
        self.assertNotIn('claim', self.record())

    def test_losing_device_never_starts_model_and_winner_only_posts_result(self):
        self.claim()
        with patch.object(local_review, 'require_trusted_checkout'), patch.object(local_review, 'run_codex') as model:
            with self.assertRaisesRegex(Blocked, 'owned'):
                local_review.review_pr(self.gh, 1, self.config, dispatch=False, dry_run=False)
        model.assert_not_called()
        self.assertEqual(self.record()['phase'], 'review_claimed')

    def test_local_end_to_end_and_model_error_go_through_the_queue(self):
        with patch.object(local_review, 'require_trusted_checkout'), \
                patch.object(local_review, 'dispatch_review', side_effect=self.dispatch), \
                patch.object(local_review, 'run_codex', return_value=(review_for(self.snapshot, 'pass'), {'thread_id': 't', 'turns': 1, 'usage': {}})):
            self.assertEqual(local_review.review_pr(self.gh, 1, self.config, dispatch=False, dry_run=False), 'pass')
        self.assertEqual(self.gh.checks[self.snapshot['check_id']]['conclusion'], 'success')
        self.snapshot = self.pending(20, retry=True)
        with patch.object(local_review, 'require_trusted_checkout'), \
                patch.object(local_review, 'dispatch_review', side_effect=self.dispatch), \
                patch.object(local_review, 'run_codex', side_effect=Blocked('model unavailable')):
            with self.assertRaisesRegex(Blocked, 'model unavailable'):
                local_review.review_pr(self.gh, 1, self.config, dispatch=False, dry_run=False)
        self.assertEqual(self.gh.checks[self.snapshot['check_id']]['conclusion'], 'failure')
        self.assertIn('claim', self.record())

    def test_active_claim_check_rejects_new_head_feedback_and_superseding_retry(self):
        self.claim()
        original = self.record()['claim']
        local_review.require_active_claim(self.gh, self.config, self.snapshot, original)
        self.gh.pr['head']['sha'] = 'c' * 40
        with self.assertRaisesRegex(Blocked, 'stale head'):
            local_review.require_active_claim(self.gh, self.config, self.snapshot, original)
        self.gh.pr['head']['sha'] = 'a' * 40
        with patch.object(engine, 'all_feedback', return_value=[{'body': 'new feedback'}]):
            with self.assertRaisesRegex(Blocked, 'feedback changed'):
                local_review.require_active_claim(self.gh, self.config, self.snapshot, original)
        self.pending(20, retry=True)
        with self.assertRaisesRegex(Blocked, 'superseded'):
            local_review.require_active_claim(self.gh, self.config, self.snapshot, original)

    def test_review_pr_supplies_the_bound_active_claim_callback(self):
        observed = []

        def model(instructions, material, schema, config, freshness=None):
            freshness()
            self.gh.pr['head']['sha'] = 'c' * 40
            with self.assertRaisesRegex(Blocked, 'stale head'):
                freshness()
            observed.append('cancelled')
            self.gh.pr['head']['sha'] = 'a' * 40
            return review_for(self.snapshot, 'pass'), {'thread_id': 't', 'turns': 1, 'usage': {}}

        with patch.object(local_review, 'require_trusted_checkout'), \
                patch.object(local_review, 'dispatch_review', side_effect=self.dispatch), \
                patch.object(local_review, 'run_codex', side_effect=model):
            self.assertEqual(local_review.review_pr(self.gh, 1, self.config, False, False), 'pass')
        self.assertEqual(observed, ['cancelled'])

    def test_workflow_keeps_claim_and_finalization_in_the_existing_pr_serialization(self):
        workflow = (ROOT / '.github/workflows/factory.yml').read_text()
        self.assertIn('group: factory-${{ github.repository }}-pr-${{ fromJSON(inputs.pr) }}', workflow)
        self.assertIn('cancel-in-progress: false', workflow)
        self.assertIn('name: Review coordination', workflow)
        job = workflow.split('\n  review-coordinate:\n', 1)[1].split('\n  correction:\n', 1)[0]
        self.assertIn("github.ref == format('refs/heads/{0}', github.event.repository.default_branch)", job)
        self.assertIn('local_review_queue.py', job)
        self.assertNotIn('CODEX_ACCESS_TOKEN', workflow)
        self.assertNotIn('actions: write', workflow)


if __name__ == '__main__':
    unittest.main()
