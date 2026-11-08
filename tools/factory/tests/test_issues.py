"""Work-order issues: authentic records, maintainer commands, the pinned approval and the one work-order reader."""
import json
import re
import unittest

from factory_testlib import BOT, DRAFT, LATER, STRANGER, IssueHub, candidate_config, user
import contracts
import issues
from contracts import Blocked


class Records(unittest.TestCase):
    def setUp(self):
        self.config = candidate_config()
        self.hub = IssueHub(self.config)
        self.hub.issue()

    def test_only_unedited_publisher_app_records_of_this_issue_count(self):
        data = {'issue': 57, 'text_sha256': 'a' * 64, 'command': 1, 'run_id': 1}
        good = self.hub.record(57, issues.FINDINGS, data)
        self.assertEqual(issues.record(good, self.config, 57, issues.FINDINGS), {'id': good['id'], 'data': data})
        self.assertIsNone(issues.record(good, self.config, 57, issues.REVIEW))  # another marker
        self.assertIsNone(issues.record(good, self.config, 58, issues.FINDINGS))  # another issue
        forged = [self.hub.record(57, issues.FINDINGS, data, app=12345),  # another App
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x')),  # a maintainer, no App
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), BOT, None),
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), self.hub.maintainer, self.hub.app),
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), BOT, self.hub.app, edited=True),
                  self.hub.comment(57, 'Quoted:\n' + issues.record_body(issues.FINDINGS, data, 'x'), BOT, self.hub.app),
                  self.hub.comment(57, issues.FINDINGS + '\n<!-- {"issue":57} -->\n', BOT, self.hub.app),
                  self.hub.comment(57, issues.FINDINGS + '\n<!-- not json -->\n', BOT, self.hub.app),
                  self.hub.record(57, issues.FINDINGS, {**data, 'issue': 58})]
        for comment in forged:
            with self.subTest(body=comment['body'][:60], app=comment.get('performed_via_github_app')):
                self.assertIsNone(issues.record(comment, self.config, 57, issues.FINDINGS))
        self.assertEqual([r['id'] for r in issues.records(self.hub.comments, self.config, 57, issues.FINDINGS)], [good['id']])

    def test_record_values_cannot_close_the_html_comment(self):
        body = issues.record_body(issues.REVIEW, {'issue': 57, 'text_sha256': 'a' * 64, 'kind': 'factory',
                                                  'allowed_paths': ['a-->b', '<x>&'], 'command': 1, 'run_id': 1}, 'text')
        line = body.split('\n')[1]
        self.assertEqual(line.count('-->'), 1)
        self.assertTrue(line.endswith(' -->') and '<x>' not in line)
        self.assertEqual(json.loads(line[5:-4])['allowed_paths'], ['a-->b', '<x>&'])
        with self.assertRaises(Blocked):
            issues.record_body(issues.REVIEW, {'issue': 57}, 'missing fields never reach GitHub')

    def test_commands_need_an_unedited_maintainer_comment_on_this_issue(self):
        cases = [('/accept', {}, 'accept'), ('/review please', {}, 'review'), ('/accept\nthanks', {}, 'accept'),
                 ('/accepted', {}, None), (' /accept', {}, None), ('please /accept', {}, None),
                 ('/accept', {'edited': True}, None), ('/accept', {'author': STRANGER}, None),
                 ('/accept', {'author': BOT, 'app': 5510081}, None)]
        for body, options, expected in cases:
            with self.subTest(body=body, options=options):
                self.assertEqual(issues.command(self.hub.comment(57, body, **options), self.config, 57), expected)
        on_other_issue = self.hub.comment(58, '/accept')
        self.assertIsNone(issues.command(on_other_issue, self.config, 57))
        self.assertIsNone(issues.command(self.hub.comment(57, '/review'), self.config, 57, 'accept'))


class Approval(unittest.TestCase):
    def setUp(self):
        self.config = candidate_config()
        self.hub = IssueHub(self.config)
        self.issue = self.hub.issue()

    def test_an_accepted_issue_is_an_approved_work_order_with_a_pin(self):
        record = self.hub.approve(paths=('docs/', 'tools/factory/issues.py'))
        order = issues.approved(self.hub, self.config, 57)
        self.assertEqual(order['spec'], {'status': 'approved', 'kind': 'factory', 'allowed_paths': ['docs/', 'tools/factory/issues.py']})
        self.assertEqual((order['task'], order['record'], order['sha256']), ('#57', record['id'], issues.text_sha256(self.issue)))
        self.assertTrue(order['text'].startswith('# #57 – CSV export\n\n'))
        self.assertEqual(issues.pin_of(order), {'issue': 57, 'sha256': order['sha256'], 'record': record['id']})
        self.assertEqual(issues.work_order(self.hub, self.config, '#57', 'p' * 40), (order['text'], order['spec'], issues.pin_of(order)))

    def test_every_edit_withdraws_the_approval(self):
        self.hub.approve()
        for field, value in (('body', self.issue['body'] + '\nmore scope'), ('title', 'CSV export and PDF'),
                             ('body', self.issue['body'].replace('\n', '\r\n'))):
            with self.subTest(field=field):
                original = self.issue[field]
                self.issue[field] = value
                with self.assertRaisesRegex(Blocked, 'was edited after its approval; comment /review and /accept again'):
                    issues.approved(self.hub, self.config, 57)
                self.issue[field] = original
        issues.approved(self.hub, self.config, 57)

    def test_a_status_written_by_hand_approves_nothing(self):
        self.issue['body'] = issues.with_block(self.issue['body'], {'status': 'approved', 'kind': 'factory', 'allowed_paths': ['docs/']})
        with self.assertRaisesRegex(Blocked, 'is not an approved work order'):
            issues.approved(self.hub, self.config, 57)
        # A record from another App, an edited record or one by a maintainer account counts neither.
        reviewed = issues.text_sha256(self.issue)
        data = {'issue': 57, 'text_sha256': reviewed, 'reviewed_sha256': reviewed, 'review': 1, 'kind': 'factory',
                'allowed_paths': ['docs/'], 'run_id': 1, 'accepted_by': [{'login': 'ftrutschnig', 'id': 306226744, 'comment': 1}]}
        self.hub.record(57, issues.APPROVAL, data, app=4242)
        self.hub.comment(57, issues.record_body(issues.APPROVAL, data, 'x'), BOT, self.hub.app, edited=True)
        self.hub.comment(57, issues.record_body(issues.APPROVAL, data, 'x'))
        with self.assertRaisesRegex(Blocked, 'is not an approved work order'):
            issues.approved(self.hub, self.config, 57)

    def test_the_issue_itself_must_still_qualify(self):
        self.hub.approve()
        cases = [('state', 'closed', 'is closed; reopen it'), ('user', STRANGER, 'not opened by a configured maintainer'),
                 ('pull_request', {'url': 'x'}, 'is a pull request'),
                 ('repository_url', 'https://api.github.com/repos/someone/fork', 'belongs to another repository')]
        for key, value, message in cases:
            with self.subTest(key=key):
                original = self.issue.get(key)
                self.issue[key] = value
                with self.assertRaisesRegex(Blocked, message):
                    issues.approved(self.hub, self.config, 57)
                if original is None:
                    del self.issue[key]
                else:
                    self.issue[key] = original
        issues.approved(self.hub, self.config, 57)  # reopening an unchanged issue restores it

    def test_accept_comments_are_read_again(self):
        self.hub.approve()
        accept = next(c for c in self.hub.comments if c['body'] == '/accept')
        accept['updated_at'] = LATER
        with self.assertRaisesRegex(Blocked, 'was edited or deleted'):
            issues.approved(self.hub, self.config, 57)
        self.hub.comments.remove(accept)
        with self.assertRaisesRegex(Blocked, 'was edited or deleted'):
            issues.approved(self.hub, self.config, 57)

    def test_an_accept_by_a_former_maintainer_or_too_few_accounts_does_not_count(self):
        self.issue = self.hub.issue(author=user(self.config['maintainers'][1]))
        self.hub.approve()  # accepted by maintainers[0], who then leaves
        former = candidate_config(maintainers=self.config['maintainers'][1:], work_order_approvals=1)
        with self.assertRaisesRegex(Blocked, 'no maintainer any more'):
            issues.approved(self.hub, former, 57)
        with self.assertRaisesRegex(Blocked, 'fewer /accept than work_order_approvals'):
            issues.approved(self.hub, candidate_config(work_order_approvals=2), 57)

    def test_two_accounts_satisfy_two_approvals(self):
        second = user(self.config['maintainers'][1])
        self.hub.approve(accepters=[self.hub.maintainer, second])
        issues.approved(self.hub, candidate_config(work_order_approvals=2), 57)

    def test_a_record_that_does_not_match_the_block_counts_nothing(self):
        self.hub.approve(paths=('docs/',))
        self.issue['body'] = issues.with_block(self.issue['body'], {'status': 'approved', 'kind': 'factory', 'allowed_paths': ['tools/']})
        record = next(c for c in self.hub.comments if c['body'].startswith(issues.APPROVAL))
        data = json.loads(record['body'].split('\n')[1][5:-4])
        record['body'] = issues.record_body(issues.APPROVAL, {**data, 'text_sha256': issues.text_sha256(self.issue)}, 'x')
        with self.assertRaisesRegex(Blocked, 'does not match its factory-task block'):
            issues.approved(self.hub, self.config, 57)

    def test_a_pin_goes_stale_when_the_issue_is_accepted_again(self):
        self.hub.approve()
        pin = issues.pin_of(issues.approved(self.hub, self.config, 57))
        self.assertEqual(issues.pinned(self.hub, self.config, pin)['task'], '#57')
        self.issue['body'] += '\nAC-2: more.'
        self.hub.approve()
        with self.assertRaisesRegex(Blocked, 'changed since this run'):
            issues.pinned(self.hub, self.config, pin)


class Readers(unittest.TestCase):
    def test_files_are_read_at_the_config_tip_and_need_no_pin(self):
        class Files:
            def text(self, repo, path, sha):
                self.read = (repo, path, sha)
                return '```factory-task\n{"status":"approved","kind":"smoke","allowed_paths":["x/"]}\n```'
        config, gh = candidate_config(), Files()
        text, spec, pin = issues.work_order(gh, config, 'docs/work/FACTORY-008.md', 'p' * 40)
        self.assertEqual((spec['kind'], pin, gh.read), ('smoke', None, (config['repository'], 'docs/work/FACTORY-008.md', 'p' * 40)))
        self.assertEqual(issues.text_for(gh, config, 'fixture/repo', 'docs/work/X.md', 'q' * 40, None), text)
        for task in ('57', '#0', '#57a', 'docs/work/../x.md', None, 57):
            with self.subTest(task=task), self.assertRaises(Blocked):
                issues.work_order(gh, config, task, 'p' * 40)

    def test_session_reads_issues_through_the_maintainers_github_only(self):
        import session
        config = candidate_config()
        hub = IssueHub(config)
        hub.issue()
        hub.approve(paths=('docs/',))
        text, spec, pin = session.work_order(config, 'p' * 40, '#57', hub)
        self.assertEqual((text, spec, pin), issues.work_order(hub, config, '#57', 'p' * 40))
        self.assertEqual((spec['allowed_paths'], pin['issue']), (['docs/'], 57))
        self.assertTrue(text.startswith('# #57 – CSV export'))
        self.assertEqual(session.order_source(config, 'p' * 40, '#57', text)['url'],
                         f"https://github.com/{config['repository']}/issues/57")
        with self.assertRaisesRegex(Blocked, 'needs GitHub access'):
            session.work_order(config, 'p' * 40, '#57')
        hub.issues[57]['body'] += '\nchanged'
        with self.assertRaisesRegex(Blocked, 'edited after its approval'):
            session.work_order(config, 'p' * 40, '#57', hub)

    def test_a_work_order_file_is_read_from_the_trusted_checkout_when_one_is_given(self):
        class NoGitHub:
            def text(self, *args):
                raise AssertionError('read from GitHub although a trusted checkout was given')
        read = []
        order = '# FACTORY-SMOKE\n```factory-task\n{"status":"approved","kind":"smoke","allowed_paths":["x/"]}\n```\n'
        text, spec, pin = issues.work_order(NoGitHub(), candidate_config(), 'docs/work/FACTORY-SMOKE.md', 'p' * 40,
                                            lambda path: read.append(path) or order)
        self.assertEqual((text, spec, pin, read), (order, {'status': 'approved', 'kind': 'smoke', 'allowed_paths': ['x/']}, None,
                                                   ['docs/work/FACTORY-SMOKE.md']))
        for task in ('docs/work/../x.md', 'docs/work/sub/X.md', 'README.md'):
            with self.subTest(task=task), self.assertRaisesRegex(Blocked, 'invalid work-order reference'):
                issues.work_order(NoGitHub(), candidate_config(), task, 'p' * 40, lambda path: order)
        with self.assertRaisesRegex(Blocked, 'task not approved'):
            issues.work_order(NoGitHub(), candidate_config(), 'docs/work/X.md', 'p' * 40, lambda path: order.replace('approved', 'draft'))

    def test_product_work_orders_need_the_approved_north_star_and_product_checks(self):
        ready = {'northstar_path': 'AICEPEAK_NORDSTERN.md', 'northstar_approved': True, 'product_checks_ready': True}
        self.assertTrue(issues.product_allowed(candidate_config(**ready)))
        for change in ({'product_checks_ready': False}, {'product_checks_ready': 'true'}, {'product_checks_ready': None},
                       {'northstar_approved': 1}, {'northstar_approved': False}, {'northstar_path': ''}, {'northstar_path': None}):
            with self.subTest(change=change):
                self.assertFalse(issues.product_allowed(candidate_config(**{**ready, **change})))
        product = '```factory-task\n{"status":"approved","kind":"product","allowed_paths":["src/"]}\n```\n'
        blocked, allowed = candidate_config(**{**ready, 'product_checks_ready': False}), candidate_config(**ready)
        self.assertEqual(issues.work_order(None, allowed, 'docs/work/P.md', 'p' * 40, lambda path: product)[1]['kind'], 'product')
        with self.assertRaisesRegex(Blocked, '^' + re.escape(issues.PRODUCT_BLOCKED) + '$'):
            issues.work_order(None, blocked, 'docs/work/P.md', 'p' * 40, lambda path: product)
        # An approved issue of kind product is refused the same way.
        hub = IssueHub(blocked)
        hub.issue(body=DRAFT.replace('"kind":"factory"', '"kind":"product"'))
        hub.approve(kind='product')
        with self.assertRaisesRegex(Blocked, 'product work orders stay blocked'):
            issues.work_order(hub, blocked, '#57', 'p' * 40)
        self.assertEqual(issues.work_order(hub, allowed, '#57', 'p' * 40)[1]['kind'], 'product')

    def test_handoff_names_an_issue_or_a_file(self):
        config = candidate_config(runners=['claude'])
        owner = config['maintainers'][0]['login']
        for task in ('#57', '#1', 'docs/work/FACTORY-009.md'):
            body = '```factory-handoff\n' + json.dumps({'runner': 'claude', 'task': task, 'owner': owner}) + '\n```'
            self.assertEqual(contracts.handoff(body, config)['task'], task)
        for task in ('57', '#0', '#057', '# 57', '#1234567890', 'issue-57', 7):
            with self.subTest(task=task), self.assertRaises(Blocked):
                contracts.handoff('```factory-handoff\n' + json.dumps({'runner': 'claude', 'task': task, 'owner': owner}) + '\n```', config)
        with self.assertRaisesRegex(Blocked, 'handoff fields'):
            contracts.handoff('```factory-handoff\n["runner","task","owner"]\n```', config)

    def test_draft_blocks_follow_the_gate_rules_with_any_status(self):
        self.assertEqual(issues.draft_spec(DRAFT), {'status': 'draft', 'kind': 'factory', 'allowed_paths': []})
        bad = ['no block', DRAFT * 2, '```factory-task\n{"status":"draft"}\n```',
               '```factory-task\n{"status":"","kind":"factory","allowed_paths":[]}\n```',
               '```factory-task\n{"status":"draft","kind":"other","allowed_paths":[]}\n```',
               '```factory-task\n{"status":"draft","kind":"factory","allowed_paths":["../x"]}\n```',
               '```factory-task\n{"status":"draft","kind":"factory","allowed_paths":[1]}\n```',
               '```factory-task\nnot json\n```']
        for text in bad:
            with self.subTest(text=text[:50]), self.assertRaises(Blocked):
                issues.draft_spec(text)

    def test_only_the_block_changes(self):
        text = 'Before\r\n\r\n```factory-task\r\n{"status":"draft","kind":"factory","allowed_paths":[]}\r\n```\r\nAfter ``` code\n'
        changed = issues.with_block(text, {'status': 'approved', 'kind': 'factory', 'allowed_paths': ['docs/']})
        self.assertEqual(issues.draft_spec(changed)['allowed_paths'], ['docs/'])
        self.assertEqual(issues.without_block(changed), issues.without_block(text))
        self.assertNotEqual(issues.without_block(changed + 'x'), issues.without_block(text))

    def test_the_issue_reviewer_needs_its_model_and_limits(self):
        config = candidate_config()
        self.assertEqual(issues.config_problems(config), [])
        self.assertEqual(issues.config_problems({k: v for k, v in config.items() if k != 'issue_review_model'}),
                         ['issue_review_model must name a Claude model'])
        broken = candidate_config(issue_review_model='gpt-6', limits={**config['limits'], 'max_issue_reviews': 0})
        del broken['limits']['issue_review_output_tokens']
        self.assertEqual(issues.config_problems(broken), [
            'issue_review_model must name a Claude model', 'limits.max_issue_reviews must be a whole number from 1 to 20',
            'limits.issue_review_output_tokens must be a whole number from 1000 to 32000'])


if __name__ == '__main__':
    unittest.main()
