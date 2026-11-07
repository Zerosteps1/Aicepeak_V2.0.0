"""Factory CLI boundaries: real Git repositories; GitHub, Docker, the keychain and models are faked."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path[:0] = [str(ROOT / 'tools/factory/cli'), str(ROOT / 'tools/factory'), str(Path(__file__).resolve().parent)]
import branch_fixture  # noqa: E402  fixtures never take the candidate's branch model (config PRs change it)
import branches  # noqa: E402
import branching  # noqa: E402
import checkouts  # noqa: E402
import commands  # noqa: E402
import common  # noqa: E402
import factory  # noqa: E402  the CLI entry (tools/factory/cli/factory.py)
import helptext  # noqa: E402
import install  # noqa: E402
import pipeline  # noqa: E402
import runs  # noqa: E402
import workorders  # noqa: E402
import engine  # noqa: E402
import issue_fixture  # noqa: E402
import issues  # noqa: E402
import session  # noqa: E402
from contracts import Blocked  # noqa: E402

REPOSITORY = 'Zerosteps1/Aicepeak_V2.0.0'
HTTPS = f'https://github.com/{REPOSITORY}.git'
ENV = {'PATH': os.environ['PATH'], 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
       'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
       'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid'}


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null', *args], env=ENV,
                          capture_output=True, text=True, check=True).stdout.strip()


def order(name, kind='factory', status='approved', paths=('docs/',)):
    return f'# {name} – Fixture order\n\n```factory-task\n' + json.dumps(
        {'status': status, 'kind': kind, 'allowed_paths': list(paths)}) + '\n```\n'


class GitHub:
    def __init__(self):
        self.pulls, self.created, self.issues = [], [], []

    def pages(self, path, field=None):
        return self.pulls if '/pulls?state=open' in path else []

    def request(self, method, path, data=None):
        if method == 'POST' and path == f'/repos/{REPOSITORY}/pulls':
            self.created.append(data)
            return {'number': 77, 'html_url': f'https://github.com/{REPOSITORY}/pull/77'}
        if method == 'POST' and path == f'/repos/{REPOSITORY}/issues':
            self.issues.append(data)
            return {'number': 58, 'html_url': f'https://github.com/{REPOSITORY}/issues/58'}
        raise AssertionError((method, path))


class IssuesAndPulls(issue_fixture.IssueHub):
    """Work-order issues plus the open pull requests of the repository."""
    def __init__(self, config, pulls=()):
        super().__init__(config)
        self.pulls = list(pulls)

    def pages(self, path, field=None):
        return self.pulls if '/pulls?state=open' in path else super().pages(path, field)


# A GitHub closing keyword before issue 57: merging a PR whose body has one closes the issue.
CLOSES_57 = re.compile(r'(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+#57\b')


class Repos(unittest.TestCase):
    """origin (bare, stands in for GitHub) with testing (validation, default) and production (config branch),
    a control clone on production and a candidate clone on testing."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name).resolve()
        self.origin = self.tmp / 'origin.git'
        subprocess.run(['git', 'init', '--quiet', '--bare', '-b', 'testing', str(self.origin)], env=ENV, check=True)
        self.seed = self.tmp / 'seed'
        self.seed.mkdir()
        git(self.seed, 'init', '--quiet', '-b', 'testing')
        files = {'factory/config.json': branch_fixture.text(ROOT),
                 'docs/work/TEMPLATE.md': (ROOT / 'docs/work/TEMPLATE.md').read_text(),
                 'docs/work/FACTORY-001.md': order('FACTORY-001', paths=('docs/work/',)),
                 'docs/work/ARCH-001.md': order('ARCH-001'),
                 'docs/work/FACTORY-003.md': order('FACTORY-003', paths=('docs/', 'tools/factory/')),
                 'docs/work/FACTORY-006.md': order('FACTORY-006'),
                 'docs/guide.md': 'guide\n', 'tools/factory/b.py': 'VALUE = 1\n', 'tool.sh': '#!/bin/sh\n'}
        for name, content in files.items():
            path = self.seed / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.seed / 'tool.sh').chmod(0o755)
        git(self.seed, 'add', '.')
        git(self.seed, 'commit', '--quiet', '-m', 'seed')
        git(self.seed, 'rm', '--quiet', 'docs/work/FACTORY-006.md')
        git(self.seed, 'commit', '--quiet', '-m', 'withdraw FACTORY-006')
        git(self.seed, 'branch', 'production')
        git(self.seed, 'push', '--quiet', str(self.origin), 'testing', 'production')
        self.control, self.candidate = self.clone('control', 'production'), self.clone('candidate')
        git(self.candidate, 'config', 'user.name', 'Fixture')
        git(self.candidate, 'config', 'user.email', 'fixture@example.invalid')
        self.tip = git(self.control, 'rev-parse', 'HEAD')
        self.config = json.loads((self.control / 'factory/config.json').read_text())
        real_tool = common.tool
        # CI mounts /tmp noexec: never run fake executables. gh only names the https credential helper,
        # which the local file transport of these tests never calls.
        patcher = mock.patch.object(common, 'tool', side_effect=lambda name, required=True:
                                    '/fake/gh' if name == 'gh' else real_tool(name, required))
        patcher.start()
        self.addCleanup(patcher.stop)
        for target, name, value in ((common, 'GITHUB', str(self.origin)), (common, 'NETWORK_PROTOCOLS', 'file'),
                                    (common, 'STATE_DIR', self.tmp / 'state'), (common, 'CONFIG_FILE', self.tmp / 'cli.json')):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def clone(self, name, branch=None):
        path = self.tmp / name
        subprocess.run(['git', 'clone', '--quiet', *(['--branch', branch] if branch else []), str(self.origin), str(path)],
                       env=ENV, check=True)
        git(path, 'remote', 'set-url', 'origin', HTTPS)
        return path

    def advance_origin(self, name='docs/later.md', branch='testing', text='later\n'):
        git(self.seed, 'switch', '--quiet', branch)
        (self.seed / name).parent.mkdir(parents=True, exist_ok=True)
        (self.seed / name).write_text(text)
        git(self.seed, 'add', name)
        git(self.seed, 'commit', '--quiet', '-m', f'later {name}')
        git(self.seed, 'push', '--quiet', str(self.origin), branch)
        return git(self.seed, 'rev-parse', 'HEAD')

    def publish_config(self, change):
        """A merged config PR: the config branch gets the edited configuration; the control fetches it."""
        git(self.seed, 'switch', '--quiet', 'production')
        text = branches.edited((self.seed / 'factory/config.json').read_text(), change)
        self.advance_origin('factory/config.json', 'production', text)
        checkouts.fetch(self.control, self.config, 'production')
        return json.loads(text)

    def switch_config(self, name):
        """`factory set config branch <name>` after owner steps 1 and 2: <name> is listed and names itself, then the old
        config branch production names <name>. Control checkouts and their code are left on production."""
        self.publish_config(lambda config: branches.with_production(config, name, 'no'))
        git(self.seed, 'branch', name)
        text = branches.edited((self.seed / 'factory/config.json').read_text(),
                               lambda config: branches.with_config_branch(config, name))
        self.advance_origin('factory/config.json', name, text)
        self.advance_origin('factory/config.json', 'production', text)
        return git(self.origin, 'rev-parse', name), git(self.origin, 'rev-parse', 'production')

    def device_file(self, branch=None):
        common.CONFIG_FILE.write_text(json.dumps({'control': str(self.control), 'candidate': str(self.candidate),
                                                  'python': sys.executable, 'bin': str(self.tmp / 'bin'),
                                                  **({'branch': branch} if branch else {})}))

    def ctx(self, model_config=None):
        """The real command context on the fixture: control policy, faked GitHub and login."""
        device = {'control': self.control, 'candidate': self.candidate, 'python': sys.executable,
                  'bin': self.tmp / 'bin', 'branch': None}
        policy = checkouts.read_policy(self.control, self.config)
        if model_config:
            policy = policy._replace(config=model_config, model=branches.parse(model_config))
        context = factory.Context(device, self.config, self.tip, policy)
        context._gh, context._user = GitHub(), {'login': 'ftrutschnig'}
        return context


class WorkOrderTests(Repos):
    def test_numbers_never_reuse_withdrawn_orders(self):
        used = workorders.numbers_ever_added(self.control, self.tip)
        self.assertEqual(used, {1, 3, 6})
        self.assertEqual(workorders.next_name('factory', used), 'FACTORY-007')
        self.assertEqual(workorders.next_name('product', used | {12}), 'PRODUCT-013')
        self.assertEqual(workorders.names_on(self.control, self.tip), ['ARCH-001', 'FACTORY-001', 'FACTORY-003'])

    def test_references_resolve_only_when_unique(self):
        names = workorders.names_on(self.control, self.tip)
        self.assertEqual(workorders.resolve('3', names), 'FACTORY-003')
        self.assertEqual(workorders.resolve('003', names), 'FACTORY-003')
        self.assertEqual(workorders.resolve('factory-003', names), 'FACTORY-003')
        with self.assertRaisesRegex(Blocked, 'ARCH-001, FACTORY-001'):
            workorders.resolve('1', names)
        # A number no file has names the work-order issue with that number; files only (sync) refuses it.
        self.assertEqual(workorders.resolve('9', names), 'issue-9')
        for reference in ('#57', 'issue-57', '#057', 'ISSUE-57'):
            self.assertEqual(workorders.resolve(reference, names), 'issue-57')
        with self.assertRaisesRegex(Blocked, 'no work order 9'):
            workorders.resolve('9', names, allow_issues=False)
        with self.assertRaisesRegex(Blocked, 'no work order #3'):
            workorders.resolve('#3', names, allow_issues=False)

    def test_template_fill_names_every_placeholder_until_completed(self):
        template = (ROOT / workorders.TEMPLATE).read_text()
        text = workorders.fill_template(template, 'FACTORY-007', None, 'factory', 'ftrutschnig', 'claude')
        path = 'docs/work/FACTORY-007.md'
        found = '\n'.join(workorders.problems(path, text, new=True, used_numbers={1, 3, 6}))
        for token in ('REPLACE-WITH-EXACT-PATHS', 'Short outcome-oriented title', 'When ..., the ... shall ....'):
            self.assertIn(token, found)
        spec = workorders.task_block(text)
        self.assertEqual((spec['status'], spec['kind']), ('draft', 'factory'))
        transfer = json.loads(workorders.HANDOFF_BLOCK.findall(text)[0])
        self.assertEqual(transfer, {'runner': 'claude', 'task': path, 'owner': 'ftrutschnig'})
        done = (text.replace('Short outcome-oriented title', 'CSV export').replace('REPLACE-WITH-EXACT-PATHS/', 'docs/')
                .replace('When ..., the ... shall ....', 'When asked, the export shall list rows.')
                .replace('If ..., then the ... shall ....', 'If empty, then the export shall say so.'))
        self.assertEqual(workorders.problems(path, done, new=True, used_numbers={1, 3, 6}), [])
        engine.task_spec(workorders.set_status(done, 'approved'))
        self.assertIn('already used', ' '.join(workorders.problems('docs/work/FACTORY-006.md', done.replace('FACTORY-007', 'FACTORY-006'),
                                                                    new=True, used_numbers={6})))
        smoke = workorders.set_status(done, 'draft').replace('"kind":"factory"', '"kind":"smoke"')
        self.assertIn('prefix FACTORY does not match kind smoke', ' '.join(workorders.problems(path, smoke, new=True, used_numbers=set())))

    def test_task_block_rejects_the_activation_typo(self):
        typo = '```factory-task\n{"status":"draft","approved":"factory","allowed_paths":["docs/"]}\n```\n'
        with self.assertRaisesRegex(Blocked, 'exactly the keys'):
            workorders.task_block(typo)
        with self.assertRaisesRegex(Blocked, 'factory-task block'):
            workorders.task_block(order('X-001', paths=('../outside/',)))
        self.assertEqual(workorders.task_block(order('X-001', status='draft'))['status'], 'draft')

    def test_branches_map_to_work_orders(self):
        names = ['FACTORY-003', 'FACTORY-SMOKE']
        self.assertEqual(workorders.branch_order('ftrutschnig/FACTORY-003', names), 'FACTORY-003')
        self.assertEqual(workorders.branch_order('ftrutschnig/FACTORY-003-2', names), 'FACTORY-003')
        self.assertEqual(workorders.branch_order('zerosteps1/FACTORY-003-fix-4', names), 'FACTORY-003')
        self.assertEqual(workorders.branch_order('ftrutschnig/FACTORY-SMOKE', names), 'FACTORY-SMOKE')
        self.assertIsNone(workorders.branch_order('feature/csv', names))
        self.assertIsNone(workorders.branch_order('testing', names))
        for branch in ('ftrutschnig/issue-57', 'ftrutschnig/issue-57-2', 'zerosteps1/issue-57-fix-3'):
            self.assertEqual(workorders.branch_order(branch, names), 'issue-57')
        self.assertIsNone(workorders.branch_order('ftrutschnig/issue-x', names))

    def test_issue_work_orders_have_their_own_task_and_label(self):
        self.assertEqual((workorders.task_of('issue-57'), workorders.label('issue-57')), ('#57', '#57'))
        self.assertEqual((workorders.task_of('FACTORY-003'), workorders.label('FACTORY-003')),
                         ('docs/work/FACTORY-003.md', 'FACTORY-003'))
        self.assertEqual(workorders.title_of(f'# #57 – CSV export\n\nbody'), 'CSV export')

    def test_issue_work_orders_are_read_through_github_and_legacy_files_at_the_config_tip(self):
        config = branch_fixture.load(ROOT)
        hub = issue_fixture.IssueHub(config)
        hub.issue()
        with self.assertRaisesRegex(Blocked, 'not an approved work order'):
            workorders.read(hub, self.control, config, self.tip, 'issue-57')
        hub.approve(paths=('docs/',))
        text, spec = workorders.read(hub, self.control, config, self.tip, 'issue-57')
        self.assertEqual((spec['allowed_paths'], text.split('\n', 1)[0]), (['docs/'], '# #57 – CSV export'))
        text, spec = workorders.read(None, self.control, config, self.tip, 'FACTORY-003')
        self.assertEqual(spec['allowed_paths'], ['docs/', 'tools/factory/'])

    def test_the_issue_template_is_a_draft_work_order_body(self):
        template = (ROOT / workorders.ISSUE_TEMPLATE).read_text()
        for kind in ('factory', 'product', 'smoke'):
            body = workorders.issue_body(template, kind)
            self.assertFalse(body.startswith('---'))
            self.assertEqual(issues.draft_spec(body), {'status': 'draft', 'kind': kind, 'allowed_paths': []})
            for section in ('## Goal', '## Non-goals', '## Acceptance criteria', '## Verification', '## Open questions'):
                self.assertIn(section, body)


class CheckoutTests(Repos):
    def test_disposable_checkout_is_what_session_accepts(self):
        with checkouts.scratch('test-') as scratch:
            repo = checkouts.materialize(scratch / 'repo', self.tip, objects=[checkouts.objects_dir(self.control)],
                                         origin=HTTPS, branch='feature/x')
            self.assertEqual(session.identity(repo, self.config), self.tip)
            session.clean_tree(repo, self.tip)
            self.assertEqual(checkouts.current_branch(repo), 'feature/x')
            self.assertTrue((repo / 'tool.sh').stat().st_mode & 0o111)
            self.assertEqual((repo / 'docs/guide.md').read_text(), 'guide\n')
            (repo / 'docs/guide.md').write_text('changed\n')
            patch = scratch / 'p.patch'
            patch.write_text(git(repo, 'diff') + '\n')
            git(repo, 'checkout', '--', 'docs/guide.md')
            git(repo, 'apply', '--index', str(patch))  # an author patch onto a fresh disposable index
            self.assertEqual((repo / 'docs/guide.md').read_text(), 'changed\n')
        self.assertFalse(scratch.exists())

    def test_control_fast_forwards_and_refuses_unsafe_states(self):
        newer = self.advance_origin(branch='production')
        self.assertEqual(checkouts.update_control(self.control, self.config), (newer, True))
        self.assertEqual(git(self.control, 'rev-parse', 'HEAD'), newer)
        self.assertEqual(checkouts.read_policy(self.control, self.config).tip, newer)
        (self.control / '.DS_Store').write_text('x')  # Finder's folder settings are tolerated
        self.assertEqual(checkouts.update_control(self.control, self.config), (newer, False))
        (self.control / 'notes.txt').write_text('x')
        with self.assertRaisesRegex(Blocked, r'untracked file notes\.txt.*factory never deletes'):
            checkouts.update_control(self.control, self.config)
        for stray in ('.DS_Store', 'notes.txt'):
            (self.control / stray).unlink()
        git(self.control, 'switch', '--quiet', '-c', 'other')
        with self.assertRaisesRegex(Blocked, 'stay on production'):
            checkouts.update_control(self.control, self.config)
        git(self.control, 'switch', '--quiet', 'production')
        (self.control / 'docs/guide.md').write_text('own\n')
        git(self.control, 'commit', '--quiet', '-am', 'own commit')
        self.advance_origin('docs/even-later.md', branch='production')
        with self.assertRaisesRegex(Blocked, 'cannot fast-forward to origin/production'):
            checkouts.update_control(self.control, self.config)

    def test_control_follows_its_listed_branch_and_fails_closed(self):
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'testing', 'origin/testing')
        newer = self.advance_origin()
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='testing'), (newer, True))
        policy = checkouts.read_policy(self.control, self.config)
        self.assertEqual((policy.tip, policy.model.config_branch, policy.model.route('smoke')), (self.tip, 'production', 'testing'))
        git(self.seed, 'push', '--quiet', str(self.origin), 'testing:feature-x')
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'feature-x', 'origin/testing')
        with self.assertRaisesRegex(Blocked, 'does not list.*`factory use branch production`'):
            checkouts.update_control(self.control, self.config, branch='feature-x')
        before = git(self.control, 'rev-parse', 'HEAD')
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='feature-x', listed=False), (before, False))
        with self.assertRaisesRegex(Blocked, 'config branch release is not on GitHub'):
            checkouts.update_control(self.control, {**self.config, 'config_branch': 'release'}, branch='feature-x')
        self.assertIsNone(checkouts.read_policy(self.control, {**self.config, 'config_branch': 'release'}))
        self.publish_config(lambda config: branches.with_config_branch(branches.with_production(config, 'release', 'no'),
                                                                       'release'))
        with self.assertRaisesRegex(Blocked, 'names the config branch release'):
            checkouts.read_policy(self.control, self.config)

    def test_control_follows_a_finished_change_of_the_config_branch(self):
        release, production = self.switch_config('release')
        self.assertEqual(checkouts.update_control(self.control, self.config), (production, True))  # code names production
        policy = checkouts.read_policy(self.control, self.config)
        self.assertEqual((policy.tip, policy.model.config_branch, policy.config['config_branch']), (release, 'release', 'release'))
        code = checkouts.repository_config(self.control)  # the fast-forwarded code itself names release now
        self.assertEqual(code['config_branch'], 'release')
        self.assertEqual(checkouts.update_control(self.control, code, branch='production'), (production, False))
        self.assertEqual(checkouts.read_policy(self.control, code).tip, release)
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'feature-x', 'origin/production')
        with self.assertRaisesRegex(Blocked, 'does not list.*`factory use branch release`'):
            checkouts.update_control(self.control, self.config, branch='feature-x')

    def test_after_a_config_branch_switch_commands_and_use_take_the_new_config_branch(self):
        """Control and code on the old config branch production, origin/production naming release, origin/release
        naming itself: the state every device is in right after owner steps 1 and 2."""
        self.advance_origin('tools/factory/cli/factory.py', 'production', '# the CLI entry bootstrap verifies\n')
        checkouts.update_control(self.control, self.config)
        release, production = self.switch_config('release')
        self.device_file()
        entry = self.control / 'tools/factory/cli/factory.py'
        with mock.patch.object(factory, 'ROOT', self.control), mock.patch.object(checkouts, 'ROOT', self.control), \
                mock.patch.object(factory, '__file__', str(entry)), mock.patch.object(factory, 'reexec') as reexec:
            ctx = factory.bootstrap('branches')
            reexec.assert_called_once()  # the control fast-forwarded to production's tip
            self.assertEqual(git(self.control, 'rev-parse', 'HEAD'), production)
            self.assertEqual(checkouts.device()['branch'], 'production')  # pinned before the code names release
            self.assertEqual((ctx.model.config_branch, ctx.policy, ctx.branch), ('release', release, 'production'))
            with mock.patch.object(factory, 'REEXECS', 1):
                ctx = factory.bootstrap('branches')  # the re-executed start, whose own code names release
                self.assertEqual((ctx.model.config_branch, ctx.policy), ('release', release))
                ctx._gh, ctx._user = GitHub(), {'login': 'ftrutschnig'}
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(branching.diagram(ctx), 0)
                self.assertIn('Config branch: release', output.getvalue())
                self.assertEqual(ctx.config_tip(), release)
                ctx = factory.bootstrap('use')
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(branching.use(ctx, 'release'), 0)
            self.assertIn('come from the config branch release', output.getvalue())
            self.assertEqual((checkouts.current_branch(self.control), checkouts.device()['branch']), ('release', 'release'))
            reexec.reset_mock()
            ctx = factory.bootstrap('branches')
            reexec.assert_not_called()
            self.assertEqual((ctx.branch, ctx.model.config_branch, ctx.policy), ('release', 'release', release))

    def test_use_leaves_a_listed_control_branch_that_is_missing_on_github(self):
        git(self.seed, 'push', '--quiet', str(self.origin), 'testing:staging')
        self.publish_config(lambda config: branches.with_validation(config, 'staging', 'tests', ['smoke']))
        checkouts.fetch(self.control, self.config, 'staging')
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'staging', 'origin/staging')
        git(self.origin, 'update-ref', '-d', 'refs/heads/staging')  # deleted on GitHub while still listed
        before = git(self.control, 'rev-parse', 'HEAD')
        with self.assertRaisesRegex(Blocked, 'staging is not on GitHub; switch with `factory use branch production`'):
            checkouts.update_control(self.control, self.config, branch='staging')
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='staging', listed=False), (before, False))
        self.device_file('staging')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.use(self.ctx(), 'production'), 0)
        self.assertEqual((checkouts.current_branch(self.control), checkouts.device()['branch']), ('production', 'production'))

    def test_an_interrupted_use_branch_never_strands_the_control_checkout(self):
        self.device_file('production')
        checkouts.fetch(self.control, self.config, 'testing')
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'testing', 'origin/testing')  # then interrupted
        head = git(self.control, 'rev-parse', 'HEAD')
        newer = self.advance_origin()
        with self.assertRaisesRegex(Blocked, 'is on testing, but it must stay on production, its recorded control branch: '
                                    '`factory use branch <listed branch>` switches it'):
            checkouts.update_control(self.control, self.config, branch='production')
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='production', listed=False), (head, False))
        self.assertEqual(git(self.control, 'rev-parse', 'HEAD'), head)  # only verified: never fast-forwarded off its branch
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.use(self.ctx(), 'testing'), 0)
        self.assertEqual((checkouts.current_branch(self.control), git(self.control, 'rev-parse', 'HEAD')), ('testing', newer))
        self.assertEqual(checkouts.device()['branch'], 'testing')
        git(self.control, 'switch', '--quiet', 'production')  # interrupted again, now on a commit GitHub never saw
        git(self.control, 'commit', '--quiet', '--allow-empty', '-m', 'own')
        with self.assertRaisesRegex(Blocked, 'is on production with own commits; it must never carry any'):
            checkouts.update_control(self.control, self.config, branch='testing', listed=False)
        git(self.control, 'reset', '--quiet', '--hard', 'HEAD~1')
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='testing', listed=False)[1], False)
        git(self.control, 'switch', '--quiet', '--no-track', '-c', 'feature-x', 'origin/testing')
        with self.assertRaisesRegex(Blocked, 'is on feature-x, neither its recorded control branch testing nor a listed branch'):
            checkouts.update_control(self.control, self.config, branch='testing', listed=False)
        git(self.control, 'switch', '--quiet', '--detach')
        with self.assertRaisesRegex(Blocked, 'is on a detached HEAD, neither'):
            checkouts.update_control(self.control, self.config, branch='testing', listed=False, online=False)

    def test_checkouts_are_separate_and_candidate_config_is_allowlisted(self):
        checkouts.separate(self.control, self.candidate)
        with self.assertRaisesRegex(Blocked, 'separate'):
            checkouts.separate(self.control, self.control / 'docs')
        checkouts.verify_candidate(self.candidate, self.config)
        git(self.candidate, 'config', 'core.fsmonitor', 'true')
        with self.assertRaisesRegex(Blocked, 'core.fsmonitor'):
            checkouts.verify_candidate(self.candidate, self.config)
        git(self.candidate, 'config', '--unset', 'core.fsmonitor')
        git(self.candidate, 'config', '--unset', 'user.email')
        with self.assertRaisesRegex(Blocked, 'user.email'):
            checkouts.verify_candidate(self.candidate, self.config)

    def test_fetch_skips_missing_branches_and_imports_become_context(self):
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/FACTORY-003')
        (self.candidate / 'tools/factory/a.py').write_text('import b\nimport json\n')
        git(self.candidate, 'add', '.')
        git(self.candidate, 'commit', '--quiet', '-m', 'a')
        git(self.candidate, 'push', '--quiet', str(self.origin), 'HEAD')
        tips = checkouts.fetch(self.candidate, self.config, 'testing', 'ftrutschnig/FACTORY-003', 'missing', 'testing')
        self.assertEqual(set(tips), {'testing', 'ftrutschnig/FACTORY-003'})
        head = git(self.candidate, 'rev-parse', 'HEAD')
        self.assertEqual(checkouts.direct_imports(self.candidate, self.tip, head), ['tools/factory/b.py'])


class CommandTests(Repos):
    def test_collect_orders_and_move_out_only_identical_files(self):
        work = self.candidate / 'docs/work'
        (work / 'FACTORY-007.md').write_text(order('FACTORY-007', status='draft'))
        (work / 'FACTORY-003.md').write_text(order('FACTORY-003', status='draft'))
        (work / 'ARCH-001.md').unlink()
        (work / 'TEMPLATE.md').write_text('changed template\n')
        (self.candidate / 'docs/guide.md').write_text('unrelated\n')
        changes = commands.collect_orders(self.candidate)
        self.assertEqual(set(changes), {'docs/work/FACTORY-007.md', 'docs/work/FACTORY-003.md', 'docs/work/ARCH-001.md'})
        self.assertIsNone(changes['docs/work/ARCH-001.md'])
        (work / 'FACTORY-003.md').write_text('edited again after the submission\n')
        commands.move_out(self.candidate, self.tip, changes)
        self.assertFalse((work / 'FACTORY-007.md').exists())
        self.assertEqual((work / 'FACTORY-003.md').read_text(), 'edited again after the submission\n')
        self.assertTrue((work / 'ARCH-001.md').exists())
        self.assertEqual((self.candidate / 'docs/guide.md').read_text(), 'unrelated\n')

    def test_submit_workorders_pushes_only_orders_into_the_config_branch_then_moves_them(self):
        self.advance_origin('docs/testing-only.md')  # testing moves on: the work-order branch starts from production
        (self.candidate / 'docs/work/FACTORY-007.md').write_text(order('FACTORY-007', status='draft'))
        (self.candidate / 'docs/guide.md').write_text('unrelated\n')
        calls = []
        with mock.patch.object(common, 'ask', return_value=True), \
                mock.patch.object(commands, 'session_submit', side_effect=lambda *a, **k: calls.append((a, k)) or k['on_created'](12) or 12), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(commands.submit_workorders(self.ctx()), 0)
        self.assertEqual((calls[0][0][2], calls[0][1]['base']), (None, 'production'))  # no advisory preflight
        self.assertEqual(git(self.origin, 'rev-parse', 'ftrutschnig/new-workorders^'), git(self.origin, 'rev-parse', 'production'))
        pushed = git(self.origin, 'show', 'refs/heads/ftrutschnig/new-workorders:docs/work/FACTORY-007.md')
        self.assertEqual(workorders.task_block(pushed)['status'], 'approved')
        self.assertEqual(git(self.origin, 'show', 'refs/heads/ftrutschnig/new-workorders:docs/guide.md'), 'guide')
        self.assertFalse((self.candidate / 'docs/work/FACTORY-007.md').exists())
        self.assertEqual((self.candidate / 'docs/guide.md').read_text(), 'unrelated\n')

    def test_submit_workorders_names_every_problem_and_pushes_nothing(self):
        template = (ROOT / workorders.TEMPLATE).read_text()
        text = workorders.fill_template(template, 'FACTORY-007', None, 'factory', 'ftrutschnig', 'claude')
        (self.candidate / 'docs/work/FACTORY-007.md').write_text(text)
        with self.assertRaisesRegex(Blocked, '(?s)REPLACE-WITH-EXACT-PATHS.*Short outcome-oriented title'):
            commands.submit_workorders(self.ctx())
        self.assertNotIn('new-workorders', git(self.origin, 'branch', '--list'))

    def test_issue_creates_a_github_issue_under_the_maintainer_login_and_no_file(self):
        ctx = self.ctx()
        with contextlib.redirect_stdout(io.StringIO()) as shown:
            self.assertEqual(commands.issue(ctx, 'CSV export', kind='smoke', noedit=True), 0)
        [created] = ctx.gh.issues
        self.assertEqual(created['title'], 'CSV export')
        self.assertEqual(issues.draft_spec(created['body']), {'status': 'draft', 'kind': 'smoke', 'allowed_paths': []})
        self.assertIn(f'Created work-order issue #58: https://github.com/{REPOSITORY}/issues/58', shown.getvalue())
        self.assertIn('`factory start workorder 58`', shown.getvalue())
        self.assertEqual(git(self.candidate, 'status', '--porcelain'), '')
        with self.assertRaisesRegex(Blocked, '--noedit needs --title'):
            commands.issue(ctx, None, noedit=True)
        self.assertEqual(len(ctx.gh.issues), 1)

    def test_issue_draft_is_written_in_the_editor_and_created_only_after_confirmation(self):
        ctx = self.ctx()
        def editor(command, check=False):
            draft = Path(command[-1])
            draft.write_text(draft.read_text().replace('# Short outcome-oriented title', '# Edited title', 1))
        with mock.patch.dict(os.environ, {'VISUAL': 'fake-editor --wait'}), \
                mock.patch.object(commands.subprocess, 'run', side_effect=editor) as run, \
                mock.patch.object(common, 'ask', return_value=False), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(Blocked, 'nothing created; your draft stays in'):
                commands.issue(ctx)
        self.assertEqual(run.call_args[0][0][:2], ['fake-editor', '--wait'])
        self.assertEqual(ctx.gh.issues, [])
        with mock.patch.dict(os.environ, {'VISUAL': 'fake-editor'}), \
                mock.patch.object(commands.subprocess, 'run', side_effect=editor), \
                mock.patch.object(common, 'ask', return_value=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(commands.issue(ctx), 0)
        self.assertEqual(ctx.gh.issues[0]['title'], 'Edited title')
        self.assertFalse(ctx.gh.issues[0]['body'].startswith('# '))
        with mock.patch.dict(os.environ, {'VISUAL': 'fake-editor'}), \
                mock.patch.object(commands.subprocess, 'run'), mock.patch.object(common, 'ask', return_value=True), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(Blocked, 'the issue needs a title'):
                commands.issue(ctx)  # the placeholder title was left unchanged
        self.assertEqual(len(ctx.gh.issues), 1)

    def test_submit_commits_only_staged_files_and_refuses_listed_branches(self):
        with self.assertRaisesRegex(Blocked, 'never on testing, a listed validation branch'):
            commands.submit(self.ctx())
        git(self.candidate, 'switch', '--quiet', '--no-track', '-c', 'production', 'origin/production')
        with self.assertRaisesRegex(Blocked, 'never on production, a listed production branch'):
            commands.submit(self.ctx())
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/FACTORY-003')
        (self.candidate / 'docs/guide.md').write_text('staged\n')
        (self.candidate / 'tools/factory/b.py').write_text('VALUE = 2\n')
        git(self.candidate, 'add', 'docs/guide.md')
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(commands.submit(self.ctx()), 0)
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%s', 'ftrutschnig/FACTORY-003'), 'FACTORY-003: Fixture order')
        self.assertEqual(git(self.origin, 'show', 'ftrutschnig/FACTORY-003:tools/factory/b.py'), 'VALUE = 1')
        self.assertEqual((self.candidate / 'tools/factory/b.py').read_text(), 'VALUE = 2\n')

    def test_branch_without_work_order_warns_and_finished_needs_one(self):
        git(self.candidate, 'switch', '--quiet', '-c', 'feature/csv')
        (self.candidate / 'docs/guide.md').write_text('staged\n')
        git(self.candidate, 'add', '.')
        with mock.patch.object(common, 'countdown') as countdown, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(commands.submit(self.ctx(), title='docs: guide'), 0)
        countdown.assert_called_once()
        self.assertEqual(git(self.origin, 'log', '-1', '--format=%s', 'feature/csv'), 'docs: guide')
        with self.assertRaisesRegex(Blocked, 'belongs to no work order'):
            commands.submit(self.ctx(), finished=True)

    def test_submit_finished_targets_the_branch_routed_for_the_kind(self):
        self.advance_origin('docs/work/SMOKE-004.md', 'production', order('SMOKE-004', kind='smoke'))
        git(self.seed, 'push', '--quiet', str(self.origin), f'{self.tip}:refs/heads/staging')
        ctx = self.ctx(branches.with_validation(self.config, 'staging', 'tests', ['smoke']))
        calls = []
        for branch in ('ftrutschnig/SMOKE-004', 'ftrutschnig/FACTORY-003'):
            git(self.candidate, 'switch', '--quiet', '-c', branch, self.tip)
            (self.candidate / 'docs/guide.md').write_text(branch + '\n')
            git(self.candidate, 'add', 'docs/guide.md')
            with mock.patch.object(commands, 'session_submit', side_effect=lambda *a, **k: calls.append((a[2], k['base'])) or 3), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(commands.submit(ctx, finished=True), 0)
        self.assertEqual(calls, [('docs/work/SMOKE-004.md', 'staging'), ('docs/work/FACTORY-003.md', 'testing')])
        self.advance_origin('docs/staging-only.md', 'testing')
        with self.assertRaisesRegex(Blocked, 'does not contain current testing.*merge origin/testing'), \
                contextlib.redirect_stdout(io.StringIO()):
            commands.submit(ctx, finished=True)

    def submit_finished(self, ctx, branch, hub, **options):
        """`factory submit --finished` on a new `branch` with one staged file: (exit code, [(task, base, body)], output)."""
        git(self.candidate, 'switch', '--quiet', '-c', branch, self.tip)
        (self.candidate / 'docs/guide.md').write_text(branch + '\n')
        git(self.candidate, 'add', 'docs/guide.md')
        ctx._gh, opened = hub, []

        def fake(context, snapshot, task, title, body, *args, **kwargs):
            opened.append((task, kwargs['base'], Path(body).read_text()))
            return 3
        with mock.patch.object(commands, 'session_submit', side_effect=fake), \
                mock.patch.object(commands, 'watch', return_value=0), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = commands.submit(ctx, finished=True, **options)
        return code, opened, out.getvalue() + err.getvalue()

    def test_submit_finished_links_the_work_order_issue_with_a_closing_keyword(self):
        hub = IssuesAndPulls(self.config)
        hub.issue()
        hub.approve()
        code, opened, output = self.submit_finished(self.ctx(), 'ftrutschnig/issue-57', hub)
        self.assertEqual((code, [entry[:2] for entry in opened]), (0, [('#57', 'testing')]))
        self.assertIn('Work order: #57\n\nCloses #57\n\nCommits:', opened[0][2])
        self.assertRegex(opened[0][2], CLOSES_57)
        self.assertIn('The PR says `Closes #57`: GitHub closes the issue when the PR merges into its default branch.', output)
        # GitHub decides when to close: the keyword is written for any target (GitHub ignores it outside its default branch).
        git(self.seed, 'push', '--quiet', str(self.origin), f'{self.tip}:refs/heads/staging')
        ctx = self.ctx(branches.with_validation(self.config, 'staging', 'tests', ['factory']))
        code, opened, _ = self.submit_finished(ctx, 'ftrutschnig/issue-57-2', hub)
        self.assertEqual((code, [entry[:2] for entry in opened]), (0, [('#57', 'staging')]))
        self.assertRegex(opened[0][2], CLOSES_57)
        # A legacy file is named by its path; there is no issue to close.
        code, opened, output = self.submit_finished(self.ctx(), 'ftrutschnig/FACTORY-003', hub)
        self.assertEqual(code, 0)
        self.assertIn('Work order: `docs/work/FACTORY-003.md`\n\nCommits:', opened[0][2])
        self.assertNotIn('Closes', opened[0][2] + output)

    def test_submit_refuses_a_branch_behind_github(self):
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/FACTORY-003')
        git(self.candidate, 'push', '--quiet', str(self.origin), 'HEAD')
        other = self.clone('other')
        git(other, 'switch', '--quiet', 'ftrutschnig/FACTORY-003')
        (other / 'docs/guide.md').write_text('pushed elsewhere\n')
        git(other, 'commit', '--quiet', '-am', 'elsewhere')
        git(other, 'push', '--quiet', str(self.origin), 'HEAD')
        with self.assertRaisesRegex(Blocked, 'behind or diverged'):
            commands.submit(self.ctx())

    def test_watch_reports_a_stale_review_and_goes_on_with_other_prs(self):
        fake = self.tmp / 'policy'
        (fake / 'tools/factory').mkdir(parents=True)
        (fake / 'tools/factory/session.py').write_text(  # stands in for session.py watch of the config branch tip
            'import json, sys\npr = int(sys.argv[sys.argv.index("--pr") + 1])\nprint("reviewer output", flush=True)\n'
            'stale = {"message": "feedback or the config branch changed after /review; comment /review again"}\n'
            'print(json.dumps({"pr": pr, "status": "stale" if pr == 12 else "polled", "attempted_checks": [],'
            ' **(stale if pr == 12 else {})}, indent=2))\n')
        ctx = self.ctx()
        ctx._gh = mock.Mock(pages=mock.Mock(return_value=[{'number': 12, 'title': 'a', 'pull_request': {'url': 'x'}},
                                                          {'number': 13, 'title': 'b', 'pull_request': {'url': 'y'}}]))
        with mock.patch.object(checkouts, 'policy_checkout', lambda *args: contextlib.nullcontext(fake)), \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as warned:
            self.assertEqual(commands.watch(ctx, 12), 0)
            with mock.patch.object(commands, 'time', mock.Mock(sleep=mock.Mock(side_effect=KeyboardInterrupt))), \
                    self.assertRaises(KeyboardInterrupt):
                commands.watch(ctx, everything=True)
        stale = 'PR #12: feedback or the config branch changed after /review; comment /review again'
        self.assertEqual(warned.getvalue().count(stale), 2)
        self.assertIn('PR #13: b', output.getvalue())
        self.assertIn('"status": "polled"', output.getvalue())  # the other PR is still watched
        self.assertIn('reviewer output', output.getvalue())


class RunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        for name, value in (('STATE_DIR', self.tmp / 'state'), ('tool', mock.Mock(return_value=None))):
            patcher = mock.patch.object(common, name, value)  # no real Docker daemon is ever touched
            patcher.start()
            self.addCleanup(patcher.stop)

    def holder(self, path, script='time.sleep(30)'):
        code = ('import fcntl, signal, sys, time\nhandle = open(sys.argv[1], "a")\nfcntl.flock(handle, fcntl.LOCK_EX)\n'
                'signal.signal(signal.SIGTERM, lambda *a: (open(sys.argv[2], "w").write("terminated"), sys.exit(0)))\n'
                'print("ready", flush=True)\n' + script + '\n')
        process = subprocess.Popen([sys.executable, '-c', code, str(path / 'lock'), str(self.tmp / 'signal')],
                                   stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        self.assertEqual(process.stdout.readline().strip(), 'ready')
        return process

    def test_liveness_comes_from_the_runner_lock_and_stale_runs_fail(self):
        path = runs.create('FACTORY-003', 'start')
        runs.update(path, order='FACTORY-003', status='running', pid=None)
        process = self.holder(path)
        self.assertTrue(runs.alive(path))
        self.assertEqual(runs.find('FACTORY-003'), path)
        process.kill()
        process.wait()
        self.assertFalse(runs.alive(path))
        with self.assertRaisesRegex(Blocked, 'ended failed'):
            runs.find('FACTORY-003')
        self.assertEqual(runs.state(path)['reason'], 'the runner ended unexpectedly')

    def test_ctrl_c_only_detaches(self):
        path = runs.create('FACTORY-003', 'start')
        runs.update(path, order='FACTORY-003', status='running')
        self.holder(path)
        (path / 'log').write_text('[10:00:00] — author\n')
        output = io.StringIO()
        with mock.patch.object(runs.time, 'sleep', side_effect=KeyboardInterrupt), contextlib.redirect_stdout(output):
            self.assertEqual(runs.follow(path, 'FACTORY-003'), 0)
        self.assertIn('— author', output.getvalue())
        self.assertIn('Detached; the run continues', output.getvalue())
        self.assertTrue(runs.alive(path))

    def test_cancel_terminates_the_runner_and_sweeps_its_labels(self):
        path = runs.create('FACTORY-003', 'start')
        process = self.holder(path)
        runs.update(path, order='FACTORY-003', status='running', pid=process.pid, pr=42, config_branch='production')
        docker = []

        def fake_run(args, **kwargs):
            docker.append(' '.join(args[1:]))
            return subprocess.CompletedProcess(args, 0, 'c1\n' if args[1] == 'ps' else '', '')
        output = io.StringIO()
        with mock.patch.object(common, 'tool', return_value='/fake/docker'), \
                mock.patch.object(runs.subprocess, 'run', side_effect=fake_run), contextlib.redirect_stdout(output):
            runs.cancel(path)
        process.wait(timeout=10)
        self.assertEqual((self.tmp / 'signal').read_text(), 'terminated')
        self.assertEqual(runs.state(path)['status'], 'cancelled')
        self.assertIn(f'ps -aq --filter label=aicepeak.factory.run={path.name}', docker)
        self.assertIn('rm -f c1', docker)
        self.assertIn('gh workflow run factory.yml --ref production -f pr=42 -f retry=true', output.getvalue())


class PipelineTests(Repos):
    def runner(self, **data):
        runner = pipeline.Runner.__new__(pipeline.Runner)
        runner.path = self.tmp / 'run'
        runner.path.mkdir(exist_ok=True)
        runner.work = checkouts.materialize(runner.path / 'work', self.tip, objects=[checkouts.objects_dir(self.control)],
                                            origin=HTTPS, branch='factory-run/test')
        runner.data = {'base': self.tip, 'branch': 'ftrutschnig/FACTORY-003', 'branch_exists': False, 'kind': 'start',
                       'allowed_paths': ['docs/', 'tools/factory/'], 'request': None, 'pr': None, 'runner': 'claude',
                       'identity': {'name': 'Fixture', 'email': 'fixture@example.invalid'}, 'target': 'testing',
                       'config_branch': 'production', 'listed': ['testing', 'production'], **data}
        runner.kind, runner.order, runner.task = runner.data['kind'], 'FACTORY-003', 'docs/work/FACTORY-003.md'
        runner.config, runner.control, runner.candidate = self.config, self.control, self.candidate
        runner.merged_base, runner.last_review, runner.spend, runner.url = None, None, 0.0, str(self.origin)
        runner.target = runner.data['target']
        return runner

    def commit(self, runner, files):
        for name, content in files.items():
            target = runner.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content) if isinstance(content, bytes) else target.write_text(content)
        git(runner.work, 'add', '.')
        git(runner.work, 'commit', '--quiet', '-m', 'run')

    def test_start_targets_the_validation_branch_routed_for_the_kind(self):
        self.advance_origin('docs/work/SMOKE-004.md', 'production', order('SMOKE-004', kind='smoke'))
        git(self.seed, 'push', '--quiet', str(self.origin), f'{self.tip}:refs/heads/staging')
        staging = self.advance_origin('docs/staging.md', 'testing')
        git(self.seed, 'push', '--quiet', str(self.origin), 'testing:staging')
        ctx = self.ctx(branches.with_validation(self.config, 'staging', 'tests', ['smoke']))
        with mock.patch.object(pipeline, 'docker_ready', return_value=''), mock.patch.object(pipeline, 'author_keys', return_value={}), \
                mock.patch.object(runs, 'spawn', side_effect=lambda *args: args[-1].close()), \
                mock.patch.object(runs, 'follow', return_value=0), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(pipeline.launch(ctx, 'start', 'SMOKE-004'), 0)
            self.assertEqual(pipeline.launch(ctx, 'start', '3'), 0)
        states = {runs.state(path)['order']: runs.state(path) for path in runs.every()}
        smoke, factory_run = states['SMOKE-004'], states['FACTORY-003']
        self.assertEqual((smoke['target'], smoke['base'], smoke['branch']), ('staging', staging, 'ftrutschnig/SMOKE-004'))
        self.assertEqual((factory_run['target'], factory_run['base']), ('testing', staging))
        self.assertEqual((smoke['config_branch'], smoke['listed']), ('production', ['testing', 'staging', 'production']))
        self.assertEqual(smoke['policy_config']['config_branch'], 'production')

    def test_author_scope_refuses_control_only_orders(self):
        with self.assertRaisesRegex(Blocked, 'protected factory change'):
            pipeline.author_scope({'allowed_paths': ['tools/factory/', 'factory/', 'AGENTS.md']})
        with contextlib.redirect_stderr(io.StringIO()) as warned:
            pipeline.author_scope({'allowed_paths': ['docs/', 'tools/factory/']})
        self.assertIn('tools/factory/', warned.getvalue())

    def test_in_scope_result_is_applied_unstaged_on_a_new_branch(self):
        runner = self.runner()
        self.commit(runner, {'docs/new.md': 'new\n'})
        with contextlib.redirect_stdout(io.StringIO()):
            runner.apply()
        self.assertEqual(checkouts.current_branch(self.candidate), 'ftrutschnig/FACTORY-003')
        self.assertEqual((self.candidate / 'docs/new.md').read_text(), 'new\n')
        self.assertIn('?? docs/new.md', git(self.candidate, 'status', '--porcelain'))

    def test_unsafe_results_are_kept_as_a_patch(self):
        runner = self.runner()
        self.commit(runner, {'docs/ok.md': 'ok\n', '.github/workflows/x.yml': 'on: push\n', 'docs/work/FACTORY-003.md': 'x\n',
                             'docs/image.bin': b'\x00\x01binary', 'outside.txt': 'x\n'})
        os.symlink('ok.md', runner.work / 'docs/link.md')
        git(runner.work, 'add', '.')
        git(runner.work, 'commit', '--quiet', '-m', 'link')
        _, _, _, problems = runner.changes()
        joined = ' '.join(problems)
        for expected in ('outside the work order: .github/workflows/x.yml', 'guarded path', 'docs/work/FACTORY-003.md',
                         'symlink or submodule: docs/link.md', 'binary: docs/image.bin', 'outside.txt'):
            self.assertIn(expected, joined)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            runner.apply()
        self.assertIn('Patch kept, not applied', output.getvalue())
        self.assertEqual(checkouts.current_branch(self.candidate), 'testing')
        self.assertTrue((runner.path / 'changes.patch').stat().st_size)

    def test_result_after_the_target_moved_lands_on_its_new_tip(self):
        runner = self.runner()
        newer = self.advance_origin()
        checkouts.fetch(self.control, self.config, 'testing')  # as the run's fetch_tips does
        git(runner.work, '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'merge', '--quiet', '--no-edit', newer)
        runner.merged_base = newer
        self.commit(runner, {'docs/new.md': 'new\n'})
        with contextlib.redirect_stdout(io.StringIO()):
            runner.apply()
        self.assertEqual(git(self.candidate, 'rev-parse', 'HEAD'), newer)
        self.assertEqual((self.candidate / 'docs/new.md').read_text(), 'new\n')

    def test_corrections_stop_at_max_rounds_and_a_failed_review_still_applies(self):
        runner = self.runner(text='order text')
        shutil.rmtree(runner.work)
        calls, applied = [], []
        review = {'outcome': 'changes_requested', 'findings': [], 'summary': 'P1 left'}
        with mock.patch.object(runner, 'author', side_effect=lambda prompt, step: calls.append(step) or True), \
                mock.patch.object(runner, 'preflight', return_value=review), \
                mock.patch.object(runner, 'apply', side_effect=lambda: applied.append(True)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            runner.execute()
        rounds = int(self.config['limits']['max_rounds'])
        self.assertEqual(calls, ['author'] + [f'correction-{n}' for n in range(1, rounds + 1)])
        self.assertIn(f'P0/P1 findings remain after {rounds} correction round(s)', output.getvalue())
        self.assertEqual(applied, [True])
        shutil.rmtree(runner.work)
        with mock.patch.object(runner, 'author', return_value=True), \
                mock.patch.object(runner, 'preflight', side_effect=Blocked('preflight did not run')), \
                mock.patch.object(runner, 'apply', side_effect=lambda: applied.append(True)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            runner.execute()
        self.assertIn('a review step failed: preflight did not run', output.getvalue())
        self.assertEqual(applied, [True, True])

    def test_dirty_or_foreign_candidate_is_never_switched(self):
        runner = self.runner()
        self.commit(runner, {'docs/new.md': 'new\n'})
        (self.candidate / 'docs/guide.md').write_text('local edit\n')
        patch = runner.path / 'p.patch'
        patch.write_bytes(git(runner.work, 'diff', '--binary', self.tip, 'HEAD').encode() + b'\n')
        names = ['docs/new.md']
        self.assertIn('uncommitted changes', runner.apply_to_candidate(patch, self.tip, names)[0])
        git(self.candidate, 'checkout', '--', 'docs/guide.md')
        git(self.candidate, 'switch', '--quiet', '-c', 'my-own-work')
        self.assertIn('does not switch away', runner.apply_to_candidate(patch, self.tip, names)[0])

    def test_run_budget_stops_model_steps_before_they_start(self):
        worker = pipeline.Worker(self.tmp, self.control, {}, 'label', 'claude', '')
        worker.spend = 20.0
        with mock.patch.object(pipeline.subprocess, 'Popen') as popen:
            with self.assertRaisesRegex(pipeline.Skip, 'run budget'):
                worker.model('author', 'prompt', self.tmp)
        popen.assert_not_called()

    def test_hotfix_never_pushes_without_a_passing_preflight_or_with_protected_paths(self):
        runner = self.runner(kind='hotfix', request='Totals are wrong')
        self.commit(runner, {'docs/fix.md': 'fixed\n'})
        applied = []
        with mock.patch.object(runner, 'apply', side_effect=lambda: applied.append(True)), \
                mock.patch.object(runner, 'fetch_tips', return_value=(self.tip, self.tip)), contextlib.redirect_stdout(io.StringIO()) as output:
            runner.publish()
        self.assertEqual(applied, [True])
        self.assertIn('the last preflight did not pass on exactly this result', output.getvalue())
        self.assertNotIn('ftrutschnig/FACTORY-003', git(self.origin, 'branch', '--list'))
        head = git(runner.work, 'rev-parse', 'HEAD')
        runner.last_review = ({'outcome': 'pass'}, head, self.tip)
        self.commit(runner, {'README.md': 'protected\n'})
        runner.last_review = ({'outcome': 'pass'}, git(runner.work, 'rev-parse', 'HEAD'), self.tip)
        runner.data['allowed_paths'].append('README.md')
        with mock.patch.object(runner, 'apply', side_effect=lambda: applied.append(True)), \
                mock.patch.object(runner, 'fetch_tips', return_value=(self.tip, self.tip)), contextlib.redirect_stdout(io.StringIO()) as output:
            runner.publish()
        self.assertIn('protected paths are never pushed automatically: README.md', output.getvalue())
        self.assertNotIn('ftrutschnig/FACTORY-003', git(self.origin, 'branch', '--list'))


class BranchTests(Repos):
    def outside_spans(self, text):
        """config.json text without the values of branches and config_branch."""
        for start, end in sorted((branches._span(text, key) for key in ('branches', 'config_branch')), reverse=True):
            text = text[:start] + text[end:]
        return text

    def submitted(self, calls=None):
        calls = [] if calls is None else calls

        def fake(ctx, snapshot, task, title, body, *args, **kwargs):
            calls.append({'task': task, 'title': title, 'body': Path(body).read_text(), 'base': kwargs['base'],
                          'branch': checkouts.current_branch(snapshot), 'head': checkouts.head(snapshot)})
            return 5
        return calls, mock.patch.object(commands, 'session_submit', side_effect=fake)

    def test_config_prs_change_only_the_branch_spans_of_the_config_branch(self):
        published = self.publish_config(lambda config: branches.with_production(
            branches.with_validation(config, 'staging', 'tests', ['smoke']), 'release', 'no'))
        production = git(self.origin, 'rev-parse', 'production')
        before = git(self.origin, 'show', 'production:factory/config.json') + '\n'
        calls, patcher = self.submitted()
        with patcher, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.add_validation(self.ctx(), 'qa', 'none', []), 0)
            self.assertEqual(branching.add_production(self.ctx(), 'release', 'initiated'), 0)
            self.assertEqual(branching.remove(self.ctx(), 'staging'), 0)
            self.assertEqual(branching.add_validation(self.ctx(), 'testing', 'full', ['factory', 'product']), 0)
        self.assertIn(commands.approvals(self.ctx().model), output.getvalue())  # the number comes from work_order_approvals
        self.assertIn('already says this; nothing to propose', output.getvalue())  # testing is unchanged
        expected = {'ftrutschnig/config-add-qa': lambda c: branches.with_validation(c, 'qa', 'none', []),
                    'ftrutschnig/config-change-release': lambda c: branches.with_production(c, 'release', 'initiated'),
                    'ftrutschnig/config-remove-staging': lambda c: branches.without(c, 'staging')}
        self.assertEqual([call['branch'] for call in calls], list(expected))
        for call, (branch, change) in zip(calls, expected.items()):
            self.assertEqual((call['base'], call['task']), ('production', None))  # no advisory preflight
            self.assertEqual(git(self.origin, 'rev-parse', f'{branch}^'), production)
            self.assertEqual(git(self.origin, 'diff', '--name-only', production, branch), 'factory/config.json')
            after = git(self.origin, 'show', f'{branch}:factory/config.json') + '\n'
            self.assertEqual(self.outside_spans(after), self.outside_spans(before))
            self.assertEqual(json.loads(after), change(published))
            self.assertIn('Owner steps after the merge', call['body'])
            self.assertIn('settings.py diff', call['body'])
            self.assertNotIn('factory-handoff', call['body'])
        self.assertIn('git/refs -f ref=refs/heads/qa', calls[0]['body'])
        self.assertIn('into the config branch `production`', calls[0]['body'])
        for name, message in (('production', 'config or default branch'), ('testing', 'config or default branch'),
                              ('nope', 'not a listed branch')):
            with self.assertRaisesRegex(Blocked, message):
                branching.remove(self.ctx(), name)
        with self.assertRaisesRegex(Blocked, 'not a listed production branch'):
            branching.set_config(self.ctx(), 'testing')
        with self.assertRaisesRegex(Blocked, 'factory/config.json on production: the change would break the branch model'):
            branching.add_validation(self.ctx(), 'main', 'full', [])
        self.assertEqual(len(calls), 3)

    def test_set_config_branch_opens_the_pr_into_the_new_branch_first(self):
        published = self.publish_config(lambda config: branches.with_production(config, 'release', 'no'))
        git(self.seed, 'push', '--quiet', str(self.origin), 'production:release')
        tips = {name: git(self.origin, 'rev-parse', name) for name in ('release', 'production')}
        calls, patcher = self.submitted()
        with patcher, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.set_config(self.ctx(), 'release'), 0)
            self.assertEqual(branching.set_config(self.ctx(), 'production'), 0)
        self.assertIn('production is already the config branch; nothing to propose', output.getvalue())
        names = ['ftrutschnig/config-set-config-release-into-release', 'ftrutschnig/config-set-config-release-into-production']
        self.assertEqual([(call['branch'], call['base']) for call in calls], list(zip(names, ('release', 'production'))))
        for branch, base in zip(names, ('release', 'production')):
            self.assertEqual(git(self.origin, 'rev-parse', f'{branch}^'), tips[base])
            self.assertEqual(git(self.origin, 'diff', '--name-only', tips[base], branch), 'factory/config.json')
            self.assertEqual(json.loads(git(self.origin, 'show', f'{branch}:factory/config.json')),
                             branches.with_config_branch(published, 'release'))
        self.assertIn('work-order/config PR into the production branch `release`', calls[0]['body'])
        self.assertIn('work-order/config PR into the config branch `production`', calls[1]['body'])
        rerun = (f"`gh pr list --repo {REPOSITORY} --state open --limit 1000 --json number --jq '.[].number' | xargs -I{{}} gh "
                 f"workflow run factory.yml --repo {REPOSITORY} --ref release -f pr={{}} -f retry=true`")
        checks = [f"`gh pr list --repo {REPOSITORY} --state open --base {p} --limit 1000 --json number --jq '.[].number' | "
                  f"xargs -I{{}} gh workflow run factory-promotion.yml --repo {REPOSITORY} --ref release -f pr={{}}`"
                  for p in ('production', 'release')]
        steps = ['Right before merging, run `factory set config branch release` again', 'Merge the config PR into `release`', 'Then merge the config PR into `production`', 'settings.py apply',
                 'Do it right away', 'refs/heads/release', 'factory promote <validation branch> --to release',
                 'factory use branch release', rerun, *checks, 'The first push to `release`']
        for call in calls:
            positions = [call['body'].index(step) for step in steps]
            self.assertEqual(positions, sorted(positions))
            self.assertNotIn('commands stop', call['body'])
            self.assertIn('regenerate the diagram with `factory branches` in a later change', call['body'])
            self.assertEqual(call['body'].rstrip().splitlines()[-1][:3], '7. ')  # re-running the open PRs comes last
            self.assertIn(rerun, call['body'].rstrip().splitlines()[-1])
        with patcher, contextlib.redirect_stdout(io.StringIO()) as output:  # a rerun reuses both proposals
            self.assertEqual(branching.set_config(self.ctx(), 'release'), 0)
        self.assertEqual(output.getvalue().count('Reusing ftrutschnig/config-set-config-release-into-'), 2)
        self.assertEqual([call['head'] for call in calls[2:]], [git(self.origin, 'rev-parse', name) for name in names])

    def test_set_config_branch_refuses_a_branch_that_lags_behind_the_config_branch(self):
        self.publish_config(lambda config: branches.with_production(config, 'release', 'no'))
        git(self.seed, 'push', '--quiet', str(self.origin), 'production:release')  # release starts as a copy
        self.publish_config(lambda config: branches.with_validation(config, 'staging', 'tests', ['smoke']))  # later, production only
        data = json.loads((self.seed / 'factory/config.json').read_text())
        data['limits'] = {**data['limits'], 'max_rounds': data['limits']['max_rounds'] + 1}
        self.advance_origin('factory/config.json', 'production', json.dumps(data, indent=2) + '\n')
        self.advance_origin('docs/work/FACTORY-009.md', 'production', order('FACTORY-009'))
        self.advance_origin('docs/work/FACTORY-003.md', 'production', order('FACTORY-003', status='draft'))
        listed = git(self.origin, 'branch', '--list')
        calls, patcher = self.submitted()
        with patcher, self.assertRaises(Blocked) as refused:
            branching.set_config(self.ctx(), 'release')
        for expected in ('release cannot become the config branch yet',
                         'factory/config.json on release differs from production in branches, limits;',
                         'release lacks the work orders FACTORY-009;', 'work orders on release differ from production: FACTORY-003.',
                         'Bring production into a validation branch and promote it into release: if <V> does not contain '
                         'production yet, `factory promote <V> --to production` merges production into <V> (push it); then '
                         '`factory promote <V> --to release`'):
            self.assertIn(expected, str(refused.exception))
        self.assertEqual((calls, git(self.origin, 'branch', '--list')), ([], listed))  # nothing pushed or proposed
        git(self.seed, 'push', '--quiet', str(self.origin), 'production:release')  # release now holds production
        with patcher, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.set_config(self.ctx(), 'release'), 0)
        self.assertEqual([call['base'] for call in calls], ['release', 'production'])

    def test_branch_changes_wait_until_the_default_branch_names_the_config_branch(self):
        release, _ = self.switch_config('release')  # production and release name release; testing still names production
        checkouts.fetch_policy(self.control, self.config)
        ctx = self.ctx()
        self.assertEqual(ctx.model.config_branch, 'release')
        calls, patcher = self.submitted()
        remedy = 'bring the previous change into testing first: `factory promote testing --to release`'
        with patcher:
            with self.assertRaisesRegex(Blocked, 'default branch testing still names the config branch production, so a '
                                        'further change would need two hops: ' + re.escape(remedy)):
                branching.set_config(ctx, 'production')
            with self.assertRaisesRegex(Blocked, 'default branch testing still names production as the config branch.*'
                                        + re.escape(remedy) + ', then remove production'):
                branching.remove(ctx, 'production')
        self.assertEqual(calls, [])
        self.advance_origin('factory/config.json', 'testing', git(self.origin, 'show', 'release:factory/config.json') + '\n')
        with patcher, contextlib.redirect_stdout(io.StringIO()):  # testing carries the change: production may go
            self.assertEqual(branching.remove(ctx, 'production'), 0)
        self.assertEqual([(call['base'], call['branch']) for call in calls], [('release', 'ftrutschnig/config-remove-production')])
        self.assertEqual(git(self.origin, 'rev-parse', 'ftrutschnig/config-remove-production^'), release)

    def test_a_config_pr_branch_is_reused_reported_or_replaced(self):
        branch = 'ftrutschnig/config-add-qa'
        submitted = []
        with mock.patch.object(commands, 'run_session_submit', side_effect=lambda ctx, snapshot, args, on_created=None:
                               submitted.append(args)), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.add_validation(self.ctx(), 'qa', 'none', []), 1)  # pushed; no PR was created
        self.assertNotIn('--task', submitted[0])  # session.py submit without a preflight: approvals decide type (b)
        self.assertEqual(submitted[0][submitted[0].index('--base') + 1], 'production')
        pushed = git(self.origin, 'rev-parse', branch)
        calls, patcher = self.submitted()
        with patcher, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.add_validation(self.ctx(), 'qa', 'none', []), 0)
        self.assertIn(f'Reusing {branch} ({pushed[:12]})', output.getvalue())
        self.assertEqual((git(self.origin, 'rev-parse', branch), calls[-1]['head'], calls[-1]['branch'], calls[-1]['task']),
                         (pushed, pushed, branch, None))  # the rerun opens the PR, again without a preflight
        moved = self.advance_origin('docs/later.md', 'production')  # the old proposal no longer sits on the config tip
        with self.submitted(calls)[1], mock.patch.object(common, 'ask', return_value=False), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(Blocked, 'nothing proposed'):
            branching.add_validation(self.ctx(), 'qa', 'none', [])
        self.assertEqual((git(self.origin, 'rev-parse', branch), len(calls)), (pushed, 1))
        with self.submitted(calls)[1], mock.patch.object(common, 'ask', return_value=True) as ask, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.add_validation(self.ctx(), 'qa', 'none', []), 0)
        ask.assert_called_once_with(f'Replace {branch} with this proposal?')
        replaced = git(self.origin, 'rev-parse', branch)
        self.assertEqual((git(self.origin, 'rev-parse', f'{branch}^'), calls[-1]['head']), (moved, replaced))
        maintainer = self.config['maintainers'][0]
        ctx = self.ctx()
        ctx.gh.pulls = [{'number': 9, 'html_url': 'https://github.com/x/pull/9', 'base': {'ref': 'production'},
                         'head': {'ref': branch, 'repo': {'full_name': REPOSITORY}},
                         'user': {'id': maintainer['id'], 'login': maintainer['login']}}]
        with self.submitted(calls)[1], contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.add_validation(ctx, 'qa', 'none', []), 0)
        self.assertIn(f'Pull request #9 of {branch} into production is already open', output.getvalue())
        self.assertEqual((git(self.origin, 'rev-parse', branch), len(calls)), (replaced, 2))
        ctx.gh.pulls[0]['draft'] = True  # e.g. session.py left it a draft when its verification failed
        with self.submitted(calls)[1], contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.add_validation(ctx, 'qa', 'none', []), 1)
        self.assertIn(f'Pull request #9 of {branch} into production is open as a draft', output.getvalue())
        self.assertIn(f'`gh pr ready 9 --repo {REPOSITORY}`', output.getvalue())
        self.assertEqual((git(self.origin, 'rev-parse', branch), len(calls)), (replaced, 2))

    def test_work_order_and_config_prs_skip_the_advisory_preflight(self):
        captured, ctx = [], self.ctx()
        with mock.patch.object(commands, 'run_session_submit', side_effect=lambda ctx, snapshot, args, on_created=None:
                               captured.append(args) or 5):
            for task in (None, 'docs/work/FACTORY-SMOKE.md'):
                self.assertEqual(commands.session_submit(ctx, self.tmp, task, 'title', self.tmp / 'body.md',
                                                         base='production' if task is None else 'testing'), 5)
        self.assertNotIn('--task', captured[0])
        self.assertEqual(captured[1][:4], ['--task', 'docs/work/FACTORY-SMOKE.md', '--base', 'testing'])
        # An open draft work-order PR becomes ready without any model call.
        gh = mock.Mock()
        with mock.patch.object(type(ctx), 'gh', new_callable=mock.PropertyMock, return_value=gh), \
                mock.patch.object(commands, 'preflight') as preflight, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(commands.finish_open_pr(ctx, {'number': 7, 'draft': True, 'base': {'ref': 'production'}},
                                                     'a' * 40, 'ftrutschnig/new-workorders', None, []), 0)
        preflight.assert_not_called()
        gh.command.assert_called_once_with(['pr', 'ready', '7', '--repo', REPOSITORY])
        self.assertIn('Pull request #7 is ready for review.', output.getvalue())

    def test_use_branch_switches_a_clean_control_to_listed_branches_only(self):
        common.CONFIG_FILE.write_text(json.dumps({'control': str(self.control), 'candidate': str(self.candidate),
                                                  'python': sys.executable, 'bin': str(self.tmp / 'bin')}))
        self.assertIsNone(checkouts.device()['branch'])
        ctx = self.ctx()
        git(self.seed, 'push', '--quiet', str(self.origin), 'testing:feature-x')
        with self.assertRaisesRegex(Blocked, 'feature-x is not a listed'):
            branching.use(ctx, 'feature-x')
        (self.control / 'stray.txt').write_text('x')
        with self.assertRaisesRegex(Blocked, 'untracked file stray.txt.*only when it is clean'):
            branching.use(ctx, 'testing')
        self.assertEqual(checkouts.current_branch(self.control), 'production')
        (self.control / 'stray.txt').unlink()
        newer = self.advance_origin()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.use(ctx, 'testing'), 0)
        self.assertIn('rules, policy and work orders still come from the config branch production', output.getvalue())
        self.assertEqual((checkouts.current_branch(self.control), git(self.control, 'rev-parse', 'HEAD')), ('testing', newer))
        self.assertEqual(checkouts.device()['branch'], 'testing')
        self.assertEqual(checkouts.update_control(self.control, self.config, branch='testing'), (newer, False))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(branching.use(ctx, 'production'), 0)
        self.assertEqual((checkouts.current_branch(self.control), checkouts.device()['branch']), ('production', 'production'))

    def promote_on_origin(self, squash=False):
        """A promotion testing → production merged on GitHub: a merge commit, or with squash one new commit."""
        git(self.seed, 'switch', '--quiet', 'production')
        if squash:
            git(self.seed, 'merge', '--quiet', '--squash', 'testing')
            git(self.seed, 'commit', '--quiet', '-m', 'Promote testing to production (#49)')
        else:
            git(self.seed, 'merge', '--quiet', '--no-ff', '-m', 'Promote testing to production (#49)', 'testing')
        git(self.seed, 'push', '--quiet', str(self.origin), 'production')
        return git(self.seed, 'rev-parse', 'HEAD')

    def commit_on_origin(self, branch, files=(), removed=()):
        git(self.seed, 'switch', '--quiet', branch)
        for name, text in dict(files).items():
            (self.seed / name).parent.mkdir(parents=True, exist_ok=True)
            (self.seed / name).write_text(text)
            git(self.seed, 'add', name)
        for name in removed:
            git(self.seed, 'rm', '--quiet', name)
        git(self.seed, 'commit', '--quiet', '-m', f'change {branch}')
        git(self.seed, 'push', '--quiet', str(self.origin), branch)
        return git(self.seed, 'rev-parse', 'HEAD')

    def test_promote_merges_production_into_the_validation_branch_without_pushing(self):
        production = self.advance_origin('docs/production-only.md', 'production')
        testing = self.advance_origin('docs/testing-only.md', 'testing')  # testing has its own commit: no fast-forward
        ctx = self.ctx()
        (self.candidate / 'scratch.txt').write_text('x')
        with self.assertRaisesRegex(Blocked, 'uncommitted or untracked files'):
            branching.promote(ctx, 'testing')
        (self.candidate / 'scratch.txt').unlink()
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/elsewhere')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)
        self.assertEqual(checkouts.current_branch(self.candidate), 'testing')
        parents = git(self.candidate, 'rev-list', '--parents', '-n', '1', 'HEAD').split()[1:]
        self.assertEqual(parents, [testing, production])
        self.assertEqual(git(self.origin, 'rev-parse', 'testing'), testing)  # never pushed
        self.assertIn('push origin testing', output.getvalue())
        self.assertIn('again to open or update the promotion PR', output.getvalue())
        self.assertEqual(ctx.gh.created, [])
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as warned:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)
        self.assertIn('not on GitHub yet', warned.getvalue())
        self.assertIn('already contains production', output.getvalue())

    def test_promote_leaves_conflicts_to_the_maintainer(self):
        self.advance_origin('docs/guide.md', 'production', 'production\n')
        self.advance_origin('docs/guide.md', 'testing', 'testing\n')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(self.ctx(), 'testing'), 1)
        self.assertIn('docs/guide.md', output.getvalue())
        self.assertIn('git merge --abort', output.getvalue())
        self.assertTrue((self.candidate / '.git/MERGE_HEAD').is_file())
        self.assertIn('<<<<<<<', (self.candidate / 'docs/guide.md').read_text())
        with self.assertRaisesRegex(Blocked, 'uncommitted or untracked'):
            branching.promote(self.ctx(), 'testing')

    def test_promote_opens_one_promotion_and_never_merges(self):
        self.advance_origin('docs/testing-only.md', 'testing')  # something to promote
        ctx = self.ctx()
        with self.assertRaisesRegex(Blocked, 'not a listed validation branch'):
            branching.promote(ctx, 'production')
        with self.assertRaisesRegex(Blocked, 'not a listed production branch'):
            branching.promote(ctx, 'testing', 'testing')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)
        created = ctx.gh.created[0]
        self.assertEqual((created['head'], created['base'], created['title']), ('testing', 'production', 'Promote testing to production'))
        self.assertIn('factory/production/production', created['body'])
        self.assertIn('/review', output.getvalue())
        own = {'number': 77, 'base': {'ref': 'production'}, 'html_url': 'https://github.com/x/pull/77',
               'head': {'ref': 'testing', 'repo': {'full_name': REPOSITORY}}}
        ctx.gh.pulls = [own]
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)  # e.g. right after the merge-back it asked for
        tip = git(self.origin, 'rev-parse', 'testing')
        self.assertIn(f'Promotion #77 (testing → production) is already open and now carries {tip[:12]}', output.getvalue())
        self.assertIn('/review', output.getvalue())
        staging = self.ctx(branches.with_validation(self.config, 'staging', 'tests', ['smoke']))
        staging.gh.pulls = [own, {**own, 'number': 78, 'head': {'ref': 'staging', 'repo': {'full_name': REPOSITORY}}}]
        with self.assertRaisesRegex(Blocked, r'already open: #78 \(staging → production\); merge or close it first'):
            branching.promote(staging, 'testing')
        self.assertEqual(len(ctx.gh.created) + len(staging.gh.created), 1)
        several = self.ctx(branches.with_production(self.config, 'release', 'no'))
        with self.assertRaisesRegex(Blocked, 'choose one with --to'):
            branching.promote(several, 'testing')

    def test_promote_fast_forwards_after_a_merge_commit_promotion(self):
        self.advance_origin('tools/factory/b.py', 'testing', 'VALUE = 2\n')
        production = self.promote_on_origin()
        ctx = self.ctx()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)
        self.assertEqual((checkouts.current_branch(self.candidate), checkouts.head(self.candidate)), ('testing', production))
        self.assertIn('Fast-forwarded testing to production', output.getvalue())
        self.assertIn('no merge commit was needed. Nothing was pushed.', output.getvalue())
        self.assertNotEqual(git(self.origin, 'rev-parse', 'testing'), production)  # never pushed
        git(self.candidate, 'push', '--quiet', str(self.origin), 'testing')  # the maintainer pushes it
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.promote(ctx, 'testing'), 0)
        self.assertIn('nothing to promote until testing has new commits', output.getvalue())
        self.assertEqual(ctx.gh.created, [])

    def test_update_fast_forwards_after_a_merge_commit_promotion(self):
        self.advance_origin('tools/factory/b.py', 'testing', 'VALUE = 2\n')  # the local testing is now behind GitHub
        production = self.promote_on_origin()
        testing = git(self.origin, 'rev-parse', 'testing')
        ctx = self.ctx()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.update(ctx), 0)  # the branch checked out in the candidate
        self.assertEqual((checkouts.current_branch(self.candidate), checkouts.head(self.candidate)), ('testing', production))
        self.assertEqual(git(self.origin, 'rev-parse', 'testing'), testing)  # never pushed
        self.assertIn(f'Fast-forwarded testing to production ({production[:12]}) in the candidate: no new commit. '
                      'Nothing was pushed.', output.getvalue())
        self.assertIn(f'git -C {shlex.quote(str(self.candidate))} push origin testing', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(branching.update(ctx, 'testing'), 0)
        self.assertIn('already contains production', output.getvalue())
        self.assertIn('up to date, nothing changed', output.getvalue())
        self.assertEqual(checkouts.head(self.candidate), production)

    def test_update_merges_after_a_squash_promotion_and_brings_only_work_orders(self):
        testing = self.advance_origin('tools/factory/b.py', 'testing', 'VALUE = 2\n')
        self.promote_on_origin(squash=True)  # production holds testing's content in a commit testing lacks
        production = self.advance_origin('docs/work/FACTORY-009.md', 'production', order('FACTORY-009') + 'tail \t\r\n')
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/elsewhere')
        git(self.candidate, 'branch', '--quiet', '-D', 'testing')  # created again from GitHub
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.update(self.ctx(), 'testing'), 0)
        self.assertEqual(checkouts.current_branch(self.candidate), 'testing')
        self.assertEqual(git(self.candidate, 'rev-list', '--parents', '-n', '1', 'HEAD').split()[1:], [testing, production])
        self.assertEqual(git(self.candidate, 'log', '-1', '--format=%s'), 'Merge production into testing (factory update)')
        self.assertEqual(git(self.candidate, 'diff', '--name-status', testing, 'HEAD'), 'A\tdocs/work/FACTORY-009.md')
        self.assertEqual(git(self.candidate, 'rev-parse', 'HEAD:docs/work/FACTORY-009.md'),
                         git(self.origin, 'rev-parse', 'production:docs/work/FACTORY-009.md'))  # byte-exact
        self.assertIn(f'merge commit {checkouts.head(self.candidate)[:12]}. Nothing was pushed.', output.getvalue())
        self.assertEqual(git(self.origin, 'rev-parse', 'testing'), testing)

    def test_update_refuses_other_paths_before_touching_the_working_tree(self):
        self.commit_on_origin('production', {**{f'docs/hotfix-{i:02}.md': f'{i}\n' for i in range(21)},
                                             'docs/work/FACTORY-009.md': order('FACTORY-009')})
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/elsewhere')
        head = checkouts.head(self.candidate)
        for target, remedy in (('testing', '`factory promote testing` brings all of production into it'),
                               (None, 'merge it by hand')):  # None: the feature branch checked out
            with self.assertRaises(Blocked) as raised:
                branching.update(self.ctx(), target)
            message = str(raised.exception)
            self.assertIn('would also change docs/hotfix-00.md, docs/hotfix-01.md', message)
            self.assertIn('docs/hotfix-19.md and 1 more. Nothing was changed', message)
            self.assertNotIn('hotfix-20', message)
            self.assertNotIn('FACTORY-009', message)  # a work order is in scope
            self.assertIn(remedy, message)
            self.assertEqual((checkouts.current_branch(self.candidate), checkouts.head(self.candidate)),
                             ('ftrutschnig/elsewhere', head))
            self.assertEqual(git(self.candidate, 'status', '--porcelain', '--ignored'), '')
            self.assertEqual(branching.local_tip(self.candidate, 'testing'), self.tip)

    def test_update_refuses_a_conflict_outside_the_scope(self):
        self.advance_origin('docs/guide.md', 'testing', 'testing\n')
        self.commit_on_origin('production', removed=['docs/guide.md'])  # modify/delete: the merged tree keeps testing's file
        with self.assertRaisesRegex(Blocked, r'would also change docs/guide\.md\. Nothing was changed'):
            branching.update(self.ctx())
        self.assertFalse((self.candidate / '.git/MERGE_HEAD').exists())
        self.assertEqual(git(self.candidate, 'status', '--porcelain'), '')
        self.assertEqual(checkouts.head(self.candidate), self.tip)  # not even fast-forwarded to GitHub's testing

    def test_update_leaves_a_config_conflict_to_the_maintainer(self):
        text = (self.seed / 'factory/config.json').read_text()
        self.assertIn('"max_rounds": 2', text)
        self.advance_origin('factory/config.json', 'production', text.replace('"max_rounds": 2', '"max_rounds": 3'))
        self.advance_origin('factory/config.json', 'testing', text.replace('"max_rounds": 2', '"max_rounds": 1'))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.update(self.ctx()), 1)
        self.assertIn('stopped on conflicts', output.getvalue())
        self.assertIn('  factory/config.json', output.getvalue())
        self.assertIn('git merge --abort', output.getvalue())
        self.assertIn('Nothing was pushed.', output.getvalue())
        self.assertTrue((self.candidate / '.git/MERGE_HEAD').is_file())
        self.assertIn('<<<<<<<', (self.candidate / 'factory/config.json').read_text())
        with self.assertRaisesRegex(Blocked, 'uncommitted or untracked'):
            branching.update(self.ctx())

    def test_update_refuses_production_dirty_and_diverged_and_keeps_unpushed_commits(self):
        ctx = self.ctx()
        for target, problem in (('production', 'production branch; factory never changes one'),
                                ('-x', 'not a valid branch name'), ('a..b', 'not a valid branch name'),
                                ('nobody/nothing', 'neither a branch of the candidate nor on GitHub')):
            with self.assertRaisesRegex(Blocked, problem):
                branching.update(ctx, target)
        git(self.candidate, 'switch', '--quiet', '--detach')
        with self.assertRaisesRegex(Blocked, 'no branch checked out'):
            branching.update(ctx)
        git(self.candidate, 'switch', '--quiet', 'testing')
        (self.candidate / 'scratch.txt').write_text('x')
        with self.assertRaisesRegex(Blocked, 'uncommitted or untracked files'):
            branching.update(ctx)
        (self.candidate / 'scratch.txt').unlink()
        production = self.advance_origin('docs/work/FACTORY-009.md', 'production', order('FACTORY-009'))
        (self.candidate / 'docs/local.md').write_text('local\n')
        git(self.candidate, 'add', 'docs/local.md')
        git(self.candidate, 'commit', '--quiet', '-m', 'local only')
        local = checkouts.head(self.candidate)
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as warned:
            self.assertEqual(branching.update(ctx), 0)
        self.assertIn('your local testing has commits that are not on GitHub yet', warned.getvalue())
        self.assertEqual(git(self.candidate, 'rev-list', '--parents', '-n', '1', 'HEAD').split()[1:], [local, production])
        self.assertIn('merge commit', output.getvalue())
        merged = checkouts.head(self.candidate)
        self.advance_origin('docs/remote.md', 'testing')
        self.advance_origin('docs/work/FACTORY-010.md', 'production', order('FACTORY-010'))
        with self.assertRaisesRegex(Blocked, 'your local testing and testing on GitHub diverged'), \
                contextlib.redirect_stderr(io.StringIO()):
            branching.update(ctx)
        self.assertEqual(checkouts.head(self.candidate), merged)

    def test_update_of_a_feature_branch_goes_up_with_the_next_submit(self):
        production = self.advance_origin('docs/work/FACTORY-009.md', 'production', order('FACTORY-009'))
        git(self.candidate, 'switch', '--quiet', '-c', 'ftrutschnig/issue-57')
        (self.candidate / 'docs/feature.md').write_text('feature\n')
        git(self.candidate, 'add', 'docs/feature.md')
        git(self.candidate, 'commit', '--quiet', '-m', 'feature')
        feature = checkouts.head(self.candidate)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.update(self.ctx()), 0)
        self.assertEqual(checkouts.current_branch(self.candidate), 'ftrutschnig/issue-57')
        self.assertEqual(git(self.candidate, 'rev-list', '--parents', '-n', '1', 'HEAD').split()[1:], [feature, production])
        self.assertIn('it goes up with your next `factory submit`', output.getvalue())
        self.assertNotIn('push origin', output.getvalue())
        self.assertEqual(git(self.origin, 'branch', '--list', 'ftrutschnig/*'), '')

    def test_branches_write_the_mermaid_document_and_a_self_contained_page(self):
        ctx = self.ctx(branches.with_validation(self.config, 'staging', 'none', ['smoke']))
        opened = []
        with mock.patch.object(branching, 'open_file', side_effect=opened.append), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(branching.diagram(ctx, show=True), 0)
        text = (self.candidate / 'docs/factory-branches.md').read_text()
        for expected in ('```mermaid\nflowchart LR\n', 'v0["testing<br/>gate: full<br/>kinds: factory, product<br/>default branch"]',
                         'v1["staging<br/>gate: none<br/>kinds: smoke"]', 'p0["production<br/>review: maintainer-manual<br/>config branch"]',
                         'feature -->|PR| v0', 'feature -->|PR, not gated| v1', 'v1 -->|promotion PR| p0',
                         'p0 -. sync work orders .-> v0', '| `production` | production, config branch |'):
            self.assertIn(expected, text)
        self.assertIn('staging', output.getvalue())
        page = opened[0].read_text()
        self.assertTrue(opened[0].is_relative_to(common.STATE_DIR))
        for expected in ('<svg', 'class="sync"', 'flowchart LR', 'review: maintainer-manual'):
            self.assertIn(expected, page)
        for remote in ('http', '<script', '<link', '<img', '@import', 'url(http'):
            self.assertNotIn(remote, page)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            branching.diagram(ctx)
        self.assertIn('is up to date', output.getvalue())
        self.assertEqual(len(opened), 1)

    def test_diagram_arrows_never_hit_a_label_or_a_line_of_text(self):
        long = 'dev-' + 'x' * 36  # the longest name a branch may have
        config = self.config
        for name, gate, kinds in (('staging', 'none', ['smoke']), ('qa', 'tests', []), (long, 'none', [])):
            config = branches.with_validation(config, name, gate, kinds)
        for name, review in (('release', 'no'), ('hotfix', 'initiated')):
            config = branches.with_production(config, name, review)
        model = branches.parse(config)
        boxes, arrows, labels, (width, height) = branching.layout(model)
        self.assertEqual((len(boxes), len(arrows)), (8, 4 + 4 * 3 + 4))
        self.assertEqual([text[0] for *_, text in boxes.values() if text[-1] == 'not gated'], ['staging', long])
        # 11px edge labels (centred): at most 7px per character; 13px box lines: 8px per character of a bold name,
        # 6.5px of the others; an em above and a third of it below the baseline
        areas = [(x - 3.5 * len(text), y - 11, x + 3.5 * len(text), y + 4) for x, y, text in labels]
        for x, y, wide, tall, text in boxes.values():
            for i, line in enumerate(text):
                base = y + branching.PAD + branching.LINE * (i + 1) - 5
                area = (x + branching.PAD, base - 13, x + branching.PAD + (8 if i == 0 else 6.5) * len(line), base + 4)
                self.assertTrue(area[2] <= x + wide and y <= area[1] and area[3] <= y + tall, (line, area))  # inside
                areas.append(area)
        overlap = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        rects = [(x, y, x + wide, y + tall) for x, y, wide, tall, _ in boxes.values()]
        for i, one in enumerate(areas[:len(labels)]):
            self.assertTrue(0 <= one[0] and one[2] <= width and 0 <= one[1] and one[3] <= height, labels[i])
            for other in areas[i + 1:len(labels)] + rects:
                self.assertFalse(overlap(one, other), (labels[i], other))
        inside = lambda point, rect: rect[0] < point[0] < rect[2] and rect[1] < point[1] < rect[3]
        for kind, sx, sy, ex, ey, bend in arrows:  # each arrow is drawn as this cubic Bezier
            controls = ((sx, sy), (sx + bend, sy), (ex - bend, ey), (ex, ey))
            for step in range(65):
                t = step / 64
                weights = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3)
                point = tuple(sum(w * c[axis] for w, c in zip(weights, controls)) for axis in (0, 1))
                for area in areas + rects:
                    self.assertFalse(inside(point, area), (kind, point, area))
        drawn = {(start, end): arrow for (start, end, _, _), arrow in zip(branching.edges(model), arrows)}
        for key in [key for key in boxes if key.startswith('v')]:  # promotion and sync arrows of a pair run apart
            (_, _, leave, _, enter, _), (kind, _, back, _, arrive, _) = drawn[key, 'p0'], drawn['p0', key]
            self.assertEqual(kind, 'sync')
            self.assertGreaterEqual(min(abs(leave - arrive), abs(enter - back)), 15)
        page = branching.page(model)
        self.assertEqual(page.count('class="muted">not gated</text>'), 2)
        self.assertIn(f'>{long}</text>', page)
        self.assertEqual(branching.layout(branches.parse(self.config))[0]['v0'][2], branching.WIDTH)  # short names

def slugs(markdown):
    """GitHub heading anchors: lower case, punctuation removed, spaces to hyphens."""
    found, fenced = set(), False
    for line in markdown.splitlines():
        if line.startswith('```'):
            fenced = not fenced
        elif not fenced and re.match(r'#{1,6} ', line):
            title = line.lstrip('#').strip().lower()
            found.add(re.sub(r'[^\w\- ]', '', title).replace(' ', '-'))
    return found


class HelpAndInstallTests(unittest.TestCase):
    def test_every_command_explains_what_when_examples_and_documentation(self):
        for name, entry in helptext.COMMANDS.items():
            for field in ('summary', 'what', 'when'):
                self.assertGreater(len(entry[field]), 20, (name, field))
            self.assertTrue(entry['examples'] and all(e.startswith('factory ') for e in entry['examples']), name)
            for target in entry['docs']:
                path, _, anchor = target.partition('#')
                self.assertTrue((ROOT / path).is_file(), target)
                if anchor:
                    self.assertIn(anchor, slugs((ROOT / path).read_text()), target)
            self.assertIn('Documentation:', helptext.epilog(name))
        commands_in_overview = {name for _, names in helptext.OVERVIEW for name in names}
        self.assertEqual(commands_in_overview, set(helptext.COMMANDS))

    def test_help_needs_no_configuration_network_or_bytecode(self):
        with tempfile.TemporaryDirectory() as temp:
            tree = Path(temp) / 'repo'
            shutil.copytree(ROOT / 'tools/factory', tree / 'tools/factory', ignore=shutil.ignore_patterns('tests', '__pycache__'))
            (tree / 'factory').mkdir()
            (tree / 'factory/config.json').write_text(branch_fixture.text(ROOT))
            env = {'PATH': os.environ['PATH'], 'HOME': temp}
            for argv in (['--help'], ['issue', '--help'], ['fix', '--help'], ['submit', '--help'], ['promote', '--help'],
                         ['add', '--help'], ['update', '--help'], ['use', '--help'], ['branches', '--help']):
                result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), *argv],
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('factory', result.stdout)
            self.assertIn('When to use it', result.stdout)
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), '--version'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual((result.returncode, result.stdout), (0, 'factory 0.4.0\n'), result.stderr)
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), 'add',
                                     'validation', 'branch', 'staging', '--review', 'no'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn('needs --gate', result.stderr)
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), 'sync',
                                     'workorders'], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2)
            self.assertIn('`factory update [<target-branch>]`', result.stderr)
            self.assertEqual(list(tree.rglob('*.pyc')), [])
            self.assertFalse((Path(temp) / '.config').exists())

    def test_doctor_report_names_each_blocked_check_and_its_fix(self):
        import doctor
        report = doctor.inspect(ROOT, 'claude')  # the real producer, so its record keys and these lines stay in step
        blocked = [item['check'] for item in report['factory']['local_prerequisites'] if item['status'] == 'blocked']
        lines = commands.doctor_report(report)
        self.assertEqual(lines[0], f"doctor.py: {report['status']}" + ('' if blocked or report.get('reason') else '; no blocked checks'))
        for name in blocked:
            self.assertTrue(any(line.startswith(f'  blocked  {name}  → ') for line in lines), name)
        self.assertNotIn('?', ''.join(lines))
        sample = {'status': 'blocked', 'factory': {'local_prerequisites': [
            {'check': 'python', 'status': 'passed', 'detail': 'Python >= 3.11 required.', 'continuation': ''},
            {'check': 'docker_daemon', 'status': 'blocked', 'detail': 'Docker endpoint', 'continuation': 'Start Docker'},
            {'check': 'environment_ANTHROPIC_API_KEY', 'status': 'blocked', 'detail': 'd', 'continuation': 'Provide it'},
            {'check': 'environment_CONTEXT7_API_KEY', 'status': 'blocked', 'detail': 'd', 'continuation': 'Provide it'}]}}
        self.assertEqual(commands.doctor_report(sample, {'ANTHROPIC_API_KEY'}), [
            'doctor.py: blocked', '  blocked  docker_daemon  → Start Docker',
            '  expected environment_ANTHROPIC_API_KEY: the key is in the keychain; doctor.py sees only exported keys',
            '  blocked  environment_CONTEXT7_API_KEY  → Provide it'])  # not in the keychain: a real gap
        self.assertEqual(commands.doctor_report({'status': 'blocked', 'read_only': True, 'reason': 'Repository unreadable.'}),
                         ['doctor.py: blocked', '  Repository unreadable.'])
        self.assertEqual(commands.doctor_report({}), ['doctor.py: produced no report'])
        # Missing pinned check tools get one command; other tools keep doctor.py's own hint.
        tools = {'status': 'blocked', 'factory': {'local_prerequisites': [
            {'check': f'tool_{name}', 'status': 'blocked', 'detail': f'Required tool: {name}', 'continuation': f'Install {name}'}
            for name in ('actionlint', 'gh', 'gitleaks')]}}
        with tempfile.TemporaryDirectory() as temp:
            control = Path(temp) / 'a control'  # a space: every part of the command is quoted
            (control / 'factory').mkdir(parents=True)
            shutil.copy(ROOT / 'factory/tools.lock.json', control / 'factory/tools.lock.json')
            bin_dir = Path(temp) / 'bin'
            lines = commands.doctor_report(tools, (), lambda names: commands.tools_command(control, bin_dir, names))
            command = shlex.join(['python3', '-I', '-B', str(control / 'factory/install_tools.py'), '--lock',
                                  str(control / 'factory/tools.lock.json'), '--destination', str(bin_dir),
                                  '--only', 'actionlint', '--only', 'gitleaks'])
            self.assertEqual(lines, ['doctor.py: blocked', '  blocked  tool_actionlint  → installed by the command below',
                                     '  blocked  tool_gh  → Install gh', '  blocked  tool_gitleaks  → installed by the command below',
                                     f'  install the missing check tools: {command}'])
            self.assertEqual(shlex.split(command)[3], str(control / 'factory/install_tools.py'))
            self.assertIsNone(commands.tools_command(control, bin_dir, ['gh', 'docker']))
            self.assertIsNone(commands.tools_command(Path(temp) / 'missing', bin_dir, ['actionlint']))

    def wait(self, daemon_from=None, inspect_from=None, listed=True, hang=False, timeout=120, asleep=False,
             desktop=False, environ=None):
        """common.wait_for_docker against a fake docker on a simulated clock: the daemon answers from `daemon_from` s
        (None: never; `desktop`: once `docker desktop start` ran), the image inspects from `inspect_from` s (None: never;
        `asleep`: once a container ran, as Docker Desktop's resource saver wakes only then) and is `listed` meanwhile."""
        now, said, calls, state = [0.0], [], [], {'started': False, 'woken': False}

        def run(command, **kwargs):
            calls.append(command[1:])
            verb = command[1:3]
            if verb == ['info', '--format']:
                if hang:
                    raise subprocess.TimeoutExpired(command, 30)
                ok = (daemon_from is not None and now[0] >= daemon_from) or state['started']
            elif verb == ['image', 'inspect']:
                ok = (inspect_from is not None and now[0] >= inspect_from) or state['woken']
            elif verb == ['run', '--rm']:
                state['woken'] = ok = asleep  # a present image wakes the VM; --pull never fails for a missing one
            elif verb == ['desktop', 'start']:
                state['started'] = ok = desktop
            else:  # image ls --quiet
                return subprocess.CompletedProcess(command, 0, '3bf1ef2fc96c\n' if listed else '', '')
            return subprocess.CompletedProcess(command, 0 if ok else 1, 'answer\n' if ok else '', '')
        with mock.patch.object(common, 'tool', return_value='/usr/local/bin/docker'), \
                mock.patch.object(common, 'docker_host', return_value='unix:///docker.sock'), \
                mock.patch.dict(common.os.environ, environ or {}), \
                mock.patch.object(common.subprocess, 'run', side_effect=run), mock.patch.object(common, 'say', side_effect=said.append):
            if not environ:
                common.os.environ.pop('FACTORY_DOCKER_HOST', None)
            result = common.wait_for_docker('image:tag', timeout=timeout, interval=2, clock=lambda: now[0],
                                            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds))
        return result, now[0], said, calls

    def test_docker_is_nudged_awake_and_waited_for_until_it_holds_the_image(self):
        ready = ('unix:///docker.sock', None)
        result, waited, said, calls = self.wait(daemon_from=0, inspect_from=0)
        self.assertEqual((result, waited, said), (ready, 0, []))
        self.assertFalse(any(call[0] in ('run', 'desktop') for call in calls))  # an awake Docker is never nudged
        # Resource saver: queries answered without the VM, the image called missing until a container run wakes it.
        result, waited, said, calls = self.wait(daemon_from=0, asleep=True)
        self.assertEqual((result, waited, said), (ready, 0, []))
        self.assertEqual([call for call in calls if call[0] == 'run'],
                         [['run', '--rm', '--pull', 'never', '--network', 'none', '--cap-drop', 'ALL', '--read-only',
                           '--entrypoint', 'true', 'image:tag']])
        # Docker Desktop not running: started once, then used at once.
        result, waited, said, calls = self.wait(desktop=True, inspect_from=0)
        self.assertEqual((result, waited, said), (ready, 0, ['Starting Docker Desktop…']))
        self.assertEqual([call[:2] for call in calls if call[0] == 'desktop'], [['desktop', 'start']])
        # Another engine named by FACTORY_DOCKER_HOST is never replaced by starting Docker Desktop.
        result, waited, said, calls = self.wait(desktop=True, inspect_from=0, environ={'FACTORY_DOCKER_HOST': 'tcp://other:2375'})
        self.assertEqual((result, waited), (('unix:///docker.sock', 'docker'), 120))
        self.assertFalse(any(call[0] == 'desktop' for call in calls))
        # Docker Desktop starting slowly, then its image store calling the listed image missing: waited for.
        result, waited, said, _ = self.wait(daemon_from=6, inspect_from=12)
        self.assertEqual((result, waited), (ready, 12))
        self.assertEqual(said, ['Starting Docker Desktop…', 'Waiting for Docker to be ready, up to 120 s…'])
        # A missing image is never pulled and is reported soon after Docker answers, not after the whole wait.
        result, waited, _, calls = self.wait(daemon_from=4, listed=False)
        self.assertEqual((result, waited), (('unix:///docker.sock', 'image'), 14))
        self.assertEqual(sum(call[0] == 'run' for call in calls), 1)
        # Docker that never answers, or hangs, ends the wait at its limit.
        self.assertEqual(self.wait()[:2], (('unix:///docker.sock', 'docker'), 120))
        self.assertEqual(self.wait(hang=True)[:2], (('unix:///docker.sock', 'docker'), 120))
        # Docker answering late with the image still loading at the limit: the image is the problem.
        self.assertEqual(self.wait(daemon_from=110)[:2], (('unix:///docker.sock', 'image'), 120))
        with mock.patch.object(common, 'tool', return_value=None):
            self.assertEqual(common.wait_for_docker('image:tag'), ('', 'docker'))

    def test_author_runs_wait_for_docker_and_name_what_is_missing(self):
        for problem, message in (('docker', 'Docker did not answer within 120 s, not even after starting Docker Desktop'),
                                 ('image', 'is missing: `factory doctor` prints the build command')):
            with self.subTest(problem=problem), mock.patch.object(common, 'wait_for_docker', return_value=('unix:///d', problem)), \
                    self.assertRaisesRegex(Blocked, re.escape(message)):
                pipeline.docker_ready()
        with mock.patch.object(common, 'wait_for_docker', return_value=('unix:///d', None)) as wait:
            self.assertEqual(pipeline.docker_ready(), 'unix:///d')
        wait.assert_called_once_with(pipeline.clients.IMAGE)

    def test_sandbox_script_runs_the_author_image_without_network_or_writes(self):
        script = ROOT / 'tools/factory/sandbox-verify.sh'
        text = script.read_text()
        self.assertTrue(script.stat().st_mode & 0o111)
        self.assertEqual(subprocess.run(['sh', '-n', str(script)], capture_output=True).returncode, 0)
        for expected in ('--network none', '--read-only', '--cap-drop ALL', 'no-new-privileges', ',readonly"',
                         '--exclude .git', 'tools/factory/clients.py', 'verify.py --root /candidate --trusted-root /candidate --ci',
                         'sh "$1"'):
            self.assertIn(expected, text)

    def test_installer_is_executable_valid_bash(self):
        script = ROOT / 'tools/factory/cli/install-factory-cli.sh'
        self.assertTrue(script.stat().st_mode & 0o111)
        self.assertEqual(subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode, 0)

    def test_installer_trusts_the_config_branch_of_the_remote_default_branch(self):
        text = (ROOT / 'tools/factory/cli/install-factory-cli.sh').read_text()
        self.assertTrue(text.startswith('#!/usr/bin/env bash\n') and 'set -euo pipefail' in text)
        for expected in ('ls-remote --symref "$url" HEAD', 'refs/remotes/origin/$1:factory/config.json', 'config_of "$start"',
                         'fetch_branch "$repo" "$named"', 'fetch_branch "$repo" "$target"',
                         '"refs/remotes/origin/$config_branch:$self"', 'hash-object --no-filters',
                         'clone --quiet --branch "$branch"', '--branch) branch="$2"', '--branch "$branch" $keys',
                         'branch="${branch:-$config_branch}"', 'not listed in factory/config.json'):
            self.assertIn(expected, text)
        self.assertNotIn('reset', text)
        lines = [line for line in text.splitlines() if not line.lstrip().startswith('#')]
        self.assertTrue(all(' rm ' not in line and 'push' not in line for line in lines))
        parser = factory.build_parser()
        args = parser.parse_args(['_install', '--control-dir', '/c', '--candidate-dir', '/d', '--bin-dir', '/b',
                                  '--branch', 'testing'])
        self.assertEqual(args.branch, 'testing')

    def test_installer_follows_a_finished_change_of_the_config_branch_once(self):
        text = (ROOT / 'tools/factory/cli/install-factory-cli.sh').read_text()
        start = text.index('config_branch="$("$python" -I -c \'\n') + len('config_branch="$("$python" -I -c \'\n')
        code = text[start:text.index('\n\' "$named_config" "$target_config" "$named" "$branch" "$repository" "$not_yet")"', start)]
        config = branch_fixture.load(ROOT)
        listed = branches.with_production(config, 'release', 'no')
        moved = branches.with_config_branch(listed, 'release')

        def stage(first, second=None, branch=''):
            return subprocess.run([sys.executable, '-I', '-c', code, json.dumps(first), json.dumps(second) if second else '',
                                   'production', branch, REPOSITORY, 'finish the runbook'], capture_output=True, text=True, timeout=30)
        for first, second, branch, expected in ((config, None, '', 'production'), (config, None, 'testing', 'production'),
                                                (moved, moved, '', 'release'), (moved, moved, 'production', 'release')):
            result = stage(first, second, branch)
            self.assertEqual((result.returncode, result.stdout), (0, expected + '\n'), result.stderr)
        for first, second, branch, problem in (
                (moved, listed, '', 'names release, whose own configuration does not name itself'),
                ({**config, 'config_branch': 'testing'}, config, '', 'names testing, which it does not list as a production'),
                (moved, moved, 'feature-x', 'feature-x is not listed in factory/config.json on release'),
                (config, None, 'feature-x', 'feature-x is not listed in factory/config.json on production'),
                ({**config, 'repository': 'someone/else'}, None, '', 'names another repository')):
            result = stage(first, second, branch)
            self.assertEqual((result.returncode, result.stdout), (1, ''), problem)
            self.assertIn(problem, result.stderr)

    def stand_in(self, temp, rulesets=None):
        """The real installer against a local stand-in for GitHub: a bare origin behind git URL rewriting, and gh
        answering only the rulesets API (None: gh reads nothing, as when it is logged out). Stops before stage 2."""
        script = (ROOT / 'tools/factory/cli/install-factory-cli.sh').read_bytes()
        origin, seed, device, tools = temp / 'origin.git', temp / 'seed', temp / 'device', temp / 'tools'
        tools.mkdir()
        responses = temp / 'gh.json'
        (tools / 'gh').symlink_to(ROOT / 'tools/factory/tests/fixtures/fake_gh.py')
        # Each ruleset is a branch name, or (name, protected branch, enforcement) for a misleading one.
        entries = [(r, r, 'active') if isinstance(r, str) else r for r in rulesets or []]
        listing = [{'id': n, 'name': f'Factory production: {name}', 'enforcement': state} for n, (name, _, state) in enumerate(entries, 1)]
        canned = {f'repos/{REPOSITORY}/rulesets?per_page=100': listing}
        for n, (_, target, state) in enumerate(entries, 1):
            canned[f'repos/{REPOSITORY}/rulesets/{n}'] = {'id': n, 'enforcement': state, 'target': 'branch',
                                                          'conditions': {'ref_name': {'include': [f'refs/heads/{target}'], 'exclude': []}}}
        responses.write_text(json.dumps(canned if rulesets is not None else {}))
        env = {**ENV, 'HOME': str(temp), 'PATH': f"{tools}{os.pathsep}{ENV['PATH']}", 'FAKE_GH_RESPONSES': str(responses),
               'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': f'url.{origin.as_uri()}.insteadOf', 'GIT_CONFIG_VALUE_0': HTTPS}
        subprocess.run(['git', 'init', '-q', '--bare', str(origin)], env=ENV, check=True)
        subprocess.run(['git', 'init', '-q', str(device)], env=ENV, check=True)  # the checkout the installer runs from
        for path in ('tools/factory/cli/install-factory-cli.sh', 'factory/github-settings.json'):
            (device / path).parent.mkdir(parents=True, exist_ok=True)
            (device / path).write_bytes((ROOT / path).read_bytes())
        (device / 'factory/config.json').write_text(json.dumps(branch_fixture.load(ROOT)))

        def publish(name, files):
            """Branch `name` on the stand-in with exactly these files (bytes or JSON-able data; None leaves it out)."""
            shutil.rmtree(seed, ignore_errors=True)
            subprocess.run(['git', 'init', '-q', '-b', name, str(seed)], env=ENV, check=True)
            for path, data in files.items():
                if data is not None:
                    (seed / path).parent.mkdir(parents=True, exist_ok=True)
                    (seed / path).write_bytes(data if isinstance(data, bytes) else (json.dumps(data, indent=2) + '\n').encode())
            git(seed, 'add', '-A')
            git(seed, 'commit', '-q', '--allow-empty', '-m', name)
            git(seed, 'push', '-q', '--force', str(origin), f'{name}:{name}')

        def install(default, *options, control=None, answer=None):
            """Run stage 1; with `answer`, on a pseudo-terminal that types it at the first prompt."""
            git(origin, 'symbolic-ref', 'HEAD', f'refs/heads/{default}')
            args = ['bash', str(device / 'tools/factory/cli/install-factory-cli.sh'), '--control-dir', str(control or temp / 'control'),
                    '--candidate-dir', str(temp / 'candidate'), '--bin-dir', str(temp / 'bin'), *options]
            if answer is None:
                return subprocess.run(args, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
            import pty
            import select
            pid, fd = pty.fork()  # the child gets the terminal as stdin and as /dev/tty
            if pid == 0:
                os.execvpe('bash', args, env)
            output, sent, deadline = b'', False, time.monotonic() + 120
            while time.monotonic() < deadline:
                if select.select([fd], [], [], 1)[0]:
                    try:
                        chunk = os.read(fd, 4096)
                    except OSError:
                        break  # the child closed the terminal
                    if not chunk:
                        break
                    output += chunk
                    if not sent and b'Number (1-' in output:
                        os.write(fd, answer.encode() + b'\n')
                        sent = True
            os.close(fd)
            code = os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1])
            return subprocess.CompletedProcess(args, code, '', output.decode(errors='replace'))

        def dirty_control():
            """A control directory that passes nothing: reaching its refusal proves every configuration check passed."""
            shutil.rmtree(temp / 'dirty', ignore_errors=True)
            subprocess.run(['git', 'clone', '-q', str(origin), str(temp / 'dirty')], env=ENV, check=True)
            (temp / 'dirty/own.txt').write_text('own\n')
            return temp / 'dirty'
        return script, publish, install, dirty_control

    def test_installer_stage_one_explains_every_configuration_problem(self):
        config = branch_fixture.load(ROOT)
        legacy = {k: v for k, v in config.items() if k not in ('config_branch', 'branches')}  # before the branch model
        legacy['default_branch'] = branches.RESERVED[0]
        installer = 'tools/factory/cli/install-factory-cli.sh'
        hint = 'GitHub does not carry the branch model of FACTORY-008 yet'
        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            script, publish, install, dirty_control = self.stand_in(temp)  # no production ruleset readable yet
            cases = [  # (published branches, default branch, expected message)
                ({'old': {'factory/config.json': legacy}}, 'old',
                 'factory/config.json on old names no config branch (config_branch): ' + hint),
                ({'old': {'factory/config.json': None, 'README.md': b'x\n'}}, 'old', 'origin/old has no factory/config.json: ' + hint),
                ({'old': {'factory/config.json': b'{not json\n'}}, 'old', 'factory/config.json on old is not valid JSON'),
                ({'testing': {'factory/config.json': config}}, 'testing',
                 'the config branch that testing names is not on GitHub; ' + hint),
                ({'production': {'factory/config.json': {k: v for k, v in config.items() if k != 'branches'}}}, 'production',
                 'factory/config.json on production has no valid branch list (branches): ' + hint),
                ({'production': {'factory/config.json': config, installer: b'#!/usr/bin/env bash\nexit 1\n'}}, 'production',
                 'this installer differs from origin/production'),
            ]
            for published, default, expected in cases:
                with self.subTest(expected=expected):
                    for name, files in published.items():
                        publish(name, files)
                    result = install(default)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(expected, result.stderr)
                    self.assertIn(f'the default branch {default} names the config branch', result.stderr)  # the fallback
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertFalse((temp / 'control').exists())  # nothing cloned
            # A valid stand-in passes every configuration check and reaches the control checkout, which it refuses here.
            publish('production', {'factory/config.json': config, installer: script})
            result = install('production', control=dirty_control())
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn(f"control checkout {temp / 'dirty'} is not a clean clone of production", result.stderr)

    def test_installer_starts_from_the_production_branches_github_protects(self):
        config = branch_fixture.load(ROOT)
        listed = branches.with_production(config, 'release', 'no')
        legacy = {k: v for k, v in config.items() if k not in ('config_branch', 'branches')}
        installer = 'tools/factory/cli/install-factory-cli.sh'
        for rulesets, options, expected in (
                # One protected production branch: taken, whatever the default branch carries.
                (['production'], (), 'not a clean clone of production'),
                # Several: asked on a terminal; without one, named with --config-branch.
                (['production', 'release'], (), 'GitHub protects several production branches (production release): '
                                                 'choose one with --config-branch NAME'),
                (['production', 'release'], ('--config-branch', 'release'), 'not a clean clone of production'),
                (['production', 'release'], ('--config-branch', 'testing'),
                 'testing is not protected as a production branch on GitHub; choose one of: production release'),
                # Only an active ruleset that protects exactly the branch counts; otherwise the default branch is read.
                ([('production', 'testing', 'active')], (), 'factory/config.json on old names no config branch'),
                ([('production', 'production', 'disabled')], (), 'factory/config.json on old names no config branch'),
                # The configuration may not lead to a config branch that GitHub does not protect.
                (['release'], (), 'the config branch production is not protected as a production branch on GitHub (release); refusing')):
            with self.subTest(rulesets=rulesets, options=options), tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                script, publish, install, dirty_control = self.stand_in(temp, rulesets)
                publish('old', {'factory/config.json': legacy})  # the default branch before the branch model
                for name in ('production', 'release'):
                    publish(name, {'factory/config.json': listed, installer: script})
                result = install('old', *options, control=dirty_control())
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                if expected.startswith('not a clean clone'):
                    self.assertNotIn('the default branch', result.stderr)  # it never read the default branch
        # On a terminal, several protected production branches are listed and the maintainer picks one by number.
        for answer, expected in (('2', 'not a clean clone of production'), ('9', 'no valid choice: 9'), ('x', 'no valid choice: x')):
            with self.subTest(answer=answer), tempfile.TemporaryDirectory() as temp:
                temp = Path(temp)
                script, publish, install, dirty_control = self.stand_in(temp, ['production', 'release'])
                publish('old', {'factory/config.json': legacy})
                for name in ('production', 'release'):
                    publish(name, {'factory/config.json': listed, installer: script})
                result = install('old', control=dirty_control(), answer=answer)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('GitHub protects several production branches; take the initial configuration from:', result.stderr)
                self.assertIn('1) production', result.stderr)
                self.assertIn('2) release', result.stderr)
                self.assertIn(expected, result.stderr)  # '2': release names production, which names itself

    def test_no_main_literal_remains_in_the_cli(self):
        for path in sorted((ROOT / 'tools/factory/cli').iterdir()):
            if path.is_file():
                self.assertNotRegex(path.read_text(), r'\bmain\b', path.name)

    def test_option_combinations_are_checked_before_any_network(self):
        parser = factory.build_parser()
        for argv, problem in ((['add', 'production', 'branch', 'x', '--review', 'no', '--gate', 'full'], 'needs --review'),
                              (['add', 'validation', 'branch', 'x', '--gate', 'full', '--kinds', 'factory,bogus'], 'distinct')):
            self.assertIn(problem, factory.misuse(parser.parse_args(argv)), argv)
        args = parser.parse_args(['add', 'validation', 'branch', 'x', '--gate', 'tests', '--kinds', 'smoke, factory'])
        self.assertIsNone(factory.misuse(args))
        self.assertEqual(args.kinds, ['smoke', 'factory'])
        self.assertIsNone(factory.misuse(parser.parse_args(['update', 'testing'])))
        # The replaced sync names factory update and exits 2, before any configuration, lock or network.
        for argv in (['sync', 'workorders'], ['sync', 'workorder', '9'], ['sync']):
            with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()) as stderr, \
                    mock.patch.object(factory, 'dispatch', side_effect=AssertionError('dispatched')):
                factory.entry(argv)
            self.assertEqual(raised.exception.code, 2, argv)
            self.assertIn('was replaced by `factory update [<target-branch>]`', stderr.getvalue())
        self.assertNotIn('sync', helptext.overview())

    def test_shim_is_marked_quoted_and_never_replaces_foreign_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'factory'
            install.write_shim(target, '/usr/bin/python3', Path('/a b/control'))
            text = target.read_text()
            self.assertIn(install.MARKER, text)
            self.assertIn("'/a b/control/tools/factory/cli/factory.py' \"$@\"", text)
            self.assertIn(' -I -S -B ', text)
            self.assertTrue(target.stat().st_mode & 0o111)
            install.write_shim(target, '/usr/bin/python3', Path('/control'))
            foreign = Path(temp) / 'foreign'
            foreign.write_text('#!/bin/sh\necho mine\n')
            with self.assertRaisesRegex(Blocked, 'not the factory shim'):
                install.write_shim(foreign, '/usr/bin/python3', Path('/control'))
            link = Path(temp) / 'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(Blocked, 'not the factory shim'):
                install.write_shim(link, '/usr/bin/python3', Path('/control'))

    def test_path_block_is_added_once_and_only_when_needed(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(install, 'RC_FILE', Path(temp) / '.zshrc'):
            bin_dir = Path(temp) / 'my bin'
            with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}):
                self.assertTrue(install.path_block(bin_dir))
                self.assertFalse(install.path_block(bin_dir))
            self.assertEqual(install.RC_FILE.read_text().count(install.BLOCK[0]), 1)
            self.assertIn("export PATH=\"$PATH\":'" + str(bin_dir) + "'", install.RC_FILE.read_text())
            with mock.patch.dict(os.environ, {'PATH': f'/usr/bin:{bin_dir}'}):
                self.assertFalse(install.path_block(bin_dir))


if __name__ == '__main__':
    unittest.main()
