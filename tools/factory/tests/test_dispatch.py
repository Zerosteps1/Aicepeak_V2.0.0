"""Dispatcher routing with the real script; only its `api` transport and file reads are replaced."""
import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
_loader = importlib.util.spec_from_file_location('factory_dispatcher', ROOT / '.github/scripts/dispatch_factory.py')
dispatcher = importlib.util.module_from_spec(_loader)
_loader.loader.exec_module(dispatcher)

PREFIX = dispatcher.PREFIX
POLICY, PUSHED, OLD, RELEASE, HEAD = 'b' * 40, 'c' * 40, 'd' * 40, 'f' * 40, 'a' * 40
HUMAN = {'type': 'User', 'id': 101, 'login': 'test-human'}
STRANGER = {'type': 'User', 'id': 999, 'login': 'stranger'}
BASES = ('testing', 'quick', 'scratch', 'production', 'release', 'feature-x')


def config():
    """testing: full, quick: tests, scratch: none; production: maintainer-manual (config), release: no review."""
    return {'repository': dispatcher.TARGET, 'default_branch': 'testing', 'config_branch': 'production',
            'branches': {'schema_version': 1, 'validation': [
                {'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product']},
                {'name': 'quick', 'gate': 'tests', 'kinds': ['smoke']},
                {'name': 'scratch', 'gate': 'none', 'kinds': []}],
                'production': [{'name': 'production', 'review': 'maintainer-manual'},
                               {'name': 'release', 'review': 'no'}]},
            'maintainers': [{'login': 'test-human', 'id': 101}], 'publisher_app_id': 201, 'writer_app_id': 202}


def pr(base, sha=PUSHED, state='open', head=HEAD):
    return {'state': state, 'head': {'sha': head, 'ref': 'feature'}, 'base': {'ref': base, 'sha': sha, 'repo': {'id': 77}}}


def contents(data):
    return {'type': 'file', 'encoding': 'base64', 'content': base64.b64encode(json.dumps(data).encode()).decode()}


def job(workflow, name):
    """One job's text of a workflow."""
    rest = workflow.split(f'\n  {name}:\n', 1)[1]
    return re.split(r'\n  (?=[a-z])', rest, maxsplit=1)[0]


def inputs(workflow):
    """The workflow_dispatch input names a workflow declares."""
    block = workflow.split('\n    inputs:\n', 1)[1].split('\n\n', 1)[0]
    return set(re.findall(r'^      ([a-z_]+):$', block, re.M))


class DispatcherTests(unittest.TestCase):
    def setUp(self):
        self.local, self.remote = config(), config()
        self.responses = {PREFIX: {'id': 77, 'full_name': dispatcher.TARGET, 'default_branch': 'testing'},
                          PREFIX + '/git/ref/heads/production': {'object': {'sha': POLICY}}}
        for number, base in enumerate(BASES, 1):
            self.responses[f'{PREFIX}/pulls/{number}'] = pr(base)

    def comment(self, number, body, user=HUMAN, ident=55):
        self.responses[f'{PREFIX}/issues/comments/{ident}'] = {
            'id': ident, 'user': user, 'body': body, 'issue_url': f'https://api.github.com{PREFIX}/issues/{number}'}
        return {'action': 'created', 'issue': {'pull_request': {'url': 'present'}, 'number': number},
                'sender': user, 'comment': {'id': ident}}

    def run_dispatcher(self, kind, event, ref='refs/heads/testing', attempt='1'):
        self.responses[PREFIX + '/contents/factory/config.json?ref=' + POLICY] = contents(self.remote)
        self.calls = []
        def request(method, endpoint, body=None):
            self.calls.append((method, endpoint, body))
            if method == 'POST':
                return None
            if endpoint.endswith('/comments?per_page=100&page=1') and endpoint not in self.responses:
                return []
            if endpoint not in self.responses:
                raise AssertionError(endpoint)
            return copy.deepcopy(self.responses[endpoint])
        environment = {'FACTORY_EVENT': kind, 'FACTORY_REF': ref, 'GITHUB_EVENT_PATH': '/unused/event.json',
                       **({} if attempt is None else {'GITHUB_RUN_ATTEMPT': attempt})}
        with patch.dict(dispatcher.os.environ, environment, clear=True), \
                patch.object(dispatcher.Path, 'read_text', side_effect=[json.dumps(self.local), json.dumps(event)]), \
                patch.object(dispatcher, 'api', side_effect=request), contextlib.redirect_stdout(io.StringIO()):
            dispatcher.main()
        return [(endpoint.rsplit('/', 2)[-2], body) for method, endpoint, body in self.calls if method == 'POST']

    def test_route_table_for_every_event_and_target(self):
        m = dispatcher.branches.parse(config())
        pipeline = ('factory.yml', {'pr': '4', 'feedback_kind': 'none', 'feedback_id': '0'})
        check = ('factory-promotion.yml', {'pr': '4'})
        expected = {
            'update': {'testing': [pipeline], 'quick': [pipeline], 'production': [pipeline, check], 'release': [pipeline, check]},
            'production_push': {'production': [check], 'release': [check]},
            'dismissal': {'testing': [pipeline], 'production': [check], 'release': [check]},
            'review_request': {'testing': [('factory.yml', {'pr': '4', 'feedback_kind': 'issue_comment', 'feedback_id': '9'})],
                               'production': [('factory.yml', {'pr': '4', 'review_request': '9', 'head': HEAD})]},
            'bypass': {base: [('factory.yml', {'pr': '4', 'bypass': '9', 'head': HEAD})] for base in ('testing', 'quick')} | {
                base: [('factory.yml', {'pr': '4', 'bypass': '9', 'head': HEAD}),
                       ('factory-promotion.yml', {'pr': '4', 'bypass': '9', 'head': HEAD})]
                for base in ('production', 'release')},
            'issue_comment': {'testing': [('factory.yml', {'pr': '4', 'feedback_kind': 'issue_comment', 'feedback_id': '9'})]},
            'review': {'testing': [('factory.yml', {'pr': '4', 'feedback_kind': 'review', 'feedback_id': '9'})],
                       'production': [check], 'release': [check]},
            'review_comment': {'testing': [('factory.yml', {'pr': '4', 'feedback_kind': 'review_comment', 'feedback_id': '9'})],
                               'production': [check], 'release': [check]}}
        for kind, routes in expected.items():
            for base in BASES:
                with self.subTest(kind=kind, base=base):
                    self.assertEqual(dispatcher.route(m, base, 4, kind, '9', HEAD), routes.get(base, []))

    def test_pr_updates_dispatch_by_target_on_the_config_branch(self):
        for number, base in enumerate(BASES, 1):
            with self.subTest(base=base):
                posts = self.run_dispatcher('pull_request_target', {'pull_request': {'number': number}})
                workflows = [workflow for workflow, _ in posts]
                self.assertEqual(workflows, {'testing': ['factory.yml'], 'quick': ['factory.yml'],
                                             'production': ['factory.yml', 'factory-promotion.yml'],
                                             'release': ['factory.yml', 'factory-promotion.yml']}.get(base, []))
                self.assertTrue(all(body['ref'] == 'production' for _, body in posts))

    def test_closed_or_foreign_pr_is_ignored(self):
        self.responses[PREFIX + '/pulls/1'] = pr('testing', state='closed')
        self.assertEqual(self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}}), [])
        self.responses[PREFIX + '/pulls/1'] = {**pr('testing'), 'base': {'ref': 'testing', 'repo': {'id': 78}}}
        self.assertEqual(self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}}), [])

    def test_config_branch_must_name_itself_or_a_finished_change_is_followed_once(self):
        release = {**config(), 'config_branch': 'release'}
        self.responses[PREFIX + '/git/ref/heads/release'] = {'object': {'sha': RELEASE}}
        self.responses[PREFIX + '/contents/factory/config.json?ref=' + RELEASE] = contents(release)
        # production's configuration names release, whose own configuration names itself: follow it.
        self.remote = release
        posts = self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})
        self.assertEqual([(w, body['ref']) for w, body in posts], [('factory.yml', 'release')])
        # The policy is the followed branch's tip: runs bound to it are current, never cancelled.
        with patch.object(dispatcher.Path, 'read_text', return_value=json.dumps(self.local)), \
                patch.object(dispatcher, 'api', side_effect=lambda method, endpoint, body=None: copy.deepcopy(self.responses[endpoint])):
            followed, model, policy = dispatcher.trusted_config()
        self.assertEqual((followed, model.config_branch, policy), (release, 'release', RELEASE))
        for named in ('production', 'quick'):
            with self.subTest(release_names=named):
                self.responses[PREFIX + '/contents/factory/config.json?ref=' + RELEASE] = contents({**config(), 'config_branch': named})
                with self.assertRaisesRegex(dispatcher.branches.Blocked, 'names the config branch release, whose own '
                                            'configuration does not name itself'):
                    self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})
                self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
        # Only a listed production branch is followed, and never more than one hop.
        for named in ('quick', 'feature-x'):
            with self.subTest(named=named):
                self.remote = {**config(), 'config_branch': named}
                with self.assertRaisesRegex(dispatcher.branches.Blocked, 'config_branch must be a production branch'):
                    self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})
                self.assertFalse(any(endpoint.endswith('/heads/' + named) for _, endpoint, _ in self.calls))
        # The followed configuration passes the repository and maintainer checks itself.
        self.remote = release
        for change in ({'repository': 'other/repo'}, {'maintainers': []}):
            with self.subTest(change=change):
                self.responses[PREFIX + '/contents/factory/config.json?ref=' + RELEASE] = contents({**release, **change})
                with self.assertRaisesRegex(RuntimeError, 'verified repository and maintainers required'):
                    self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})
        del self.responses[PREFIX + '/git/ref/heads/release']  # The followed branch is missing on GitHub.
        with self.assertRaises(AssertionError):
            self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
        self.assertFalse(any(endpoint.endswith('/pulls/1') for _, endpoint, _ in self.calls))
        # The configuration is read from the config branch tip, never from the checkout.
        self.remote = config()
        self.local['branches']['validation'][0]['gate'] = 'none'
        self.assertEqual([w for w, _ in self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})], ['factory.yml'])
        self.local['config_branch'] = 'bad/name'
        with self.assertRaises(RuntimeError):
            self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})

    def test_wrong_ref_or_repository_identity_fails(self):
        for kind, ref in (('pull_request_target', 'refs/heads/production'), ('workflow_dispatch', 'refs/heads/attacker'),
                          ('issue_comment', 'refs/heads/feature')):
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                self.run_dispatcher(kind, {'pull_request': {'number': 1}}, ref=ref)
        self.responses[PREFIX]['default_branch'] = 'quick'
        with self.assertRaisesRegex(RuntimeError, 'default branch'):
            self.run_dispatcher('pull_request_target', {'pull_request': {'number': 1}})

    def test_maintainer_comments_route_commands_and_feedback_without_forwarding_bodies(self):
        cases = [('testing', 'NEVER FORWARD BODY', [('factory.yml', {'pr': '1', 'feedback_kind': 'issue_comment', 'feedback_id': '55'})]),
                 ('quick', 'please look', []), ('production', 'please look', []),
                 ('production', '/review', [('factory.yml', {'pr': '4', 'review_request': '55', 'head': HEAD})]),
                 ('release', '/review now', []),
                 ('testing', '/review', [('factory.yml', {'pr': '1', 'feedback_kind': 'issue_comment', 'feedback_id': '55'})]),
                 ('testing', '/reviewer please', [('factory.yml', {'pr': '1', 'feedback_kind': 'issue_comment', 'feedback_id': '55'})]),
                 ('testing', '/bypass flaky runner', [('factory.yml', {'pr': '1', 'bypass': '55', 'head': HEAD})]),
                 ('quick', '/bypass flaky runner', [('factory.yml', {'pr': '2', 'bypass': '55', 'head': HEAD})]),
                 ('production', '/bypass hotfix', [('factory.yml', {'pr': '4', 'bypass': '55', 'head': HEAD}),
                                                   ('factory-promotion.yml', {'pr': '4', 'bypass': '55', 'head': HEAD})]),
                 ('scratch', '/bypass reason', []), ('feature-x', '/bypass reason', [])]
        for base, body, expected in cases:
            with self.subTest(base=base, body=body):
                number = BASES.index(base) + 1
                posts = self.run_dispatcher('issue_comment', self.comment(number, body))
                self.assertEqual([(workflow, data['inputs']) for workflow, data in posts], expected)
                self.assertTrue(all(data['ref'] == 'production' for _, data in posts))
                self.assertNotIn(body, json.dumps([data for _, data in posts]))

    def test_commands_carry_the_head_the_dispatcher_read(self):
        self.responses[PREFIX + '/pulls/4'] = pr('production', head='e' * 40)
        for body in ('/review', '/bypass hotfix'):
            with self.subTest(body=body):
                posts = self.run_dispatcher('issue_comment', self.comment(4, body))
                self.assertTrue(posts and all(data['inputs']['head'] == 'e' * 40 for _, data in posts), posts)
        for head in ('', 'E' * 40, 'e' * 39, None):
            with self.subTest(head=head):
                self.responses[PREFIX + '/pulls/4'] = pr('production', head=head)
                with self.assertRaisesRegex(RuntimeError, 'Invalid PR head identifier'):
                    self.run_dispatcher('issue_comment', self.comment(4, '/bypass hotfix'))
                self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))

    def test_edited_commands_never_repeat_but_edited_feedback_counts(self):
        event = {**self.comment(4, '/bypass old reason'), 'action': 'edited'}
        self.assertEqual(self.run_dispatcher('issue_comment', event), [])
        event = {**self.comment(4, '/review'), 'action': 'edited'}
        self.assertEqual(self.run_dispatcher('issue_comment', event), [])
        event = {**self.comment(1, 'clarified question'), 'action': 'edited'}
        self.assertEqual([w for w, _ in self.run_dispatcher('issue_comment', event)], ['factory.yml'])

    def test_a_rerun_never_repeats_a_command_but_other_events_still_dispatch(self):
        for base, body in (('production', '/review'), ('production', '/bypass hotfix'), ('testing', '/bypass flaky'),
                           ('testing', '/review')):
            for attempt in ('2', '10', '', None):
                with self.subTest(base=base, body=body, attempt=attempt):
                    event = self.comment(BASES.index(base) + 1, body)
                    with self.assertRaisesRegex(RuntimeError, 'a re-run never repeats a command; post a new comment'):
                        self.run_dispatcher('issue_comment', event, attempt=attempt)
                    self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
                    self.assertFalse(any(endpoint.startswith(PREFIX + '/pulls/') for _, endpoint, _ in self.calls))
        # The same commands dispatch on the first attempt; every other event keeps working on a re-run.
        self.assertEqual([w for w, _ in self.run_dispatcher('issue_comment', self.comment(4, '/bypass hotfix'))],
                         ['factory.yml', 'factory-promotion.yml'])
        self.assertEqual(self.run_dispatcher('issue_comment', self.comment(1, 'clarified question'), attempt='2'),
                         [('factory.yml', {'ref': 'production', 'inputs': {'pr': '1', 'feedback_kind': 'issue_comment', 'feedback_id': '55'}})])
        self.assertEqual([w for w, _ in self.run_dispatcher('pull_request_target', {'pull_request': {'number': 4}}, attempt='3')],
                         ['factory.yml', 'factory-promotion.yml'])
        self.assertEqual(self.feedback(1, attempt='2')[0][1]['inputs']['feedback_kind'], 'review')
        self.responses[PREFIX + '/pulls/11'] = pr('quick')
        self.responses[f'{PREFIX}/pulls?state=open&base=quick&per_page=100&page=1'] = [{'number': 11}]
        self.assertEqual([w for w, _ in self.run_dispatcher('push', {'ref': 'refs/heads/quick', 'after': PUSHED},
                                                            ref='refs/heads/quick', attempt='2')], ['factory.yml'])

    def issue_comment(self, number, body, user=HUMAN, author=HUMAN, ident=66, pull=False):
        """A comment on issue `number`, opened by `author`, as the event and the API show it."""
        self.responses[f'{PREFIX}/issues/comments/{ident}'] = {
            'id': ident, 'user': user, 'body': body, 'issue_url': f'https://api.github.com{PREFIX}/issues/{number}'}
        self.responses[f'{PREFIX}/issues/{number}'] = {'number': number, 'user': author, **({'pull_request': {}} if pull else {})}
        return {'action': 'created', 'issue': {'number': number}, 'sender': user, 'comment': {'id': ident}}

    def test_issue_commands_of_maintainers_on_maintainer_issues_dispatch_the_issue_jobs(self):
        self.remote['issue_review_model'] = 'claude-sonnet-5-5'
        declared = inputs((ROOT / '.github/workflows/factory.yml').read_text())
        for body, word in (('/review', 'review'), ('/accept', 'accept'), ('/accept looks right', 'accept'),
                           ('looks good', None), ('/reviewer', None), ('/bypass now', None), (' /accept', None)):
            with self.subTest(body=body):
                posts = self.run_dispatcher('issue_comment', self.issue_comment(57, body))
                expected = [('factory.yml', {'ref': 'production', 'inputs': {'issue': '57', 'issue_command': word,
                                                                             'comment': '66'}})] if word else []
                self.assertEqual(posts, expected)
                self.assertTrue(all(set(data['inputs']) <= declared for _, data in posts))
                self.assertNotIn(body.strip(), json.dumps([data for _, data in posts]).replace('"accept"', '').replace('"review"', ''))

    def test_issue_commands_are_ignored_where_they_do_not_apply(self):
        self.remote['issue_review_model'] = 'claude-sonnet-5-5'
        self.assertEqual(self.run_dispatcher('issue_comment', self.issue_comment(57, '/review', author=STRANGER)), [])
        self.assertEqual(self.run_dispatcher('issue_comment', self.issue_comment(57, '/review', author={**HUMAN, 'type': 'Bot'})), [])
        self.assertEqual(self.run_dispatcher('issue_comment', {**self.issue_comment(57, '/accept'), 'action': 'edited'}), [])
        posts = self.run_dispatcher('issue_comment', self.issue_comment(57, '/review', user=STRANGER))
        self.assertEqual(posts, [])
        self.assertFalse(any('/issues/' in endpoint for _, endpoint, _ in self.calls))
        with self.assertRaisesRegex(RuntimeError, 'a re-run never repeats a command'):
            self.run_dispatcher('issue_comment', self.issue_comment(57, '/accept'), attempt='2')
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))
        event = self.issue_comment(57, '/accept')
        self.responses[f'{PREFIX}/issues/comments/66']['issue_url'] = f'https://api.github.com{PREFIX}/issues/58'
        with self.assertRaisesRegex(RuntimeError, 'issue association failed'):
            self.run_dispatcher('issue_comment', event)

    def test_issue_commands_wait_until_the_config_branch_enables_them(self):
        # Before the promotion that brings the issue jobs, the config branch's factory.yml would refuse the inputs.
        self.assertNotIn('issue_review_model', self.remote)
        self.assertEqual(self.run_dispatcher('issue_comment', self.issue_comment(57, '/review')), [])
        self.assertFalse(any('/issues/' in endpoint for _, endpoint, _ in self.calls))

    def test_non_maintainer_and_bot_comments_are_ignored(self):
        for user in (STRANGER, {'type': 'Bot', 'id': 201, 'login': 'factory[bot]'}, {**HUMAN, 'login': 'impostor'}):
            with self.subTest(user=user['login']):
                posts = self.run_dispatcher('issue_comment', self.comment(4, '/bypass because', user=user))
                self.assertEqual(posts, [])
                self.assertFalse(any('/issues/comments/' in endpoint for _, endpoint, _ in self.calls))

    def test_forged_comment_author_or_pr_association_fails(self):
        event = self.comment(4, '/bypass because')
        self.responses[PREFIX + '/issues/comments/55']['user'] = STRANGER
        with self.assertRaises(RuntimeError):
            self.run_dispatcher('issue_comment', event)
        event = self.comment(4, '/bypass because')
        self.responses[PREFIX + '/issues/comments/55']['issue_url'] = f'https://api.github.com{PREFIX}/issues/1'
        with self.assertRaises(RuntimeError):
            self.run_dispatcher('issue_comment', event)
        self.assertFalse(any(method == 'POST' for method, _, _ in self.calls))

    def feedback(self, number, kind='pull_request_review', actor=HUMAN, author=HUMAN, state='APPROVED', pull=None, attempt='1'):
        self.responses[PREFIX + '/actions/runs/70'] = {
            'actor': actor, 'workflow_id': 6, 'repository': {'id': 77}, 'event': kind,
            'display_title': f'factory-feedback:{number}:{kind}:88'}
        self.responses[PREFIX + '/actions/workflows/6'] = {'path': '.github/workflows/factory-feedback.yml'}
        endpoint = f'{PREFIX}/pulls/{number}/reviews/88' if kind == 'pull_request_review' else f'{PREFIX}/pulls/comments/88'
        self.responses[endpoint] = {'user': author, 'state': state,
                                    'pull_request_url': f'https://api.github.com{PREFIX}/pulls/{pull or number}'}
        return self.run_dispatcher('workflow_run', {'workflow_run': {'id': 70}}, attempt=attempt)

    def test_review_feedback_reruns_full_gates_and_production_checks_only(self):
        self.assertEqual(self.feedback(1), [('factory.yml', {'ref': 'production', 'inputs': {'pr': '1', 'feedback_kind': 'review', 'feedback_id': '88'}})])
        self.assertEqual(self.feedback(1, 'pull_request_review_comment')[0][1]['inputs']['feedback_kind'], 'review_comment')
        self.assertEqual(self.feedback(4), [('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': '4'}})])
        self.assertEqual(self.feedback(5), [('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': '5'}})])
        for number in (2, 3, 6):
            with self.subTest(base=BASES[number - 1]):
                self.assertEqual(self.feedback(number), [])
        self.assertEqual(self.feedback(4, actor=STRANGER), [])
        with self.assertRaises(RuntimeError):
            self.feedback(4, author=STRANGER)

    def test_a_dismissal_reruns_the_production_check_or_the_full_gate_pipeline(self):
        other = {'type': 'User', 'id': 102, 'login': 'second-human'}
        self.remote['maintainers'] = self.local['maintainers'] = [{'login': 'test-human', 'id': 101}, {'login': 'second-human', 'id': 102}]
        # Maintainer test-human dismisses second-human's approval: the dismisser acts, not the review's author.
        for author in (other, STRANGER, {'type': 'Bot', 'id': 5, 'login': 'some[bot]'}):
            with self.subTest(author=author['login']):
                self.assertEqual(self.feedback(4, author=author, state='DISMISSED'),
                                 [('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': '4'}})])
                self.assertEqual(self.feedback(5, author=author, state='DISMISSED'),
                                 [('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': '5'}})])
        # A full gate re-reads its feedback with the plain pipeline update (a pending review is bound to it); the
        # dismissed review is never forwarded as feedback. Nothing for other targets.
        for author in (other, STRANGER):
            with self.subTest(full_gate_author=author['login']):
                self.assertEqual(self.feedback(1, author=author, state='DISMISSED'), [
                    ('factory.yml', {'ref': 'production', 'inputs': {'pr': '1', 'feedback_kind': 'none', 'feedback_id': '0'}})])
        for number in (2, 3, 6):
            with self.subTest(base=BASES[number - 1]):
                self.assertEqual(self.feedback(number, author=other, state='DISMISSED'), [])
        self.assertEqual(self.feedback(1, actor=STRANGER, author=other, state='DISMISSED'), [])
        # The dismisser must be a configured maintainer, and the review must belong to this PR.
        self.assertEqual(self.feedback(4, actor=STRANGER, author=other, state='DISMISSED'), [])
        with self.assertRaisesRegex(RuntimeError, 'different pull request'):
            self.feedback(4, author=other, state='DISMISSED', pull=5)
        # Any other review still needs its own author as the run actor.
        with self.assertRaisesRegex(RuntimeError, 'run actor'):
            self.feedback(4, author=other, state='CHANGES_REQUESTED')

    def test_feedback_ingress_subscribes_to_dismissals(self):
        workflow = (ROOT / '.github/workflows/factory-feedback.yml').read_text()
        self.assertIn('  pull_request_review:\n', workflow)
        self.assertIn('types: [submitted, edited, dismissed]', workflow)

    def test_dispatched_inputs_exist_and_the_jobs_pass_the_head_on(self):
        workflows = {name: (ROOT / '.github/workflows' / name).read_text() for name in ('factory.yml', 'factory-promotion.yml')}
        declared = {name: inputs(text) for name, text in workflows.items()}
        self.assertEqual(declared['factory-promotion.yml'], {'pr', 'bypass', 'head'})
        self.assertIn('head', declared['factory.yml'])
        m = dispatcher.branches.parse(config())
        sent = [(w, i) for kind in ('update', 'production_push', 'dismissal', 'review_request', 'bypass', 'issue_comment',
                                    'review', 'review_comment') for base in BASES for w, i in dispatcher.route(m, base, 4, kind, '9', HEAD)]
        for workflow, given in sent:
            self.assertLessEqual(set(given), declared[workflow], (workflow, given))
            if {'review_request', 'bypass'} & set(given):
                self.assertEqual(given['head'], HEAD)
        for workflow, name, command in (('factory.yml', 'review-request', 'engine.py review-request'),
                                        ('factory.yml', 'bypass', 'engine.py bypass'),
                                        ('factory-promotion.yml', 'production', 'promotion.py')):
            with self.subTest(job=name):
                text = job(workflows[workflow], name)
                self.assertIn('HEAD_SHA: ${{ inputs.head }}', text)
                self.assertRegex(text, r'python3 tools/factory/' + re.escape(command) + r' .*--head "\$HEAD_SHA"')
        self.assertEqual(workflows['factory.yml'].count('${{ inputs.head }}'), 2)

    def push(self, branch, prs, **event):
        self.responses[f'{PREFIX}/pulls?state=open&base={branch}&per_page=100&page=1'] = [{'number': n} for n in prs]
        return self.run_dispatcher('push', {'ref': 'refs/heads/' + branch, 'after': PUSHED, **event}, ref='refs/heads/' + branch)

    def test_push_to_a_gated_validation_branch_reruns_prs_on_the_pushed_tip(self):
        self.responses[PREFIX + '/pulls/11'] = pr('quick')
        self.responses[PREFIX + '/pulls/12'] = pr('quick', sha=OLD)
        posts = self.push('quick', [11, 12])
        self.assertEqual(posts, [('factory.yml', {'ref': 'production', 'inputs': {'pr': '11', 'feedback_kind': 'none', 'feedback_id': '0'}})])
        self.assertFalse(any(endpoint.startswith(PREFIX + '/issues/12/') for _, endpoint, _ in self.calls))

    def test_push_to_the_config_branch_reruns_every_gated_and_production_pr_once(self):
        listed = {'testing': [13], 'quick': [14, 13], 'scratch': [16], 'release': [15], 'feature-x': [17]}
        for base, numbers in listed.items():
            self.responses[f'{PREFIX}/pulls?state=open&base={base}&per_page=100&page=1'] = [{'number': n} for n in numbers]
        self.responses.update({PREFIX + '/pulls/11': pr('production'), PREFIX + '/pulls/12': pr('production', sha=OLD),
                               # The config tip moved, not their base: never skipped as behind the pushed tip.
                               PREFIX + '/pulls/13': pr('testing', sha=OLD), PREFIX + '/pulls/14': pr('quick', sha=OLD),
                               PREFIX + '/pulls/15': pr('release', sha=OLD)})
        posts = self.push('production', [11, 12])
        pipeline = lambda n: ('factory.yml', {'ref': 'production', 'inputs': {'pr': n, 'feedback_kind': 'none', 'feedback_id': '0'}})
        check = lambda n: ('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': n}})
        self.assertEqual(posts, [check('11'), check('12'), pipeline('13'), pipeline('14'), pipeline('15'), check('15')])
        listings = [endpoint for _, endpoint, _ in self.calls if '/pulls?' in endpoint]
        self.assertEqual([e.split('base=')[1].split('&')[0] for e in listings], ['production', 'testing', 'quick', 'release'])
        # Runs bound to the former config tip are cancelled before the fresh pipeline runs.
        self.assertTrue(all(any(e == f'{PREFIX}/issues/{n}/comments?per_page=100&page=1' for _, e, _ in self.calls)
                            for n in (13, 14, 15)))

    def test_push_to_another_production_or_validation_branch_reruns_only_its_own_prs(self):
        self.responses[PREFIX + '/pulls/15'] = pr('release')
        self.assertEqual(self.push('release', [15]), [('factory-promotion.yml', {'ref': 'production', 'inputs': {'pr': '15'}})])
        self.assertEqual([e for _, e, _ in self.calls if '/pulls?' in e], [f'{PREFIX}/pulls?state=open&base=release&per_page=100&page=1'])
        self.responses[PREFIX + '/pulls/13'] = pr('testing')
        self.assertEqual([w for w, _ in self.push('testing', [13])], ['factory.yml'])
        self.assertEqual([e for _, e, _ in self.calls if '/pulls?' in e], [f'{PREFIX}/pulls?state=open&base=testing&per_page=100&page=1'])

    def test_push_to_unlisted_ungated_or_deleted_branch_does_nothing(self):
        for branch in ('scratch', 'feature-x'):
            with self.subTest(branch=branch):
                self.assertEqual(self.push(branch, [1]), [])
                self.assertFalse(any('/pulls?' in endpoint for _, endpoint, _ in self.calls))
        self.assertEqual(self.push('testing', [1], deleted=True), [])
        with self.assertRaises(RuntimeError):
            self.push('testing', [1], after='not-a-sha')
        with self.assertRaises(RuntimeError):
            self.run_dispatcher('push', {'ref': 'refs/heads/testing', 'after': PUSHED}, ref='refs/heads/quick')

    def ledger(self, external_id, head_branch='production'):
        comment = {'performed_via_github_app': {'id': 201}, 'body': '<!-- factory-ledger:v1 -->\n{"check_id":8}'}
        self.responses.update({
            PREFIX + '/issues/4/comments?per_page=100&page=1': [comment, comment],
            PREFIX + '/check-runs/8': {'app': {'id': 201}, 'status': 'in_progress', 'external_id': external_id},
            # The run executes the config tip its binding names.
            PREFIX + '/actions/runs/9': {'status': 'in_progress', 'event': 'workflow_dispatch', 'head_sha': external_id.split(':')[3],
                                         'head_branch': head_branch, 'repository': {'full_name': dispatcher.TARGET}, 'workflow_id': 6},
            PREFIX + '/actions/workflows/6': {'path': '.github/workflows/factory.yml'}})
        calls = []
        def request(method, path, data=None):
            calls.append((method, path))
            return copy.deepcopy(self.responses.get(path))
        return calls, request

    def test_cancel_obsolete_parses_seven_field_bindings(self):
        head = 'a' * 40
        current = f'{dispatcher.TARGET}:4:{head}:{POLICY}:production:9:1'
        cases = [(current, pr('production', head=head), False),  # Title-only edit.
                 (current, pr('production', head='e' * 40), True),  # New head.
                 (f'{dispatcher.TARGET}:4:{head}:{OLD}:production:9:1', pr('production', head=head), True),  # Config tip moved.
                 (current, pr('release', head=head), True),  # Target changed.
                 (f'{dispatcher.TARGET}:4:{head}:{OLD}:9:1', pr('production', head='e' * 40), False)]  # Legacy never counts.
        for external_id, state, cancelled in cases:
            with self.subTest(external_id=external_id, base=state['base']['ref']):
                calls, request = self.ledger(external_id)
                with patch.object(dispatcher, 'api', side_effect=request):
                    dispatcher.cancel_obsolete(config(), 4, state, POLICY)
                self.assertEqual([p for m, p in calls if m == 'POST'], [PREFIX + '/actions/runs/9/cancel'] if cancelled else [])
        for external_id, branch in ((f'{dispatcher.TARGET}:4:{head}:{OLD}:production:9:1:extra', 'production'),
                                    (f'other/repo:4:{head}:{OLD}:production:9:1', 'production')):
            with self.subTest(external_id=external_id, branch=branch):
                calls, request = self.ledger(external_id, branch)
                with patch.object(dispatcher, 'api', side_effect=request), self.assertRaises(RuntimeError):
                    dispatcher.cancel_obsolete(config(), 4, pr('production', head='e' * 40), POLICY)
                self.assertFalse(any(m == 'POST' for m, _ in calls))

    def test_cancel_obsolete_skips_runs_on_another_config_branch_but_keeps_every_other_refusal(self):
        head, current = 'a' * 40, {**config(), 'config_branch': 'release'}  # production handed over to release
        old = f'{dispatcher.TARGET}:4:{head}:{OLD}:production:9:1'
        cancelled = lambda calls: [p for m, p in calls if m == 'POST']
        for branch, expected in (('production', []), ('testing', []), ('release', [PREFIX + '/actions/runs/9/cancel'])):
            with self.subTest(branch=branch):
                calls, request = self.ledger(old, branch)
                with patch.object(dispatcher, 'api', side_effect=request):
                    dispatcher.cancel_obsolete(current, 4, pr('production', head='e' * 40), RELEASE)
                self.assertEqual(cancelled(calls), expected)
                self.assertIn(('GET', PREFIX + '/actions/runs/9'), calls)
        for branch in ('production', 'release'):
            for change in ({'event': 'push'}, {'head_sha': RELEASE}, {'repository': {'full_name': 'other/repo'}}, 'workflow'):
                with self.subTest(branch=branch, change=change):
                    calls, request = self.ledger(old, branch)
                    if change == 'workflow':
                        self.responses[PREFIX + '/actions/workflows/6'] = {'path': '.github/workflows/factory-dispatch.yml'}
                    else:
                        self.responses[PREFIX + '/actions/runs/9'].update(change)
                    with patch.object(dispatcher, 'api', side_effect=request), \
                            self.assertRaisesRegex(RuntimeError, 'Refuse to cancel an unverified workflow'):
                        dispatcher.cancel_obsolete(current, 4, pr('production', head='e' * 40), RELEASE)
                    self.assertEqual(cancelled(calls), [])

    def test_dispatcher_names_no_branch_literal(self):
        source = (ROOT / '.github/scripts/dispatch_factory.py').read_text()
        # Branch names come from the config branch; "production" alone is the level name of the model.
        retired = [name for name in dispatcher.branches.RESERVED if name != 'head']  # 'head' is a PR field.
        for name in retired + ['testing']:
            for quote in ('"', "'"):
                self.assertFalse(quote + name + quote in source, name)
        for name in retired + ['testing', 'production']:
            self.assertFalse('refs/heads/' + name in source, name)


if __name__ == '__main__':
    unittest.main()
