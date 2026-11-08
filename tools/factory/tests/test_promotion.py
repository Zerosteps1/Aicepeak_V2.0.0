"""Production check classification with the real promotion.py; GitHub is replaced at its client."""
import argparse
import contextlib
import copy
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.parse import unquote

from factory_testlib import DISPATCHER, FIXTURE_REPO as REPO, ROOT, STRANGER
import promotion
from contracts import Blocked, binding

HEAD, PRODUCTION, RELEASE, OTHER = 'a' * 40, 'b' * 40, 'c' * 40, 'd' * 40
ALICE = {'type': 'User', 'id': 101, 'login': 'alice'}
BOB = {'type': 'User', 'id': 102, 'login': 'Bob'}
ENV = {'GITHUB_REF': 'refs/heads/production', 'GITHUB_SHA': PRODUCTION, 'GITHUB_RUN_ID': '9', 'GITHUB_RUN_ATTEMPT': '1'}
POSTED, COMMITTED = '2026-11-01T10:00:00Z', '2026-11-01T09:59:00Z'


def senior(ident=30, pr=5, policy=PRODUCTION, base='production', **changes):
    """A publisher-App AI review check run on HEAD, bound to a PR, config tip and target."""
    check = {'id': ident, 'app': {'id': 7}, 'name': 'factory/senior-review', 'head_sha': HEAD, 'status': 'completed',
             'conclusion': 'success', 'external_id': f'{REPO}:{pr}:{HEAD}:{policy}:{base}:3:1'}
    check.update(changes)
    return check


def config():
    return {'repository': REPO, 'default_branch': 'testing', 'config_branch': 'production', 'publisher_app_id': 7,
            'branches': {'schema_version': 1, 'validation': [
                {'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product']},
                {'name': 'quick', 'gate': 'tests', 'kinds': ['smoke']},
                {'name': 'scratch', 'gate': 'none', 'kinds': []}],
                'production': [{'name': 'production', 'review': 'maintainer-manual'},
                               {'name': 'release', 'review': 'no'}]},
            'maintainers': [{'login': 'alice', 'id': 101}, {'login': 'bob', 'id': 102}], 'work_order_approvals': 2}


class FakeGitHub:
    def __init__(self):
        self.tips = {'production': PRODUCTION, 'release': RELEASE, 'testing': HEAD, 'quick': OTHER, 'scratch': HEAD}
        self.pr = {'number': 5, 'state': 'open', 'draft': False, 'changed_files': 1,
                   'head': {'sha': HEAD, 'ref': 'testing', 'repo': {'full_name': REPO}},
                   'base': {'ref': 'production', 'sha': PRODUCTION}}
        self.compare = {'status': 'ahead', 'behind_by': 0}
        self.open = [{'number': 5, 'head': {'ref': 'testing', 'repo': {'full_name': REPO}}}]
        self.files = [{'filename': 'tools/factory/engine.py'}]
        self.reviews, self.comments, self.posted, self.calls = [], {}, [], []
        self.checks = [senior()]  # The AI review of this promotion passed.
        self.committed, self.actor = COMMITTED, DISPATCHER
        self.recheck = None  # Changes the world after the check has judged the PR.

    def request(self, method, path, data=None):
        self.calls.append((method, path))
        prefix = '/repos/' + REPO
        if method == 'POST' and path == prefix + '/check-runs':
            self.posted.append(copy.deepcopy(data))
            return {'id': 500 + len(self.posted)}
        assert method == 'GET', (method, path)
        if path == prefix + '/pulls/5':
            if sum(p == path for _, p in self.calls) == 2 and self.recheck:
                self.recheck(self)
            return copy.deepcopy(self.pr)
        if path.startswith(prefix + '/git/ref/heads/'):
            return {'object': {'sha': self.tips[path.rsplit('/', 1)[1]]}}
        if path == f"{prefix}/compare/{self.pr['base']['sha']}...{HEAD}?per_page=1":
            return dict(self.compare)
        if path.startswith(prefix + '/issues/comments/'):
            return copy.deepcopy(self.comments[int(path.rsplit('/', 1)[1])])
        if path == f'{prefix}/commits/{HEAD}':
            return {'sha': HEAD, 'commit': {'committer': {'date': self.committed}}}
        if path == f'{prefix}/actions/runs/9':
            return {'id': 9, 'triggering_actor': copy.deepcopy(self.actor)}
        raise AssertionError(path)

    def pages(self, path, field=None):
        self.calls.append(('PAGES', path))
        prefix = '/repos/' + REPO
        if path == prefix + f"/pulls?state=open&base={self.pr['base']['ref']}":
            return copy.deepcopy(self.open)
        if path == prefix + '/pulls/5/files':
            return copy.deepcopy(self.files)
        if path == prefix + '/pulls/5/reviews':
            return copy.deepcopy(self.reviews)
        query = f'{prefix}/commits/{HEAD}/check-runs?check_name='
        if path.startswith(query) and path.endswith('&filter=all&app_id=7'):
            name = unquote(path[len(query):-len('&filter=all&app_id=7')])
            return copy.deepcopy([c for c in self.checks if c['head_sha'] == HEAD and c['name'] == name])
        raise AssertionError(path)


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()

    def judge(self, bypass=0, env=None, value=None, head=HEAD):
        """Every judgement publishes exactly one check; that check is returned."""
        with patch.object(promotion, 'installation', return_value=self.gh):
            promotion.run(argparse.Namespace(pr=5, bypass_comment=bypass, head=head), value or config(), env or ENV)
        self.assertEqual(len(self.gh.posted), 1)
        return self.gh.posted[-1]

    def comment(self, body, user=ALICE, number=5, ident=55, edited=None):
        self.gh.comments[ident] = {'id': ident, 'user': user, 'body': body, 'created_at': POSTED, 'updated_at': edited or POSTED,
                                   'issue_url': f'https://api.github.com/repos/{REPO}/issues/{number}'}
        return ident

    def assertRefused(self, check, *reasons):
        self.assertEqual(check['conclusion'], 'failure')
        for reason in reasons:
            self.assertIn(reason, check['output']['summary'])

    def test_config_ref_is_checked_before_any_other_action(self):
        for ref in ('refs/heads/testing', 'refs/heads/release', None):
            with self.subTest(ref=ref), patch.object(promotion, 'installation', side_effect=AssertionError('no credential')):
                with self.assertRaisesRegex(Blocked, 'config branch'):
                    promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), config(), {**ENV, 'GITHUB_REF': ref})

    def test_current_unique_complete_promotion_passes_with_seven_field_binding(self):
        check = self.judge()
        self.assertEqual((check['name'], check['head_sha'], check['status'], check['conclusion']),
                         ('factory/production/production', HEAD, 'completed', 'success'))
        self.assertEqual(check['output']['title'], 'Promotion of testing')
        snapshot = {'repository': REPO, 'pr': 5, 'head_sha': HEAD, 'policy_sha': PRODUCTION, 'base_ref': 'production',
                    'run_id': 9, 'run_attempt': 1}
        self.assertEqual(check['external_id'], binding(snapshot))
        self.assertEqual(check['external_id'].split(':')[4], 'production')
        self.assertNotIn('bypass', json.loads(check['output']['text']))
        # A tests gate is promotable too.
        self.gh = FakeGitHub()
        self.gh.pr['head'].update(ref='quick', sha=HEAD)
        self.gh.tips['quick'] = HEAD
        self.gh.open[0]['head']['ref'] = 'quick'
        self.assertEqual(self.judge()['conclusion'], 'success')

    def test_promotion_failure_reasons(self):
        def stale_tip(gh): gh.tips['testing'] = OTHER
        def gate_none(gh):
            gh.pr['head']['ref'] = 'scratch'
            gh.open[0]['head']['ref'] = 'scratch'
        def behind(gh): gh.compare = {'status': 'diverged', 'behind_by': 2}
        def second(gh): gh.open.append({'number': 6, 'head': {'ref': 'quick', 'repo': {'full_name': REPO}}})
        for change, reason in ((stale_tip, 'the head is not the current tip of testing'),
                               (gate_none, 'scratch has gate none'),
                               (behind, 'production is not contained in the head; run `factory promote testing --to production`'),
                               (second, 'another promotion into production is open: #6')):
            with self.subTest(reason=reason):
                self.gh = FakeGitHub()
                change(self.gh)
                check = self.judge()
                self.assertRefused(check, reason)
                self.assertEqual(check['output']['title'], f"Promotion of {self.gh.pr['head']['ref']} refused")

    def test_not_contained_names_the_target_when_several_production_branches_are_listed(self):
        single = config()
        single['branches']['production'] = single['branches']['production'][:1]
        for target, value, remedy in (('production', config(), '`factory promote testing --to production`'),
                                      ('release', config(), '`factory promote testing --to release`'),
                                      ('production', single, '`factory promote testing`')):
            with self.subTest(target=target, production=len(value['branches']['production'])):
                self.gh = FakeGitHub()
                self.gh.pr['base'] = {'ref': target, 'sha': self.gh.tips[target]}
                self.gh.compare = {'status': 'diverged', 'behind_by': 2}
                self.assertRefused(self.judge(value=value), f'{target} is not contained in the head; run {remedy}')

    def test_feature_and_fork_prs_do_not_count_as_promotions(self):
        self.gh.open += [{'number': 6, 'head': {'ref': 'feature', 'repo': {'full_name': REPO}}},
                         {'number': 7, 'head': {'ref': 'quick', 'repo': {'full_name': 'someone/fork'}}},
                         {'number': 8, 'head': {'ref': 'quick', 'repo': None}}]
        self.assertEqual(self.judge()['conclusion'], 'success')
        # A fork's branch named like a validation branch is no promotion: it is judged by its files.
        self.gh = FakeGitHub()
        self.gh.pr['head']['repo'] = {'full_name': 'someone/fork'}
        self.assertRefused(self.judge(), promotion.REFUSED)

    def test_valid_bypass_passes_exactly_a_failing_promotion_head(self):
        self.gh.tips['testing'] = OTHER
        check = self.judge(self.comment('/bypass  release\nfreeze   window'))
        self.assertEqual(check['conclusion'], 'success')
        self.assertEqual(check['head_sha'], HEAD)
        self.assertEqual(check['output']['title'], 'Bypassed by alice')
        self.assertEqual(check['output']['summary'], 'release freeze window')
        self.assertEqual(json.loads(check['output']['text']),
                         {'bypass': {'login': 'alice', 'id': 101, 'comment_id': 55, 'reason': 'release freeze window'}})
        self.assertEqual(len(check['external_id'].split(':')), 7)

    def test_bypass_login_is_the_configured_maintainer_spelling(self):
        self.gh.tips['testing'] = OTHER
        check = self.judge(self.comment('/bypass ok', user=BOB))
        self.assertEqual(json.loads(check['output']['text'])['bypass']['login'], 'bob')

    def test_invalid_bypass_is_refused(self):
        cases = [(dict(body='/bypass reason', user=STRANGER), 'not by a configured maintainer'),
                 (dict(body='/bypass reason', user={**ALICE, 'login': 'mallory'}), 'not by a configured maintainer'),
                 (dict(body='/bypass reason', user={**ALICE, 'type': 'Bot'}), 'not by a configured maintainer'),
                 (dict(body='/bypass reason', number=6), 'another PR'),
                 (dict(body='/bypass'), 'reason'), (dict(body='/bypass   \n '), 'reason'),
                 (dict(body='/bypassed reason'), 'reason'), (dict(body='please /bypass reason'), 'reason'),
                 (dict(body='/bypass ' + 'x' * 501), 'at most 500')]
        for kwargs, reason in cases:
            with self.subTest(**{k: str(v)[:40] for k, v in kwargs.items()}):
                self.gh = FakeGitHub()
                self.gh.tips['testing'] = OTHER
                check = self.judge(self.comment(**kwargs))
                self.assertRefused(check, 'the head is not the current tip of testing', 'bypass refused', reason)
        self.gh = FakeGitHub()
        self.gh.tips['testing'] = OTHER
        self.assertEqual(self.judge(self.comment('/bypass ' + 'x' * 500))['conclusion'], 'success')

    def bypass_check(self, **changes):
        check = {'id': 40, 'app': {'id': 7}, 'name': 'factory/production/production', 'head_sha': HEAD,
                 'status': 'completed', 'conclusion': 'success',
                 'external_id': f'{REPO}:5:{HEAD}:{PRODUCTION}:production:8:1',
                 'output': {'text': json.dumps({'bypass': {'login': 'alice', 'id': 101, 'comment_id': 55, 'reason': 'r'}})}}
        check.update(changes)
        return check

    def test_an_earlier_bypass_for_the_same_head_survives_a_rerun(self):
        self.gh.tips['testing'] = OTHER
        self.comment('/bypass release freeze')
        self.gh.checks = [self.bypass_check()]
        check = self.judge()
        self.assertEqual(check['output']['title'], 'Bypassed by alice')
        self.assertIn(':9:1', check['external_id'])  # Bound to this run, not the earlier one.

    def test_earlier_bypass_does_not_carry_to_another_head_policy_target_app_or_malformed_binding(self):
        for change in ({'head_sha': OTHER}, {'external_id': f'{REPO}:5:{HEAD}:{OTHER}:production:8:1'},
                       {'external_id': f'{REPO}:5:{HEAD}:{PRODUCTION}:release:8:1'},
                       {'external_id': f'{REPO}:6:{HEAD}:{PRODUCTION}:production:8:1'},
                       {'external_id': f'{REPO}:5:{HEAD}:{PRODUCTION}:8:1'}, {'app': {'id': 8}},
                       {'conclusion': 'failure'}, {'output': {'text': '{"production": {}}'}}):
            with self.subTest(change=change):
                self.gh = FakeGitHub()
                self.gh.tips['testing'] = OTHER
                self.comment('/bypass release freeze')
                self.gh.checks = [self.bypass_check(**change)]
                self.assertRefused(self.judge(), 'the head is not the current tip of testing')
        # A deleted or rewritten comment does not bypass.
        self.gh = FakeGitHub()
        self.gh.tips['testing'] = OTHER
        self.comment('just a note')
        self.gh.checks = [self.bypass_check()]
        self.assertRefused(self.judge(), 'the head is not the current tip of testing')

    def config_pr(self, *paths, renames=()):
        self.gh.pr['head'].update(ref='ftrutschnig/config-add-qa')
        self.gh.files = [{'filename': p} for p in paths] + [{'filename': new, 'previous_filename': old} for old, new in renames]
        self.gh.pr['changed_files'] = len(self.gh.files)

    def review(self, user, state='APPROVED', commit=HEAD, ident=None):
        self.gh.reviews.append({'id': ident or 100 + len(self.gh.reviews), 'user': user, 'state': state, 'commit_id': commit})

    def test_config_pr_needs_two_maintainer_accounts_at_the_head(self):
        self.config_pr('docs/work/FACTORY-009.md', 'factory/config.json')
        self.review(ALICE)
        check = self.judge()
        self.assertRefused(check, 'Needs approving reviews by 2 maintainer accounts', 'approved by: alice')
        self.assertEqual(check['output']['title'], 'Work-order/config PR')
        self.gh.posted.clear()
        self.review(BOB)
        check = self.judge()
        self.assertEqual(check['conclusion'], 'success')
        self.assertEqual(json.loads(check['output']['text']), {'production': {'kind': 'work-order', 'approvals': ['alice', 'bob']}})

    def test_work_order_approvals_sets_how_many_maintainer_accounts_approve(self):
        self.config_pr('docs/work/FACTORY-009.md')
        one = {**config(), 'work_order_approvals': 1}
        check = self.judge(value=one)
        self.assertRefused(check, 'Needs approving reviews by 1 maintainer account at', 'approved by: nobody')
        self.gh.posted.clear()
        self.review(BOB)
        check = self.judge(value=one)
        self.assertEqual((check['conclusion'], json.loads(check['output']['text'])),
                         ('success', {'production': {'kind': 'work-order', 'approvals': ['bob']}}))
        # The number is required: a configuration without it, or with more than there are maintainers, judges nothing.
        for value in ({k: v for k, v in config().items() if k != 'work_order_approvals'}, {**config(), 'work_order_approvals': 3}):
            with self.subTest(value=value.get('work_order_approvals')), \
                    patch.object(promotion, 'installation', side_effect=AssertionError('no credential')), \
                    self.assertRaisesRegex(Blocked, 'work_order_approvals must be a whole number from 1 to the number of maintainers'):
                promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), value, ENV)

    def test_approvals_that_do_not_count(self):
        cases = {'same account twice': [(ALICE,), (ALICE,)],
                 'stale approval': [(ALICE,), (BOB, 'APPROVED', OTHER)],
                 'non-maintainer': [(ALICE,), (STRANGER,)],
                 'id with another login': [(ALICE,), ({**BOB, 'login': 'mallory'},)],
                 'bot': [(ALICE,), ({**BOB, 'type': 'Bot'},)],
                 'later change request': [(ALICE,), (BOB,), (BOB, 'CHANGES_REQUESTED')],
                 'dismissed': [(ALICE,), (BOB, 'DISMISSED')],
                 'approved at an older head, then commented': [(ALICE,), (BOB, 'APPROVED', OTHER), (BOB, 'COMMENTED')]}
        for name, reviews in cases.items():
            with self.subTest(name):
                self.gh = FakeGitHub()
                self.config_pr('docs/work/FACTORY-009.md')
                for review in reviews:
                    self.review(*review)
                self.assertRefused(self.judge(), 'approved by: alice')
        self.gh = FakeGitHub()
        self.config_pr('docs/work/FACTORY-009.md')
        self.review(BOB, 'CHANGES_REQUESTED', ident=1)
        self.review(ALICE, ident=2)
        self.review(BOB, ident=3)
        self.review(BOB, 'COMMENTED', ident=4)  # A comment does not withdraw a decision.
        self.assertEqual(self.judge()['conclusion'], 'success')

    def test_bypass_never_applies_to_config_or_other_prs(self):
        ident = self.comment('/bypass urgent')
        self.config_pr('docs/work/FACTORY-009.md')
        self.review(ALICE)
        check = self.judge(ident)
        self.assertRefused(check, 'Needs approving reviews', '`/bypass` does not apply')
        self.assertNotIn('bypass', json.loads(check['output']['text']))
        self.assertFalse(any('/issues/comments/' in path for _, path in self.gh.calls))
        self.gh = FakeGitHub()
        ident = self.comment('/bypass urgent')
        self.gh.pr['head']['ref'] = 'feature'
        check = self.judge(ident)
        self.assertRefused(check, promotion.REFUSED, '`/bypass` does not apply')
        self.assertEqual(check['output']['title'], 'Refused')

    def test_anything_else_is_refused(self):
        self.assertEqual(promotion.REFUSED, 'only promotions and config PRs may target a production branch')
        cases = [(['docs/work/FACTORY-009.md', 'README.md'], ()), (['docs/work/sub/FACTORY-009.md'], ()),
                 (['docs/work/FACTORY-009.txt'], ()), (['factory/config.json.bak'], ()), ([], ()),
                 ([], (('tools/factory/engine.py', 'docs/work/FACTORY-009.md'),)),
                 ([], (('docs/work/FACTORY-009.md', 'docs/FACTORY-009.md'),))]
        for paths, renames in cases:
            with self.subTest(paths=paths, renames=renames):
                self.gh = FakeGitHub()
                self.config_pr(*paths, renames=renames)
                self.review(ALICE)
                self.review(BOB)
                self.assertRefused(self.judge(), promotion.REFUSED)
        self.gh = FakeGitHub()
        self.config_pr(renames=(('docs/work/OLD.md', 'docs/work/NEW.md'),))
        self.review(ALICE)
        self.review(BOB)
        self.assertEqual(self.judge()['conclusion'], 'success')

    def test_incomplete_file_list_publishes_nothing(self):
        self.config_pr('docs/work/FACTORY-009.md')
        self.gh.pr['changed_files'] = 2
        with patch.object(promotion, 'installation', return_value=self.gh), self.assertRaisesRegex(Blocked, 'incomplete'):
            promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), config(), ENV)
        self.assertEqual(self.gh.posted, [])

    def test_stale_tips_publish_nothing(self):
        def head(gh): gh.pr['head']['sha'] = OTHER
        def base(gh): gh.tips['production'] = OTHER
        def lagging(gh): gh.pr['base']['sha'] = OTHER
        def target(gh): gh.pr['base']['ref'] = 'release'
        def closed(gh): gh.pr['state'] = 'closed'
        def draft(gh): gh.pr['draft'] = True
        for change in (head, base, lagging, target, closed, draft):
            with self.subTest(change.__name__):
                self.gh = FakeGitHub()
                self.gh.recheck = change
                with patch.object(promotion, 'installation', return_value=self.gh), self.assertRaisesRegex(Blocked, 'nothing published'):
                    promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), config(), ENV)
                self.assertEqual(self.gh.posted, [])
        # The config tip moved after dispatch: this run's policy is stale.
        self.gh = FakeGitHub()
        with patch.object(promotion, 'installation', return_value=self.gh), self.assertRaisesRegex(Blocked, 'stale policy'):
            promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), config(), {**ENV, 'GITHUB_SHA': OTHER})
        self.assertEqual(self.gh.posted, [])

    def test_non_config_production_target_binds_its_own_tip_and_check(self):
        self.gh.pr['base'] = {'ref': 'release', 'sha': RELEASE}
        self.gh.open[0]['head']['ref'] = 'testing'
        check = self.judge()
        self.assertEqual((check['name'], check['conclusion']), ('factory/production/release', 'success'))
        self.assertEqual(check['external_id'], f'{REPO}:5:{HEAD}:{PRODUCTION}:release:9:1')
        self.assertIn(('GET', f'/repos/{REPO}/compare/{RELEASE}...{HEAD}?per_page=1'), self.gh.calls)

    def test_only_open_prs_into_production_branches_are_judged(self):
        for change in ({'base': {'ref': 'testing', 'sha': HEAD}}, {'base': {'ref': 'feature', 'sha': HEAD}}, {'state': 'closed'}):
            with self.subTest(change=change):
                self.gh = FakeGitHub()
                self.gh.pr.update(change)
                with patch.object(promotion, 'installation', return_value=self.gh), self.assertRaises(Blocked):
                    promotion.run(argparse.Namespace(pr=5, bypass_comment=0, head=''), config(), ENV)
                self.assertEqual(self.gh.posted, [])

    def test_draft_fails_without_classification(self):
        self.gh.pr['draft'] = True
        check = self.judge(self.comment('/bypass now'))
        self.assertEqual((check['conclusion'], check['output']['title']), ('failure', 'Draft PR'))

    def test_reads_are_bounded_and_cli_reports_blocked(self):
        self.judge()
        self.assertLessEqual(len(self.gh.calls), 12)
        self.assertTrue(all(path.endswith(('/files', '/reviews')) or '/pulls?state=open&base=' in path or '/check-runs?' in path
                            for kind, path in self.gh.calls if kind == 'PAGES'))
        stderr = io.StringIO()
        with patch.dict(os.environ, {**ENV, 'GITHUB_REF': 'refs/heads/testing'}, clear=True), \
                patch.object(promotion, 'installation', side_effect=AssertionError('no credential')), \
                contextlib.redirect_stderr(stderr):
            self.assertEqual(promotion.main(['--pr', '5']), 1)
        self.assertIn('factory jobs must run on the config branch', stderr.getvalue())

    def test_workflow_runs_on_the_config_branch_with_the_publisher_key_only(self):
        workflow = (ROOT / '.github/workflows/factory-promotion.yml').read_text()
        self.assertIn('environment: factory-promotion', workflow)
        self.assertEqual(workflow.count('secrets.'), 1)
        self.assertIn('secrets.FACTORY_PUBLISHER_APP_PRIVATE_KEY', workflow)
        self.assertIn('contents: read', workflow)
        self.assertNotIn('write', workflow)
        self.assertIn('python3 tools/factory/promotion.py --pr "$PR_NUMBER" --bypass-comment', workflow)
        self.assertIn('--head "$HEAD_SHA"', workflow)
        self.assertIn('HEAD_SHA: ${{ inputs.head }}', workflow)

    def test_promotion_into_maintainer_manual_needs_a_passed_review_bound_to_this_pr(self):
        cases = {'missing': ([], 'the AI review of this head is missing: a maintainer comments `/review` (a review that passed since '
                                 'needs only a re-run of this check: `gh workflow run factory-promotion.yml --repo fixture/repo '
                                 '--ref production -f pr=5`)'),
                 'another PR on the same commit': ([senior(pr=6)], 'is missing'),
                 'another target': ([senior(base='release')], 'is missing'),
                 'an older config tip': ([senior(policy=OTHER)], 'is missing'),
                 'a binding without the target': ([senior(external_id=f'{REPO}:5:{HEAD}:{PRODUCTION}:3:1')], 'is missing'),
                 'another App': ([senior(app={'id': 8})], 'is missing'),
                 'in progress': ([senior(status='in_progress', conclusion=None)], 'awaiting the local AI review'),
                 'failed': ([senior(conclusion='failure')], 'the AI review did not pass'),
                 'newer failure': ([senior(ident=30), senior(ident=31, conclusion='failure')], 'the AI review did not pass'),
                 'newer request': ([senior(ident=30), senior(ident=31, status='in_progress', conclusion=None)], 'awaiting')}
        for name, (checks, reason) in cases.items():
            with self.subTest(name):
                self.gh = FakeGitHub()
                self.gh.checks = checks
                check = self.judge()
                self.assertRefused(check, reason)
                self.assertEqual(json.loads(check['output']['text'])['production']['problems'], [check['output']['summary']])
        # A passed review of this PR counts even when another PR's review on the same commit is newer.
        self.gh = FakeGitHub()
        self.gh.checks = [senior(ident=30), senior(ident=31, pr=6, conclusion='failure'), senior(ident=29, conclusion='failure')]
        check = self.judge()
        self.assertEqual(check['conclusion'], 'success')
        self.assertIn('its AI review passed', check['output']['summary'])
        self.assertIn(('PAGES', f'/repos/{REPO}/commits/{HEAD}/check-runs?check_name=factory%2Fsenior-review&filter=all&app_id=7'),
                      self.gh.calls)

    def test_review_is_judged_only_after_the_promotion_conditions_and_only_where_required(self):
        self.gh.checks = []
        self.gh.tips['testing'] = OTHER
        check = self.judge()
        self.assertRefused(check, 'the head is not the current tip of testing')
        self.assertNotIn('AI review', check['output']['summary'])
        for review in ('initiated', 'no'):
            with self.subTest(review=review):
                self.gh = FakeGitHub()
                self.gh.checks = []
                value = config()
                value['branches']['production'][0]['review'] = review
                self.assertEqual(self.judge(value=value)['conclusion'], 'success')
                self.assertFalse(any('senior-review' in path for _, path in self.gh.calls))

    def test_a_valid_bypass_overrides_a_missing_or_failed_review(self):
        for checks in ([], [senior(conclusion='failure')]):
            with self.subTest(checks=len(checks)):
                self.gh = FakeGitHub()
                self.gh.checks = checks
                check = self.judge(self.comment('/bypass reviewed by hand'))
                self.assertEqual((check['conclusion'], check['output']['title']), ('success', 'Bypassed by alice'))

    def test_a_promotion_whose_diff_holds_only_work_orders_stays_a_promotion(self):
        self.gh.files = [{'filename': 'docs/work/FACTORY-009.md'}, {'filename': 'factory/config.json'}]
        self.gh.pr['changed_files'] = 2
        self.review(ALICE)
        self.review(BOB)
        self.gh.tips['testing'] = OTHER
        check = self.judge(self.comment('/bypass release freeze'))
        self.assertEqual((check['conclusion'], check['output']['title']), ('success', 'Bypassed by alice'))
        self.assertFalse(any(path.endswith('/files') or path.endswith('/reviews') for _, path in self.gh.calls))

    def test_config_pr_into_maintainer_manual_needs_no_ai_review(self):
        self.gh.checks = []
        self.config_pr('docs/work/FACTORY-009.md', 'factory/config.json')
        self.review(ALICE)
        self.review(BOB)
        check = self.judge()
        self.assertEqual(check['conclusion'], 'success')
        self.assertFalse(any('check-runs?' in path for _, path in self.gh.calls))

    def refused_bypass(self, reason, **kwargs):
        """A promotion with a problem: the bypass is refused for `reason` and the check fails."""
        self.gh.tips['testing'] = OTHER
        check = self.judge(**kwargs)
        self.assertRefused(check, 'the head is not the current tip of testing', 'bypass refused', reason)
        self.assertNotIn('bypass', json.loads(check['output']['text']))

    def test_an_edited_bypass_comment_never_bypasses(self):
        self.refused_bypass('the command comment was edited; post a new comment',
                            bypass=self.comment('/bypass reason', edited='2026-11-01T10:05:00Z'))
        # Nor is an earlier bypass whose comment was edited afterwards re-honoured.
        self.gh = FakeGitHub()
        self.gh.tips['testing'] = OTHER
        self.comment('/bypass release freeze', edited='2026-11-01T10:05:00Z')
        self.gh.checks = [self.bypass_check()]
        self.assertRefused(self.judge(), 'the head is not the current tip of testing')

    def test_a_bypass_for_another_head_is_refused(self):
        for head in (OTHER, '', HEAD[:12], HEAD.upper()):
            with self.subTest(head=head):
                self.gh = FakeGitHub()
                self.refused_bypass('the PR head changed after the command; post a new `/bypass`',
                                    bypass=self.comment('/bypass reason'), head=head)

    def test_a_head_newer_than_the_bypass_comment_is_refused(self):
        self.gh.committed = '2026-11-01T10:00:01Z'
        self.refused_bypass('the head is newer than the `/bypass` comment; post a new `/bypass`', bypass=self.comment('/bypass reason'))
        # Offsets are compared as moments, not as text.
        self.gh = FakeGitHub()
        self.gh.committed = '2026-11-01T11:00:00+02:00'
        self.gh.tips['testing'] = OTHER
        self.assertEqual(self.judge(self.comment('/bypass reason'))['conclusion'], 'success')
        self.gh = FakeGitHub()
        self.gh.committed = POSTED
        self.gh.tips['testing'] = OTHER
        self.assertEqual(self.judge(self.comment('/bypass reason'))['conclusion'], 'success')

    def test_a_bypass_run_started_by_another_account_is_refused(self):
        for actor in (STRANGER, BOB, {**ALICE, 'login': 'mallory'}, {**DISPATCHER, 'type': 'User'},
                      {'type': 'Bot', 'id': 5, 'login': 'factory-publisher[bot]'}):
            with self.subTest(actor=actor['login']):
                self.gh = FakeGitHub()
                self.gh.actor = actor
                self.refused_bypass('started by the dispatcher or by the author of the comment', bypass=self.comment('/bypass reason'))
        # The comment's own author may dispatch it.
        self.gh = FakeGitHub()
        self.gh.actor = ALICE
        self.gh.tips['testing'] = OTHER
        self.assertEqual(self.judge(self.comment('/bypass reason'))['conclusion'], 'success')

    def test_a_rerun_attempt_never_reuses_a_bypass(self):
        ident = self.comment('/bypass reason')
        self.gh.tips['testing'] = OTHER
        with patch.object(promotion, 'installation', side_effect=AssertionError('no credential')), \
                self.assertRaisesRegex(Blocked, 'dispatch a fresh /bypass'):
            promotion.run(argparse.Namespace(pr=5, bypass_comment=ident, head=HEAD), config(), {**ENV, 'GITHUB_RUN_ATTEMPT': '2'})
        self.assertEqual(self.gh.posted, [])
        # A re-run without a bypass is an ordinary production check.
        self.assertRefused(self.judge(env={**ENV, 'GITHUB_RUN_ATTEMPT': '2'}), 'the head is not the current tip of testing')

    def test_command_line_passes_the_head(self):
        with patch.object(promotion, 'run', return_value={}) as called, patch.object(promotion, 'load_config', return_value={}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(promotion.main(['--pr', '5', '--bypass-comment', '55', '--head', HEAD]), 0)
        self.assertEqual((called.call_args.args[0].bypass_comment, called.call_args.args[0].head), (55, HEAD))


if __name__ == '__main__':
    unittest.main()
