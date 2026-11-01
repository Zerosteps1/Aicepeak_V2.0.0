"""Factory CLI boundaries: real Git repositories; GitHub, Docker, the keychain and models are faked."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path[:0] = [str(ROOT / 'tools/factory/cli'), str(ROOT / 'tools/factory')]
import checkouts  # noqa: E402
import commands  # noqa: E402
import common  # noqa: E402
import helptext  # noqa: E402
import install  # noqa: E402
import pipeline  # noqa: E402
import runs  # noqa: E402
import workorders  # noqa: E402
import engine  # noqa: E402
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
        self.pulls = []

    def pages(self, path, field=None):
        return self.pulls if '/pulls?state=open' in path else []

    def request(self, method, path, data=None):
        raise AssertionError((method, path))


class Repos(unittest.TestCase):
    """origin (bare, stands in for GitHub), a control clone and a candidate clone."""
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name).resolve()
        self.origin = self.tmp / 'origin.git'
        subprocess.run(['git', 'init', '--quiet', '--bare', '-b', 'main', str(self.origin)], env=ENV, check=True)
        self.seed = self.tmp / 'seed'
        self.seed.mkdir()
        git(self.seed, 'init', '--quiet', '-b', 'main')
        files = {'factory/config.json': (ROOT / 'factory/config.json').read_text(),
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
        git(self.seed, 'push', '--quiet', str(self.origin), 'main')
        self.control, self.candidate = self.clone('control'), self.clone('candidate')
        git(self.candidate, 'config', 'user.name', 'Fixture')
        git(self.candidate, 'config', 'user.email', 'fixture@example.invalid')
        self.main = git(self.control, 'rev-parse', 'HEAD')
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

    def clone(self, name):
        path = self.tmp / name
        subprocess.run(['git', 'clone', '--quiet', str(self.origin), str(path)], env=ENV, check=True)
        git(path, 'remote', 'set-url', 'origin', HTTPS)
        return path

    def advance_origin(self, name='docs/later.md'):
        (self.seed / name).write_text('later\n')
        git(self.seed, 'add', name)
        git(self.seed, 'commit', '--quiet', '-m', 'later')
        git(self.seed, 'push', '--quiet', str(self.origin), 'main')
        return git(self.seed, 'rev-parse', 'HEAD')

    def ctx(self):
        case = self

        class Context:
            candidate, control, config, sha, root, login = case.candidate, case.control, case.config, case.main, ROOT, 'ftrutschnig'
            gh = GitHub()

            def candidate_lock(self):
                return common.Lock(common.STATE_DIR / 'locks/candidate.lock', 'the candidate checkout')

            def main(self):
                return checkouts.fetch(self.candidate, self.config, 'main')['main']

            def identity(self):
                return ['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid']
        return Context()


class WorkOrderTests(Repos):
    def test_numbers_never_reuse_withdrawn_orders(self):
        used = workorders.numbers_ever_added(self.control, self.main)
        self.assertEqual(used, {1, 3, 6})
        self.assertEqual(workorders.next_name('factory', used), 'FACTORY-007')
        self.assertEqual(workorders.next_name('product', used | {12}), 'PRODUCT-013')
        self.assertEqual(workorders.names_on(self.control, self.main), ['ARCH-001', 'FACTORY-001', 'FACTORY-003'])

    def test_references_resolve_only_when_unique(self):
        names = workorders.names_on(self.control, self.main)
        self.assertEqual(workorders.resolve('3', names), 'FACTORY-003')
        self.assertEqual(workorders.resolve('003', names), 'FACTORY-003')
        self.assertEqual(workorders.resolve('factory-003', names), 'FACTORY-003')
        with self.assertRaisesRegex(Blocked, 'ARCH-001, FACTORY-001'):
            workorders.resolve('1', names)
        with self.assertRaisesRegex(Blocked, 'no work order 9'):
            workorders.resolve('9', names)

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
        self.assertIsNone(workorders.branch_order('main', names))


class CheckoutTests(Repos):
    def test_disposable_checkout_is_what_session_accepts(self):
        with checkouts.scratch('test-') as scratch:
            repo = checkouts.materialize(scratch / 'repo', self.main, objects=[checkouts.objects_dir(self.control)],
                                         origin=HTTPS, branch='feature/x')
            self.assertEqual(session.identity(repo, self.config), self.main)
            session.clean_tree(repo, self.main)
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
        newer = self.advance_origin()
        self.assertEqual(checkouts.update_control(self.control, self.config), (newer, True))
        self.assertEqual(git(self.control, 'rev-parse', 'HEAD'), newer)
        (self.control / '.DS_Store').write_text('x')
        with self.assertRaisesRegex(Blocked, r'untracked file \.DS_Store.*factory never deletes'):
            checkouts.update_control(self.control, self.config)
        (self.control / '.DS_Store').unlink()
        git(self.control, 'switch', '--quiet', '-c', 'other')
        with self.assertRaisesRegex(Blocked, 'stay on main'):
            checkouts.update_control(self.control, self.config)
        git(self.control, 'switch', '--quiet', 'main')
        (self.control / 'docs/guide.md').write_text('own\n')
        git(self.control, 'commit', '--quiet', '-am', 'own commit')
        self.advance_origin('docs/even-later.md')
        with self.assertRaisesRegex(Blocked, 'cannot fast-forward'):
            checkouts.update_control(self.control, self.config)

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
        tips = checkouts.fetch(self.candidate, self.config, 'main', 'ftrutschnig/FACTORY-003', 'missing')
        self.assertEqual(set(tips), {'main', 'ftrutschnig/FACTORY-003'})
        head = git(self.candidate, 'rev-parse', 'HEAD')
        self.assertEqual(checkouts.direct_imports(self.candidate, self.main, head), ['tools/factory/b.py'])


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
        commands.move_out(self.candidate, self.main, changes)
        self.assertFalse((work / 'FACTORY-007.md').exists())
        self.assertEqual((work / 'FACTORY-003.md').read_text(), 'edited again after the submission\n')
        self.assertTrue((work / 'ARCH-001.md').exists())
        self.assertEqual((self.candidate / 'docs/guide.md').read_text(), 'unrelated\n')

    def test_submit_workorders_pushes_only_orders_then_moves_them(self):
        (self.candidate / 'docs/work/FACTORY-007.md').write_text(order('FACTORY-007', status='draft'))
        (self.candidate / 'docs/guide.md').write_text('unrelated\n')
        calls = []
        with mock.patch.object(common, 'ask', return_value=True), \
                mock.patch.object(commands, 'session_submit', side_effect=lambda *a, **k: calls.append(a) or k['on_created'](12) or 12), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(commands.submit_workorders(self.ctx()), 0)
        self.assertEqual(calls[0][2], 'docs/work/FACTORY-001.md')
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

    def test_submit_commits_only_staged_files_and_never_main(self):
        with self.assertRaisesRegex(Blocked, 'never on main'):
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
        runs.update(path, order='FACTORY-003', status='running', pid=process.pid, pr=42)
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
        self.assertIn('gh workflow run factory.yml --ref main -f pr=42 -f retry=true', output.getvalue())


class PipelineTests(Repos):
    def runner(self, **data):
        runner = pipeline.Runner.__new__(pipeline.Runner)
        runner.path = self.tmp / 'run'
        runner.path.mkdir(exist_ok=True)
        runner.work = checkouts.materialize(runner.path / 'work', self.main, objects=[checkouts.objects_dir(self.control)],
                                            origin=HTTPS, branch='factory-run/test')
        runner.data = {'base': self.main, 'branch': 'ftrutschnig/FACTORY-003', 'branch_exists': False, 'kind': 'start',
                       'allowed_paths': ['docs/', 'tools/factory/'], 'request': None, 'pr': None, 'runner': 'claude',
                       'identity': {'name': 'Fixture', 'email': 'fixture@example.invalid'}, **data}
        runner.kind, runner.order, runner.task = runner.data['kind'], 'FACTORY-003', 'docs/work/FACTORY-003.md'
        runner.config, runner.control, runner.candidate = self.config, self.control, self.candidate
        runner.merged_main, runner.last_review, runner.spend, runner.url = None, None, 0.0, str(self.origin)
        return runner

    def commit(self, runner, files):
        for name, content in files.items():
            target = runner.work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content) if isinstance(content, bytes) else target.write_text(content)
        git(runner.work, 'add', '.')
        git(runner.work, 'commit', '--quiet', '-m', 'run')

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
        self.assertEqual(checkouts.current_branch(self.candidate), 'main')
        self.assertTrue((runner.path / 'changes.patch').stat().st_size)

    def test_result_after_main_moved_lands_on_the_new_main(self):
        runner = self.runner()
        newer = self.advance_origin()
        checkouts.update_control(self.control, self.config)
        git(runner.work, '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'merge', '--quiet', '--no-edit', newer)
        runner.merged_main = newer
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
        patch.write_bytes(git(runner.work, 'diff', '--binary', self.main, 'HEAD').encode() + b'\n')
        names = ['docs/new.md']
        self.assertIn('uncommitted changes', runner.apply_to_candidate(patch, self.main, names)[0])
        git(self.candidate, 'checkout', '--', 'docs/guide.md')
        git(self.candidate, 'switch', '--quiet', '-c', 'my-own-work')
        self.assertIn('does not switch away', runner.apply_to_candidate(patch, self.main, names)[0])

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
                mock.patch.object(runner, 'fetch_main', return_value=self.main), contextlib.redirect_stdout(io.StringIO()) as output:
            runner.publish()
        self.assertEqual(applied, [True])
        self.assertIn('the last preflight did not pass on exactly this result', output.getvalue())
        self.assertNotIn('ftrutschnig/FACTORY-003', git(self.origin, 'branch', '--list'))
        head = git(runner.work, 'rev-parse', 'HEAD')
        runner.last_review = ({'outcome': 'pass'}, head, self.main)
        self.commit(runner, {'README.md': 'protected\n'})
        runner.last_review = ({'outcome': 'pass'}, git(runner.work, 'rev-parse', 'HEAD'), self.main)
        runner.data['allowed_paths'].append('README.md')
        with mock.patch.object(runner, 'apply', side_effect=lambda: applied.append(True)), \
                mock.patch.object(runner, 'fetch_main', return_value=self.main), contextlib.redirect_stdout(io.StringIO()) as output:
            runner.publish()
        self.assertIn('protected paths are never pushed automatically: README.md', output.getvalue())
        self.assertNotIn('ftrutschnig/FACTORY-003', git(self.origin, 'branch', '--list'))


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
            shutil.copy(ROOT / 'factory/config.json', tree / 'factory/config.json')
            env = {'PATH': os.environ['PATH'], 'HOME': temp}
            for argv in (['--help'], ['issue', '--help'], ['fix', '--help'], ['submit', '--help']):
                result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), *argv],
                                        env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('factory', result.stdout)
            self.assertIn('When to use it', result.stdout)
            result = subprocess.run([sys.executable, '-I', '-S', '-B', str(tree / 'tools/factory/cli/factory.py'), '--version'],
                                    env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual((result.returncode, result.stdout), (0, 'factory 0.1.0\n'), result.stderr)
            self.assertEqual(list(tree.rglob('*.pyc')), [])
            self.assertFalse((Path(temp) / '.config').exists())

    def test_installer_is_executable_valid_bash(self):
        script = ROOT / 'tools/factory/cli/install-factory-cli.sh'
        self.assertTrue(script.stat().st_mode & 0o111)
        self.assertEqual(subprocess.run(['bash', '-n', str(script)], capture_output=True).returncode, 0)

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
