"""Work-order issues (FACTORY-009): authentic records, maintainer commands and the pinned approval."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import branch_fixture  # noqa: E402
import contracts  # noqa: E402
import issue_fixture  # noqa: E402
import issues  # noqa: E402
from contracts import Blocked  # noqa: E402


def fixture_config(**changes):
    config = branch_fixture.load(ROOT)
    config.update(changes)
    return config


class Records(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()
        self.hub = issue_fixture.IssueHub(self.config)
        self.hub.issue()

    def test_only_unedited_publisher_app_records_of_this_issue_count(self):
        data = {'issue': 57, 'text_sha256': 'a' * 64, 'command': 1, 'run_id': 1}
        good = self.hub.record(57, issues.FINDINGS, data)
        self.assertEqual(issues.record(good, self.config, 57, issues.FINDINGS), {'id': good['id'], 'data': data})
        self.assertIsNone(issues.record(good, self.config, 57, issues.REVIEW))  # another marker
        self.assertIsNone(issues.record(good, self.config, 58, issues.FINDINGS))  # another issue
        forged = [self.hub.record(57, issues.FINDINGS, data, app=12345),  # another App
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x')),  # a maintainer, no App
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), issue_fixture.BOT, None),
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), self.hub.maintainer, self.hub.app),
                  self.hub.comment(57, issues.record_body(issues.FINDINGS, data, 'x'), issue_fixture.BOT, self.hub.app, edited=True),
                  self.hub.comment(57, 'Quoted:\n' + issues.record_body(issues.FINDINGS, data, 'x'), issue_fixture.BOT, self.hub.app),
                  self.hub.comment(57, issues.FINDINGS + '\n<!-- {"issue":57} -->\n', issue_fixture.BOT, self.hub.app),
                  self.hub.comment(57, issues.FINDINGS + '\n<!-- not json -->\n', issue_fixture.BOT, self.hub.app),
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
                 ('/accept', {'edited': True}, None), ('/accept', {'author': issue_fixture.STRANGER}, None),
                 ('/accept', {'author': issue_fixture.BOT, 'app': 5510081}, None)]
        for body, options, expected in cases:
            with self.subTest(body=body, options=options):
                self.assertEqual(issues.command(self.hub.comment(57, body, **options), self.config, 57), expected)
        on_other_issue = self.hub.comment(58, '/accept')
        self.assertIsNone(issues.command(on_other_issue, self.config, 57))
        self.assertIsNone(issues.command(self.hub.comment(57, '/review'), self.config, 57, 'accept'))


class Approval(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()
        self.hub = issue_fixture.IssueHub(self.config)
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
        self.hub.comment(57, issues.record_body(issues.APPROVAL, data, 'x'), issue_fixture.BOT, self.hub.app, edited=True)
        self.hub.comment(57, issues.record_body(issues.APPROVAL, data, 'x'))
        with self.assertRaisesRegex(Blocked, 'is not an approved work order'):
            issues.approved(self.hub, self.config, 57)

    def test_the_issue_itself_must_still_qualify(self):
        self.hub.approve()
        cases = [('state', 'closed', 'is closed; reopen it'), ('user', issue_fixture.STRANGER, 'not opened by a configured maintainer'),
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
        accept['updated_at'] = issue_fixture.LATER
        with self.assertRaisesRegex(Blocked, 'was edited or deleted'):
            issues.approved(self.hub, self.config, 57)
        self.hub.comments.remove(accept)
        with self.assertRaisesRegex(Blocked, 'was edited or deleted'):
            issues.approved(self.hub, self.config, 57)

    def test_an_accept_by_a_former_maintainer_or_too_few_accounts_does_not_count(self):
        self.issue = self.hub.issue(author=issue_fixture.user(self.config['maintainers'][1]))
        self.hub.approve()  # accepted by maintainers[0], who then leaves
        former = fixture_config(maintainers=self.config['maintainers'][1:], work_order_approvals=1)
        with self.assertRaisesRegex(Blocked, 'no maintainer any more'):
            issues.approved(self.hub, former, 57)
        with self.assertRaisesRegex(Blocked, 'fewer /accept than work_order_approvals'):
            issues.approved(self.hub, fixture_config(work_order_approvals=2), 57)

    def test_two_accounts_satisfy_two_approvals(self):
        second = issue_fixture.user(self.config['maintainers'][1])
        self.hub.approve(accepters=[self.hub.maintainer, second])
        issues.approved(self.hub, fixture_config(work_order_approvals=2), 57)

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
        config, gh = fixture_config(), Files()
        text, spec, pin = issues.work_order(gh, config, 'docs/work/FACTORY-008.md', 'p' * 40)
        self.assertEqual((spec['kind'], pin, gh.read), ('smoke', None, (config['repository'], 'docs/work/FACTORY-008.md', 'p' * 40)))
        self.assertEqual(issues.text_for(gh, config, 'fixture/repo', 'docs/work/X.md', 'q' * 40, None), text)
        for task in ('57', '#0', '#57a', 'docs/work/../x.md', None, 57):
            with self.subTest(task=task), self.assertRaises(Blocked):
                issues.work_order(gh, config, task, 'p' * 40)

    def test_session_reads_issues_through_the_maintainers_github_only(self):
        import session
        config = fixture_config()
        hub = issue_fixture.IssueHub(config)
        hub.issue()
        hub.approve(paths=('docs/',))
        spec, text, pin = session.work_order(config, 'p' * 40, '#57', hub)
        self.assertEqual((spec['allowed_paths'], pin['issue']), (['docs/'], 57))
        self.assertTrue(text.startswith('# #57 – CSV export'))
        self.assertEqual(session.order_source(config, 'p' * 40, '#57', text)['url'],
                         f"https://github.com/{config['repository']}/issues/57")
        with self.assertRaisesRegex(Blocked, 'needs GitHub access'):
            session.work_order(config, 'p' * 40, '#57')
        hub.issues[57]['body'] += '\nchanged'
        with self.assertRaisesRegex(Blocked, 'edited after its approval'):
            session.task_order(config, 'p' * 40, '#57', hub)

    def test_handoff_names_an_issue_or_a_file(self):
        config = fixture_config(runners=['claude'])
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
        self.assertEqual(issues.draft_spec(issue_fixture.DRAFT), {'status': 'draft', 'kind': 'factory', 'allowed_paths': []})
        bad = ['no block', issue_fixture.DRAFT * 2, '```factory-task\n{"status":"draft"}\n```',
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

    def test_configuration_enables_issue_work_orders_only_completely(self):
        config = branch_fixture.load(ROOT)
        self.assertEqual(issues.config_problems(config), [])
        self.assertEqual(issues.config_problems({k: v for k, v in config.items() if k != 'issue_review_model'}), [])
        broken = fixture_config(issue_review_model='gpt-6', limits={**config['limits'], 'max_issue_reviews': 0})
        del broken['limits']['issue_review_output_tokens']
        self.assertEqual(issues.config_problems(broken), [
            'issue_review_model must name a Claude model', 'limits.max_issue_reviews must be a whole number from 1 to 20',
            'limits.issue_review_output_tokens must be a whole number from 1000 to 32000'])


if __name__ == '__main__':
    unittest.main()
