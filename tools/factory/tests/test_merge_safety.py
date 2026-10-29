"""Collision sweep and verified merge: real Git data; only GitHub, fetch and model edges are fake."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import session
import engine
import local_review
import merge_safety
import test_session
from test_session import REPOSITORY, git
from contracts import Blocked


class MergeFixture(test_session.GitHubFixture):
    """Adds open PRs, compare, check runs, review threads, the merge lock and the merge itself."""
    def __init__(self, case):
        super().__init__(case)
        self.open_prs, self.pr_files, self.head_checks, self.threads = [], {}, [], []
        self.compare = {'status': 'ahead', 'behind_by': 0}
        self.merges, self.merge_parents, self.lock, self.locks, self.on_lock = [], None, None, [], None

    def command(self, arguments, data=None):
        if arguments[:2] == ['api', 'graphql']:
            nodes = [{'isResolved': resolved} for resolved in self.threads]
            return json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {'totalCount': len(nodes), 'nodes': nodes}}}}})
        return super().command(arguments, data)

    def gh_merge(self, pr, head, outcome='sent', merged=True):
        """Stands in for `gh pr merge --admin --match-head-commit` run with the maintainer's login."""
        self.merges.append((pr, head))
        if merged:
            self.pr.update(state='closed', merged=True, merge_commit_sha='c' * 40)
        return outcome

    def request(self, method, path, data=None):
        prefix = '/repos/' + REPOSITORY
        if method == 'GET' and path.startswith(prefix + '/compare/' + self.case.base + '...' + self.pr['head']['sha']):
            return copy.deepcopy(self.compare)
        if method == 'GET' and path == prefix + '/commits/' + 'c' * 40:
            return {'parents': [{'sha': sha} for sha in (self.merge_parents or [self.main, self.pr['head']['sha']])]}
        if method == 'POST' and path == prefix + '/git/refs':
            if self.lock is not None:
                raise Blocked('GitHub POST /git/refs: HTTP 422')
            self.lock = copy.deepcopy(data)
            self.locks.append(copy.deepcopy(data))
            if self.on_lock:
                self.on_lock()
            return {'ref': data['ref'], 'object': {'sha': data['sha']}}
        if method == 'DELETE' and path == prefix + '/git/refs/tags/factory-merge-lock':
            self.lock = None
            return None
        return super().request(method, path, data)

    def pages(self, path, field=None):
        if '/pulls?state=open&base=main' in path:
            return copy.deepcopy(self.open_prs)
        if '/check-runs?' in path:
            return copy.deepcopy(self.head_checks)
        if path.endswith('/files'):
            number = int(path.rsplit('/pulls/', 1)[1].split('/')[0])
            if number in self.pr_files:
                return copy.deepcopy(self.pr_files[number])
        return super().pages(path, field)


class MergeSafety(unittest.TestCase):
    setUp = test_session.SessionBoundaries.setUp
    model = test_session.SessionBoundaries.model

    def fixture(self):
        self.gh = MergeFixture(self)
        self.sources = {}

    def other_pr(self, number, branch, changes, task='docs/work/TEST.md'):
        """Another maintainer's PR that started from the same main as the candidate."""
        other = Path(self.temp.name) / f'other-{number}'
        git(self.control, 'clone', '-q', str(self.control), str(other))
        git(other, 'switch', '-qc', branch)
        for name, content in changes.items():
            (other / name).write_text(content)
        git(other, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qam', branch)
        self.gh.open_prs.append({'number': number, 'draft': False, 'base': {'ref': 'main'},
                                 'head': {'sha': git(other, 'rev-parse', 'HEAD'), 'ref': branch, 'repo': {'full_name': REPOSITORY}},
                                 'body': '```factory-handoff\n' + json.dumps({'runner': 'claude', 'task': task, 'owner': 'Zerosteps1'}) + '\n```'})
        self.gh.pr_files[number] = [{'filename': name, 'status': 'modified'} for name in changes]
        self.sources[number] = (other, branch)

    def fetch(self, trial, numbers):
        # Stands in for the HTTPS fetch of refs/pull/<n>/head from GitHub.
        for number in numbers:
            other, branch = self.sources[number]
            git(trial, 'fetch', '-q', str(other), f'+refs/heads/{branch}:refs/factory/pull/{number}')
        return True

    def git_state(self):
        return {str(root): (git(root, 'for-each-ref'), git(root, 'status', '--porcelain', '--ignored'),
                            sorted(p.relative_to(root).as_posix() for p in (root / '.git/objects').rglob('*')))
                for root in (self.control, self.candidate)}

    def gates(self, digest=None, **change):
        handoff = {'runner': 'claude', 'task': 'docs/work/TEST.md', 'owner': 'Zerosteps1'}
        feedback = engine.digest(engine.all_feedback(self.gh, REPOSITORY, 1, self.config)) if digest is None else digest
        receipt = json.dumps({'phase': 'completed', 'snapshot': {'handoff': handoff, 'feedback_digest': feedback}})
        return [{'id': ident, 'name': name, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 77},
                 'external_id': f'{REPOSITORY}:1:{self.head}:{self.base}:5:1', 'output': {'text': receipt}, **change}
                for ident, name in enumerate(self.config['required_checks'], 1)]

    def merging(self, outcome='sent', merged=True):
        return patch.object(merge_safety, 'gh_merge', side_effect=lambda pr, head: self.gh.gh_merge(pr, head, outcome, merged))

    def body(self):
        path = Path(self.temp.name) / 'body.md'
        path.write_text('Change with its evidence.')
        return path

    def test_collision_sweep_names_overlaps_and_trial_conflicts_without_writing_checkouts(self):
        self.fixture()
        self.gh.open_prs.append(copy.deepcopy(self.gh.pr))  # the candidate's own PR is not a collision
        self.other_pr(2, 'feature/two', {'tools/factory/example.py': 'VALUE = 5\n'})
        self.other_pr(3, 'feature/three', {'AGENTS.md': 'OTHER CONTROL\n'}, task='docs/work/OTHER.md')
        self.other_pr(4, 'feature/four', {'AGENTS.md': 'SAME TASK\n'})
        self.other_pr(5, 'feature/five', {'tools/factory/example.py': 'VALUE = 9\n'})
        self.gh.open_prs[-1]['body'] = '```factory-handoff\n["runner", "task", "owner"]\n```'  # malformed, still a PR
        self.other_pr(6, 'fork-branch', {'AGENTS.md': 'FORK\n'})
        self.gh.open_prs[-1].update(body='```factory-handoff\n5\n```')
        self.gh.open_prs[-1]['head']['repo'] = {'full_name': 'someone/fork'}
        before = self.git_state()
        with patch.object(merge_safety, 'fetch_pulls', side_effect=self.fetch) as fetched:
            report = merge_safety.collisions(self.gh, self.candidate, 'docs/work/TEST.md')
        self.assertEqual(self.git_state(), before)
        # Disjoint files do not prove a clean merge: every open PR, forks included, is trial-merged.
        self.assertEqual(fetched.call_args.args[1], [2, 3, 4, 5, 6])
        self.assertEqual(report['main'], {'sha': self.base, 'contains': True, 'conflicts': []})
        self.assertEqual([(o['pr'], o['same_task'], o['overlap'], o['conflicts']) for o in report['open_prs']],
                         [(2, True, ['tools/factory/example.py'], ['tools/factory/example.py']), (3, False, [], []), (4, True, [], []),
                          (5, False, ['tools/factory/example.py'], ['tools/factory/example.py']), (6, False, [], [])])
        self.assertEqual(report['limitations'], [])
        summary = merge_safety.collision_summary(report)
        self.assertIn('- #2 (same work order): overlapping files `tools/factory/example.py`; '
                      'trial merge conflicts in `tools/factory/example.py`.', summary)
        self.assertIn('- #4 (same work order): overlapping files none; trial merge clean.', summary)
        self.assertNotIn('#3', summary)
        self.assertIn('2 further open PR(s) share no file and merge cleanly.', summary)
        with patch.object(merge_safety, 'fetch_pulls', return_value=False):
            unfetched = merge_safety.collisions(self.gh, self.candidate, 'docs/work/TEST.md')
        self.assertIsNone(unfetched['open_prs'][0]['conflicts'])
        self.assertIn('trial merge not run', merge_safety.collision_summary(unfetched))
        self.assertTrue(unfetched['limitations'])

    def test_trial_merge_and_fetch_never_report_unknown_results_as_clean(self):
        tree, scratch = b'a' * 40, Path(self.temp.name)
        cases = [((0, tree + b'\0'), []), ((1, tree + b'\0x.py\0'), ['x.py']), ((1, tree + b'\0'), None),
                 ((1, b''), None), ((128, tree + b'\0'), None)]
        for (code, out), expected in cases:
            with self.subTest(code=code, out=out), \
                    patch.object(session, 'git_run', return_value=subprocess.CompletedProcess([], code, out, b'')):
                self.assertEqual(merge_safety.conflicts(scratch, 'a' * 40, 'b' * 40), expected)
        with patch.object(session, 'git_run', side_effect=subprocess.TimeoutExpired(['git'], 120)):
            self.assertFalse(merge_safety.fetch_pulls(scratch, [2]))
            self.assertIsNone(merge_safety.conflicts(scratch, 'a' * 40, 'b' * 40))
        with patch.object(session, 'git_run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            merge_safety.fetch_pulls(scratch, [2])
        self.assertIn('core.alternateRefsCommand=true', run.call_args.args)

    def test_candidate_behind_main_is_named_and_submit_stops_before_any_model_call(self):
        self.fixture()
        (self.control / 'tools/factory/example.py').write_text('VALUE = 3\n')
        git(self.control, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qam', 'Main moved')
        self.gh.main = git(self.control, 'rev-parse', 'HEAD')
        report = merge_safety.collisions(self.gh, self.candidate)
        self.assertEqual((report['main']['contains'], report['main']['conflicts']), (False, ['tools/factory/example.py']))
        with patch.object(session, 'HumanGitHub', return_value=self.gh):
            self.assertEqual(session.main(['collisions', '--candidate', str(self.candidate)]), 1)
        with patch.object(local_review, 'run_codex', side_effect=self.model):
            with self.assertRaisesRegex(Blocked, 'does not contain current main.*tools/factory/example.py'):
                session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude')
        self.assertEqual((self.model_calls, self.gh.creates, self.gh.posts), ([], [], []))

    def test_submit_records_collisions_for_exactly_its_head_and_comments_nowhere(self):
        self.fixture()
        self.other_pr(2, 'feature/two', {'tools/factory/example.py': 'VALUE = 5\n'})
        with patch.object(local_review, 'run_codex', side_effect=self.model), \
                patch.object(merge_safety, 'fetch_pulls', side_effect=self.fetch):
            result = session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude', draft=True)
        created = self.gh.creates[0]['body']
        self.assertIn('Collision check at `' + self.head[:12] + '` against main `' + self.base[:12] + '`: contains current main.', created)
        self.assertIn('- #2 (same work order)', created)
        self.assertEqual(engine.handoff(created, self.config)['task'], 'docs/work/TEST.md')
        self.assertEqual((result['collisions']['open_prs'][0]['pr'], self.gh.posts), (2, []))
        stale = {**result['collisions'], 'candidate': {**result['collisions']['candidate'], 'head_sha': 'f' * 40}}
        self.gh.creates.clear()
        with patch.object(local_review, 'run_codex', side_effect=self.model), patch.object(merge_safety, 'collisions', return_value=stale):
            with self.assertRaisesRegex(Blocked, 'changed after the collision sweep'):
                session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude', draft=True)
        self.assertEqual(self.gh.creates, [])

    def test_merge_binds_both_app_gates_to_this_head_and_main_under_the_lock(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), [True]
        verdict = merge_safety.merge(self.gh, 1, dry_run=True)
        self.assertEqual((verdict['mergeable'], verdict['problems'], self.gh.merges, self.gh.locks), (True, [], [], []))
        with self.merging():
            result = merge_safety.merge(self.gh, 1)
        self.assertEqual(self.gh.merges, [(1, self.head)])
        self.assertEqual((self.gh.locks, self.gh.lock), ([{'ref': 'refs/tags/factory-merge-lock', 'sha': self.base}], None))
        self.assertEqual((result['merged'], result['merge_commit_sha'], len(self.gh.posts)), (True, 'c' * 40, 1))
        self.assertIn(f'head `{self.head}` onto main `{self.base}`', self.gh.posts[0]['body'])
        self.assertIn('verified for exactly this head and main', self.gh.posts[0]['body'])

    def test_merge_refuses_unverified_gates_without_lock_or_github_merge(self):
        self.fixture()
        cases = {
            'missing from the publisher App': lambda: setattr(self.gh, 'head_checks', self.gates(app={'id': 99})),
            'factory/senior-review: failure': lambda: setattr(self.gh, 'head_checks', self.gates()[:1] + [
                {**self.gates()[1], 'conclusion': 'failure'}]),
            'factory/senior-review: in_progress': lambda: setattr(self.gh, 'head_checks', self.gates() + [
                {**self.gates()[1], 'id': 3, 'status': 'in_progress', 'conclusion': None}]),
            'older main': lambda: setattr(self.gh, 'head_checks', self.gates(external_id=f'{REPOSITORY}:1:{self.head}:{"d" * 40}:5:1')),
            'human feedback changed after the review': lambda: setattr(self.gh, 'head_checks', self.gates(digest='stale')),
            'unresolved review thread': lambda: setattr(self.gh, 'threads', [True, False]),
            'does not contain the current main': lambda: setattr(self.gh, 'compare', {'status': 'diverged', 'behind_by': 2}),
            'draft': lambda: self.gh.pr.update(draft=True),
        }
        for expected, arrange in cases.items():
            with self.subTest(expected=expected):
                self.gh.head_checks, self.gh.threads = self.gates(), [True]
                self.gh.compare = {'status': 'ahead', 'behind_by': 0}
                self.gh.pr['draft'] = False
                arrange()
                self.assertIn(expected, ' '.join(merge_safety.merge(self.gh, 1, dry_run=True)['problems']))
                with self.assertRaisesRegex(Blocked, 'not merged: .*' + expected), self.merging():
                    merge_safety.merge(self.gh, 1)
                self.assertEqual((self.gh.merges, self.gh.posts, self.gh.locks), ([], [], []))

    def test_merges_by_two_maintainers_are_serialized_before_the_merge(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), []
        self.gh.lock = {'ref': 'refs/tags/factory-merge-lock', 'sha': self.base}  # the other maintainer is merging
        with self.assertRaisesRegex(Blocked, 'merge lock .* is held'), self.merging():
            merge_safety.merge(self.gh, 1)
        self.assertEqual((self.gh.merges, self.gh.posts), ([], []))
        self.assertIsNotNone(self.gh.lock, 'a refused merge must not release somebody else\'s lock')
        self.gh.lock = None
        # The other merge landed between our verification and taking the lock: refuse, release, merge nothing.
        self.gh.on_lock = lambda: setattr(self.gh, 'main', 'e' * 40)
        with self.assertRaisesRegex(Blocked, 'changed before the merge; nothing was merged'), self.merging():
            merge_safety.merge(self.gh, 1)
        self.assertEqual((self.gh.merges, self.gh.posts, self.gh.lock), ([], [], None))

    def test_checks_and_threads_are_validated_again_while_the_lock_is_held(self):
        self.fixture()
        rerun = {**self.gates()[1], 'id': 3, 'status': 'in_progress', 'conclusion': None}
        for name, change in (('1 unresolved review thread', lambda: setattr(self.gh, 'threads', [False])),
                             ('factory/senior-review: in_progress', lambda: self.gh.head_checks.append(rerun))):
            with self.subTest(name=name):
                self.gh.head_checks, self.gh.threads, self.gh.on_lock = self.gates(), [], change
                with self.assertRaisesRegex(Blocked, 'changed before the merge; nothing was merged; .*' + name), self.merging():
                    merge_safety.merge(self.gh, 1)
                self.assertEqual((self.gh.merges, self.gh.posts, self.gh.lock), ([], [], None))

    def test_an_unanswered_merge_keeps_the_lock_and_a_refusal_releases_it(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), []
        with self.assertRaisesRegex(Blocked, 'GitHub refused the merge'), self.merging('refused', merged=False):
            merge_safety.merge(self.gh, 1)
        self.assertIsNone(self.gh.lock)
        with self.assertRaisesRegex(Blocked, 'outcome of PR #1 unknown; the lock stays'), self.merging('unknown', merged=False):
            merge_safety.merge(self.gh, 1)
        self.assertEqual(self.gh.lock, {'ref': 'refs/tags/factory-merge-lock', 'sha': self.base})
        self.gh.lock = None
        with self.merging('unknown', merged=True):
            self.assertTrue(merge_safety.merge(self.gh, 1)['merged'])  # GitHub did merge: verified as usual
        self.assertIsNone(self.gh.lock)

    def test_only_an_answer_from_github_counts_as_a_refusal(self):
        cases = [(subprocess.CompletedProcess([], 0, '', ''), 'sent'),
                 (subprocess.CompletedProcess([], 1, '', 'GraphQL: Pull Request is not mergeable (mergePullRequest)'), 'refused'),
                 (subprocess.CompletedProcess([], 1, '', 'Head branch was modified. Review and try the merge again.'), 'refused'),
                 (subprocess.CompletedProcess([], 1, '', 'connection reset by peer'), 'unknown'),
                 (subprocess.TimeoutExpired(['gh'], 120), 'unknown')]
        for result, expected in cases:
            with self.subTest(expected=expected, result=result), \
                    patch.object(merge_safety.subprocess, 'run', **({'side_effect': result} if isinstance(result, Exception) else {'return_value': result})) as run:
                self.assertEqual(merge_safety.gh_merge(1, 'a' * 40), expected)
            self.assertEqual(run.call_args.args[0][-4:], ['--merge', '--admin', '--match-head-commit', 'a' * 40])

    def test_a_merge_outside_the_helper_is_reported_as_an_error(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), []
        self.gh.merge_parents = ['e' * 40, self.head]
        with self.assertRaisesRegex(Blocked, 'main moved outside session.py merge'), self.merging():
            merge_safety.merge(self.gh, 1)
        self.assertEqual((len(self.gh.merges), self.gh.lock), (1, None))
        self.assertIn('WARNING: main was `' + 'e' * 40 + '`', self.gh.posts[0]['body'])

    def test_human_transport_allows_only_the_exact_compare_route(self):
        with patch.object(session.HumanGitHub, 'command', return_value='{"status":"ahead","behind_by":0}') as command:
            self.assertTrue(engine.contains_base(session.HumanGitHub(), REPOSITORY, 'b' * 40, 'a' * 40))
            self.assertIn(f'/repos/{REPOSITORY}/compare/{"b" * 40}...{"a" * 40}?per_page=1', command.call_args.args[0])
            for unsafe in (f'/repos/{REPOSITORY}/contents/../secrets', f'/repos/{REPOSITORY}/compare/main...{"a" * 40}?per_page=1',
                           f'/repos/{REPOSITORY}/compare/{"b" * 40}...{"a" * 40}/../x?per_page=1'):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(Blocked, 'unsafe API path'):
                    session.HumanGitHub().request('GET', unsafe)


if __name__ == '__main__':
    unittest.main()
