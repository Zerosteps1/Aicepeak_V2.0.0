"""Collision sweep and verified merge: real Git data; only GitHub, fetch and model edges are fake."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from factory_testlib import REPOSITORY, SESSION_BRANCHES, SessionGitHub, SessionRepos, git
import branches
import engine
import github_api
import local_review
import merge_safety
import session
from contracts import Blocked, handoff


class MergeFixture(SessionGitHub):
    """Adds open PRs, compare, check runs, review threads, the merge lock and the merge itself."""
    def __init__(self, case):
        super().__init__(case)
        self.open_prs, self.pr_files, self.head_checks, self.threads = [], {}, [], []
        self.compare = {'status': 'ahead', 'behind_by': 0}
        self.merges, self.merge_parents, self.lock, self.locks, self.on_lock = [], None, None, [], None
        self.read_back_fails, self.answered = None, False

    def command(self, arguments, data=None):
        if arguments[:2] == ['api', 'graphql']:
            nodes = [{'isResolved': resolved} for resolved in self.threads]
            return json.dumps({'data': {'repository': {'pullRequest': {'reviewThreads': {'totalCount': len(nodes), 'nodes': nodes}}}}})
        return super().command(arguments, data)

    def gh_merge(self, pr, head, outcome='sent', merged=True):
        """Stands in for `gh pr merge --admin --match-head-commit` run with the maintainer's login."""
        self.merges.append((pr, head))
        self.answered = True
        if merged:
            self.pr.update(state='closed', merged=True, merge_commit_sha='c' * 40)
        return outcome

    def request(self, method, path, data=None):
        prefix = '/repos/' + REPOSITORY
        if method == 'GET' and path == prefix + '/pulls/1' and self.answered:
            self.answered = False  # only the read-back right after the merge request can fail
            if self.read_back_fails:
                raise self.read_back_fails
        if method == 'GET' and path.startswith(prefix + '/compare/' + self.pr['base']['sha'] + '...' + self.pr['head']['sha']):
            return copy.deepcopy(self.compare)
        if method == 'GET' and path == prefix + '/commits/' + 'c' * 40:
            target = self.tips[self.pr['base']['ref']]
            return {'parents': [{'sha': sha} for sha in (self.merge_parents or [target, self.pr['head']['sha']])]}
        if method == 'POST' and path == prefix + '/git/refs':
            if self.lock is not None:
                raise Blocked('GitHub POST /git/refs: HTTP 422')
            self.lock = copy.deepcopy(data)
            self.locks.append(copy.deepcopy(data))
            if self.on_lock:
                self.on_lock()
            return {'ref': data['ref'], 'object': {'sha': data['sha']}}
        if method == 'DELETE' and path.startswith(prefix + '/git/refs/tags/factory-merge-lock'):
            if self.lock is None or path != prefix + '/git/' + self.lock['ref']:
                raise AssertionError('released a lock this merge does not hold: ' + path)
            self.lock = None
            return None
        return super().request(method, path, data)

    def pages(self, path, field=None):
        if '/pulls?state=open&base=' in path:
            base = path.rsplit('base=', 1)[1]
            return copy.deepcopy([pr for pr in self.open_prs if pr['base']['ref'] == base])
        if path.endswith('/files'):
            number = int(path.rsplit('/pulls/', 1)[1].split('/')[0])
            if number in self.pr_files:
                return copy.deepcopy(self.pr_files[number])
        return super().pages(path, field)


class MergeSafety(SessionRepos, unittest.TestCase):
    def fixture(self):
        self.gh = MergeFixture(self)
        self.sources = {}

    def other_pr(self, number, branch, changes, task='docs/work/TEST.md'):
        """Another maintainer's PR into testing that started from the same tip as the candidate."""
        other = Path(self.temp.name) / f'other-{number}'
        git(self.control, 'clone', '-q', str(self.control), str(other))
        git(other, 'switch', '-qc', branch)
        for name, content in changes.items():
            (other / name).write_text(content)
        git(other, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qam', branch)
        self.gh.open_prs.append({'number': number, 'draft': False, 'base': {'ref': 'testing'},
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

    def gates(self, digest=None, base='testing', pin=None, **change):
        transfer = handoff(self.gh.pr['body'], self.config)
        feedback = engine.digest(engine.all_feedback(self.gh, REPOSITORY, 1, self.config)) if digest is None else digest
        receipt = json.dumps({'phase': 'completed', 'snapshot': {'handoff': transfer, 'feedback_digest': feedback,
                                                                 **({'task_pin': pin} if pin else {})}})
        return [{'id': ident, 'name': name, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 77}, 'head_sha': self.head,
                 'external_id': f'{REPOSITORY}:1:{self.head}:{self.base}:{base}:5:1', 'output': {'text': receipt}, **change}
                for ident, name in enumerate(branches.parse(self.config).required_checks(base), 1)]

    def bypass(self, name, record=(), **change):
        """A check published for this head by the bypass stage of a maintainer's `/bypass` comment."""
        receipt = {'login': 'Zerosteps1', 'id': 115100163, 'comment_id': 41, 'reason': 'Reviewer outage; checked by hand.', **dict(record)}
        check = {'id': 10, 'name': name, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 77}, 'head_sha': self.head,
                 'external_id': f'{REPOSITORY}:1:{self.head}:{self.base}:testing:9:1',
                 'output': {'title': f"Bypassed by {receipt['login']}", 'summary': receipt['reason'],
                            'text': json.dumps({'bypass': receipt})}}
        return {**check, **change}

    def bypass_comment(self, user=None, **change):
        """The maintainer's `/bypass` comment that the receipts of bypass() name, as GitHub returns it."""
        comment = {'id': 41, 'user': copy.deepcopy(user or self.gh.user), 'body': '/bypass Reviewer outage; checked by hand.',
                   'issue_url': f'https://api.github.com/repos/{REPOSITORY}/issues/1',
                   'html_url': f'https://github.com/{REPOSITORY}/pull/1#issuecomment-41',
                   'created_at': '2026-11-02T10:00:00Z', 'updated_at': '2026-11-02T10:00:00Z', **change}
        self.gh.comments = [c for c in self.gh.comments if c['id'] != 41] + [comment]
        return comment

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
        self.assertEqual(report['base'], {'ref': 'testing', 'sha': self.base, 'contains': True, 'conflicts': []})
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

    def test_candidate_behind_its_target_is_named_and_submit_stops_before_any_model_call(self):
        self.fixture()
        (self.control / 'tools/factory/example.py').write_text('VALUE = 3\n')
        git(self.control, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qam', 'Target moved')
        moved = git(self.control, 'rev-parse', 'HEAD')
        self.gh.tips.update(production=moved, testing=moved)
        report = merge_safety.collisions(self.gh, self.candidate)
        self.assertEqual((report['base']['ref'], report['base']['contains'], report['base']['conflicts']),
                         ('testing', False, ['tools/factory/example.py']))
        with patch.object(session, 'HumanGitHub', return_value=self.gh):
            self.assertEqual(session.main(['collisions', '--candidate', str(self.candidate)]), 1)
            self.assertEqual(session.main(['collisions', '--candidate', str(self.candidate), '--base', 'quick']), 0)
        with patch.object(local_review, 'run_codex', side_effect=self.model):
            with self.assertRaisesRegex(Blocked, 'does not contain current testing.*tools/factory/example.py'):
                session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude')
        self.assertEqual((self.model_calls, self.gh.creates, self.gh.posts), ([], [], []))

    def test_submit_records_collisions_for_exactly_its_head_and_comments_nowhere(self):
        self.fixture()
        self.other_pr(2, 'feature/two', {'tools/factory/example.py': 'VALUE = 5\n'})
        with patch.object(local_review, 'run_codex', side_effect=self.model), \
                patch.object(merge_safety, 'fetch_pulls', side_effect=self.fetch), patch.object(session, 'watch', return_value=None):
            result = session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude')
        created = self.gh.creates[0]['body']
        self.assertIn('Collision check at `' + self.head[:12] + '` against testing `' + self.base[:12] + '`: contains current testing.', created)
        self.assertIn('- #2 (same work order)', created)
        self.assertEqual(handoff(created, self.config)['task'], 'docs/work/TEST.md')
        self.assertEqual((result['collisions']['open_prs'][0]['pr'], self.gh.posts), (2, []))
        stale = {**result['collisions'], 'candidate': {**result['collisions']['candidate'], 'head_sha': 'f' * 40}}
        self.gh.creates.clear()
        with patch.object(local_review, 'run_codex', side_effect=self.model), patch.object(merge_safety, 'collisions', return_value=stale):
            with self.assertRaisesRegex(Blocked, 'changed after the collision sweep'):
                session.submit(self.gh, self.candidate, 'docs/work/TEST.md', [], 'Update value', self.body(), 'claude')
        self.assertEqual(self.gh.creates, [])

    def test_merge_binds_both_app_gates_to_this_head_target_and_config_tip_under_the_lock(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), [True]
        verdict = merge_safety.merge(self.gh, 1, dry_run=True)
        self.assertEqual((verdict['mergeable'], verdict['problems'], self.gh.merges, self.gh.locks), (True, [], [], []))
        self.assertEqual((verdict['base_ref'], verdict['base_sha'], verdict['policy_sha']), ('testing', self.base, self.base))
        with self.merging():
            result = merge_safety.merge(self.gh, 1)
        self.assertEqual(self.gh.merges, [(1, self.head)])
        self.assertEqual((self.gh.locks, self.gh.lock), ([{'ref': 'refs/tags/factory-merge-lock--testing', 'sha': self.base}], None))
        self.assertEqual((result['merged'], result['merge_commit_sha'], len(self.gh.posts)), (True, 'c' * 40, 1))
        self.assertIn(f'head `{self.head}` onto testing `{self.base}`', self.gh.posts[0]['body'])
        self.assertIn('verified for exactly this head, target tip and config revision', self.gh.posts[0]['body'])

    def test_merge_refuses_unverified_gates_without_lock_or_github_merge(self):
        self.fixture()
        stale, moved = 'bound to another head, target branch or config revision', 'the config branch moved after this run'
        cases = [
            ('missing from the publisher App', lambda: setattr(self.gh, 'head_checks', self.gates(app={'id': 99}))),
            ('factory/senior-review: failure', lambda: setattr(self.gh, 'head_checks', self.gates()[:1] + [
                {**self.gates()[1], 'conclusion': 'failure'}])),
            ('factory/senior-review: in_progress', lambda: setattr(self.gh, 'head_checks', self.gates() + [
                {**self.gates()[1], 'id': 3, 'status': 'in_progress', 'conclusion': None}])),
            (moved, lambda: setattr(self.gh, 'head_checks', self.gates(external_id=f'{REPOSITORY}:1:{self.head}:{"d" * 40}:testing:5:1'))),
            (stale, lambda: setattr(self.gh, 'head_checks', self.gates(external_id=f'{REPOSITORY}:1:{self.head}:{self.base}:quick:5:1'))),
            (stale, lambda: setattr(self.gh, 'head_checks', self.gates(external_id=f'{REPOSITORY}:2:{self.head}:{self.base}:testing:5:1'))),
            ('malformed binding; wait for a fresh run', lambda: setattr(self.gh, 'head_checks', self.gates(external_id=f'{REPOSITORY}:1:{self.head}:{self.base}:5:1'))),
            ('human feedback changed after the review', lambda: setattr(self.gh, 'head_checks', self.gates(digest='stale'))),
            # A review bound to another approved text of the work-order issue does not count.
            ('the work-order issue changed after the review', lambda: setattr(self.gh, 'head_checks', self.gates(
                pin={'issue': 57, 'sha256': 'a' * 64, 'record': 9}))),
            ('unresolved review thread', lambda: setattr(self.gh, 'threads', [True, False])),
            ('does not contain the current testing tip', lambda: setattr(self.gh, 'compare', {'status': 'diverged', 'behind_by': 2})),
            ('draft', lambda: self.gh.pr.update(draft=True)),
        ]
        for expected, arrange in cases:
            with self.subTest(expected=expected):
                self.gh.head_checks, self.gh.threads = self.gates(), [True]
                self.gh.compare = {'status': 'ahead', 'behind_by': 0}
                self.gh.pr['draft'] = False
                arrange()
                self.assertIn(expected, ' '.join(merge_safety.merge(self.gh, 1, dry_run=True)['problems']))
                with self.assertRaisesRegex(Blocked, 'not merged: .*' + expected), self.merging():
                    merge_safety.merge(self.gh, 1)
                self.assertEqual((self.gh.merges, self.gh.posts, self.gh.locks), ([], [], []))

    def test_a_moved_config_tip_names_the_automatic_rerun_and_its_manual_fallback(self):
        self.fixture()
        self.gh.threads = []
        moved = f'{REPOSITORY}:1:{self.head}:{"d" * 40}:testing:5:1'
        self.gh.head_checks = self.gates(external_id=moved)
        retry = f'`gh workflow run factory.yml --repo {REPOSITORY} --ref production -f pr=1 -f retry=true`'
        self.assertEqual(merge_safety.merge(self.gh, 1, dry_run=True)['problems'], [
            f'{name}: the config branch moved after this run; a fresh run is dispatched automatically (if none arrives: {retry})'
            for name in ('factory/deterministic', 'factory/senior-review')])
        # Only the config tip may differ: any other field names the general binding problem.
        for changed in (f'{REPOSITORY}:1:{self.head}:{"d" * 40}:quick:5:1', f'{REPOSITORY}:2:{self.head}:{"d" * 40}:testing:5:1'):
            with self.subTest(changed=changed):
                self.gh.head_checks = self.gates(external_id=changed)
                problems = merge_safety.merge(self.gh, 1, dry_run=True)['problems']
                self.assertTrue(problems and all('bound to another head' in p for p in problems), problems)
        self.gh.head_checks = self.gates(external_id=moved, head_sha='a' * 40)
        self.assertTrue(all('bound to another head' in p for p in merge_safety.merge(self.gh, 1, dry_run=True)['problems']))

    def test_merges_by_two_maintainers_are_serialized_before_the_merge(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), []
        self.gh.lock = {'ref': 'refs/tags/factory-merge-lock--testing', 'sha': self.base}  # the other maintainer is merging
        with self.assertRaisesRegex(Blocked, 'merge lock refs/tags/factory-merge-lock--testing is held'), self.merging():
            merge_safety.merge(self.gh, 1)
        self.assertEqual((self.gh.merges, self.gh.posts), ([], []))
        self.assertIsNotNone(self.gh.lock, 'a refused merge must not release somebody else\'s lock')
        # The other merge landed (or the config tip moved) between our verification and taking the lock:
        # refuse, release, merge nothing.
        for branch in ('testing', 'production'):
            with self.subTest(moved=branch):
                self.gh.lock, self.gh.tips = None, {**self.gh.tips, 'testing': self.base, 'production': self.base}
                self.gh.on_lock = lambda: self.gh.tips.update({branch: 'e' * 40})
                with self.assertRaisesRegex(Blocked, 'moved before the merge; nothing was merged'), self.merging():
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
        self.assertEqual(self.gh.lock, {'ref': 'refs/tags/factory-merge-lock--testing', 'sha': self.base})
        for failure in (Blocked('GitHub GET /repos: HTTP 502'), KeyboardInterrupt()):
            with self.subTest(read_back=type(failure).__name__):
                self.gh.lock, self.gh.read_back_fails = None, failure
                with self.assertRaisesRegex(Blocked, 'outcome of PR #1 unknown; the lock stays'), self.merging('unknown', merged=False):
                    merge_safety.merge(self.gh, 1)
                self.assertIsNotNone(self.gh.lock, 'a merge GitHub never confirmed must keep the lock')
        self.gh.lock, self.gh.read_back_fails = None, None
        with self.merging('unknown', merged=True):
            self.assertTrue(merge_safety.merge(self.gh, 1)['merged'])  # GitHub did merge: verified as usual
        self.assertIsNone(self.gh.lock)

    def test_only_an_answer_from_github_counts_as_a_refusal(self):
        cases = [(subprocess.CompletedProcess([], 0, '', ''), 'sent'),
                 (subprocess.CompletedProcess([], 1, '', 'GraphQL: Pull Request is not mergeable (mergePullRequest)'), 'refused'),
                 (subprocess.CompletedProcess([], 1, '', 'Head branch was modified. Review and try the merge again.'), 'refused'),
                 (subprocess.CompletedProcess([], 1, '', 'connection reset by peer'), 'unknown'),
                 (subprocess.CompletedProcess([], 1, '', 'HTTP 422: Unprocessable Entity'), 'refused'),
                 (subprocess.CompletedProcess([], 1, '', 'HTTP 504: Gateway Timeout'), 'unknown'),
                 (subprocess.CompletedProcess([], 1, '', 'GraphQL: Something went wrong while executing your query.'), 'unknown'),
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
        with self.assertRaisesRegex(Blocked, 'testing moved outside session.py merge'), self.merging():
            merge_safety.merge(self.gh, 1)
        self.assertEqual((len(self.gh.merges), self.gh.lock), (1, None))
        self.assertIn('WARNING: testing was `' + 'e' * 40 + '`', self.gh.posts[0]['body'])

    def test_human_transport_allows_only_the_exact_compare_route(self):
        with patch.object(session.HumanGitHub, 'command', return_value='{"status":"ahead","behind_by":0}') as command:
            self.assertTrue(github_api.contains(session.HumanGitHub(), REPOSITORY, 'b' * 40, 'a' * 40))
            self.assertIn(f'/repos/{REPOSITORY}/compare/{"b" * 40}...{"a" * 40}?per_page=1', command.call_args.args[0])
            for unsafe in (f'/repos/{REPOSITORY}/contents/../secrets', f'/repos/{REPOSITORY}/compare/testing...{"a" * 40}?per_page=1',
                           f'/repos/{REPOSITORY}/compare/{"b" * 40}...{"a" * 40}/../x?per_page=1'):
                with self.subTest(unsafe=unsafe), self.assertRaisesRegex(Blocked, 'unsafe API path'):
                    session.HumanGitHub().request('GET', unsafe)


    def test_production_and_ungated_targets_are_never_merged_here(self):
        self.fixture()
        self.gh.head_checks, self.gh.threads = self.gates(), []
        for base, head_ref, expected in (('production', 'testing', 'targets the production branch production: merge production PRs on GitHub'),
                                         ('sandbox', 'feature/one', 'targets sandbox, which is not a gated validation branch')):
            self.gh.target(base, head_ref)
            for dry_run in (True, False):
                with self.subTest(base=base, dry_run=dry_run), self.assertRaisesRegex(Blocked, expected), self.merging():
                    merge_safety.merge(self.gh, 1, dry_run=dry_run)
        with patch.object(session, 'HumanGitHub', return_value=self.gh):
            self.assertEqual(session.main(['merge', '--pr', '1', '--dry-run']), 1)
        self.gh.target('testing', 'feature/one')
        with self.assertRaisesRegex(Blocked, 'targets testing, not quick'):
            merge_safety.merge(self.gh, 1, base='quick')
        self.assertEqual((self.gh.merges, self.gh.locks, self.gh.posts), ([], [], []))

    def test_a_tests_gate_needs_only_the_deterministic_check_and_has_its_own_lock(self):
        self.fixture()
        self.gh.target('quick')
        self.gh.pr['body'] = '```factory-handoff\n' + json.dumps({'runner': 'claude', 'task': 'docs/work/QUICK.md', 'owner': 'Zerosteps1'}) + '\n```'
        self.gh.head_checks, self.gh.threads = self.gates(base='quick'), []
        self.assertEqual([c['name'] for c in self.gh.head_checks], ['factory/deterministic'])
        with patch.object(session, 'HumanGitHub', return_value=self.gh):
            self.assertEqual(session.main(['merge', '--pr', '1', '--base', 'quick', '--dry-run']), 0)
        with self.merging():
            result = merge_safety.merge(self.gh, 1)
        self.assertEqual((result['merged'], result['base_ref'], self.gh.lock), (True, 'quick', None))
        self.assertEqual(self.gh.locks, [{'ref': 'refs/tags/factory-merge-lock--quick', 'sha': self.base}])
        self.assertIn(f'onto quick `{self.base}`', self.gh.posts[0]['body'])

    def test_a_bypass_counts_only_when_authentic(self):
        self.fixture()
        self.bypass_comment()
        self.gh.threads = []
        passed, other = self.gates(), SESSION_BRANCHES['production'][0]['name']
        failed = [passed[0], {**passed[1], 'conclusion': 'failure'}]
        not_authentic = 'factory/senior-review: bypass without an authentic maintainer receipt'
        stale = 'factory/senior-review: bound to another head, target branch or config revision'
        cases = [
            ({}, None),
            ({'app': {'id': 99}}, 'factory/senior-review: failure'),  # not the publisher App: the failed review stays latest
            ({'head_sha': 'a' * 40}, stale),
            ({'external_id': f'{REPOSITORY}:2:{self.head}:{self.base}:testing:9:1'}, stale),
            ({'external_id': f'{REPOSITORY}:1:{self.head}:{self.base}:{other}:9:1'}, stale),
            ({'external_id': f'{REPOSITORY}:1:{self.head}:{"d" * 40}:testing:9:1'}, 'factory/senior-review: the config branch moved'),
            ({'external_id': f'{REPOSITORY}:1:{self.head}:{self.base}:9:1'}, 'factory/senior-review: malformed binding; wait for a fresh run'),
            ({'conclusion': 'neutral'}, 'factory/senior-review: neutral'),
            ({'record': {'login': 'outsider', 'id': 1}}, not_authentic),
            ({'record': {'id': 345378269}}, not_authentic),  # another maintainer's id under this login
            ({'record': {'reason': ' '}}, not_authentic),
            ({'record': {'reason': 'x' * 501}}, not_authentic),
            ({'record': {'comment_id': 0}}, not_authentic),
            ({'output': {'title': 'Bypassed by Zerosteps1', 'text': json.dumps({'bypass': 'Zerosteps1'})}}, not_authentic),
            ({'output': {**self.bypass('x')['output'], 'title': 'Passed'}}, not_authentic),
        ]
        for change, expected in cases:
            with self.subTest(change=change):
                self.gh.head_checks = failed + [self.bypass('factory/senior-review', **change)]
                problems = merge_safety.merge(self.gh, 1, dry_run=True)['problems']
                self.assertEqual(len(problems), 1 if expected else 0, problems)
                self.assertTrue(not expected or problems[0].startswith(expected), problems)
        self.gh.head_checks = [self.bypass(name, id=10 + i) for i, name in enumerate(('factory/deterministic', 'factory/senior-review'))]
        with self.merging():
            self.assertTrue(merge_safety.merge(self.gh, 1)['merged'])

    def test_a_bypass_counts_only_while_its_comment_stands_unedited_on_this_pr(self):
        self.fixture()
        self.gh.threads = []
        names = ('factory/deterministic', 'factory/senior-review')
        withdrawn = [f'{name}: the `/bypass` comment could not be re-read, or was edited or deleted; retry, or post a new `/bypass`' for name in names]
        other = next({'type': 'User', **m} for m in self.config['maintainers'] if m['id'] != self.gh.user['id'])
        moved = {'issue_url': f'https://api.github.com/repos/{REPOSITORY}/issues/2'}
        cases = [('edited', lambda: self.bypass_comment(updated_at='2026-11-02T10:05:00Z')),
                 ('deleted', lambda: setattr(self.gh, 'comments', [])),
                 ('another PR', lambda: (self.gh.elsewhere.append(self.bypass_comment(**moved)), setattr(self.gh, 'comments', []))),
                 ('another maintainer', lambda: self.bypass_comment(user=other)),
                 ('not a maintainer', lambda: self.bypass_comment(user={'type': 'User', 'id': 1, 'login': 'outsider'})),
                 ('no longer a /bypass', lambda: self.bypass_comment(body='Reviewer outage; checked by hand.'))]
        for label, arrange in cases:
            with self.subTest(comment=label):
                self.gh.elsewhere = []
                arrange()
                self.gh.head_checks = [self.bypass(name, id=10 + i) for i, name in enumerate(names)]
                self.assertEqual(merge_safety.merge(self.gh, 1, dry_run=True)['problems'], withdrawn)
                with self.assertRaisesRegex(Blocked, 'not merged: .*could not be re-read, or was edited or deleted'), self.merging():
                    merge_safety.merge(self.gh, 1)
                self.assertEqual((self.gh.merges, self.gh.posts, self.gh.locks), ([], [], []))
        # The unedited comment of the receipt's maintainer on this PR still counts.
        self.gh.elsewhere = []
        self.bypass_comment()
        self.assertEqual(merge_safety.merge(self.gh, 1, dry_run=True)['problems'], [])


if __name__ == '__main__':
    unittest.main()
