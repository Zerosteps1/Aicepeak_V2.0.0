"""Sandboxed steps: exact flags, timeout cleanup, the shared deadline and safe reading of PR-written result files."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_testlib import ROOT
import sandbox

ID = 'sha256:' + 'c' * 64


class Argv(unittest.TestCase):
    def test_every_step_gets_the_full_sandbox_flags_and_only_the_given_mounts_and_env(self):
        argv = sandbox.argv(ID, ['dotnet', 'build'], 'factory-x-backend-build',
                            mounts=[('/host/work', '/work', False), ('/host/feeds', '/feeds', True)],
                            env={'NO_COLOR': '1'}, workdir='/work/backend', user='1001:121')
        self.assertEqual(argv[:2], ['docker', 'run'])
        for flags in (['--rm', '--init'], ['--network', 'none'], ['--read-only'], ['--cap-drop', 'ALL'],
                      ['--security-opt', 'no-new-privileges'], ['--pids-limit', '256'], ['--memory', '2g'], ['--cpus', '2'],
                      ['--tmpfs', '/tmp:rw,nosuid,nodev,size=256m'], ['--name', 'factory-x-backend-build'],
                      ['--log-driver', 'none'], ['--user', '1001:121'], ['--env', 'NO_COLOR=1'], ['--workdir', '/work/backend']):
            self.assertTrue(any(argv[i:i + len(flags)] == flags for i in range(len(argv))), flags)
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == '--mount'],
                         ['type=bind,src=/host/work,dst=/work', 'type=bind,src=/host/feeds,dst=/feeds,readonly'])
        self.assertEqual(argv[argv.index(ID):], [ID, 'dotnet', 'build'])
        self.assertNotIn('--privileged', argv)
        self.assertFalse(any('docker.sock' in a for a in argv))

    def test_mounts_and_env_values_cannot_inject_options(self):
        for mount in (('/a,dst=/etc', '/work', False), ('/a', '/work,readonly=false', False), ('relative', '/work', True)):
            with self.subTest(mount=mount), self.assertRaises(ValueError):
                sandbox.argv(ID, ['true'], 'n', mounts=[mount])
        with self.assertRaises(ValueError):
            sandbox.argv(ID, ['true'], 'n', env={'A\nB': '1'})
        with self.assertRaises(ValueError):
            sandbox.argv('latest', ['true'], 'n')


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.calls = []

    def test_output_goes_to_a_host_file_and_the_exit_code_is_returned(self):
        def docker(argv, **kwargs):
            self.calls.append((argv, kwargs))
            kwargs['stdout'].write(b'line 1\nPASS: done\n')
            return subprocess.CompletedProcess(argv, 3)

        code, seconds = sandbox.run(['docker', 'run', 'x'], 'factory-x', 60, self.tmp / 'log', run=docker)
        self.assertEqual(code, 3)
        self.assertGreaterEqual(seconds, 0)
        self.assertEqual(sandbox.tail(self.tmp / 'log'), 'line 1\nPASS: done\n')
        [(argv, kwargs)] = self.calls
        self.assertEqual(kwargs['stderr'], subprocess.STDOUT)
        self.assertEqual(kwargs['timeout'], 60)
        self.assertTrue(set(kwargs['env']) <= {'PATH', 'DOCKER_HOST', 'DOCKER_CONFIG'})

    def test_a_timeout_removes_the_container_and_returns_no_exit_code(self):
        def docker(argv, **kwargs):
            self.calls.append(argv)
            if argv[1] == 'run':
                raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
            return subprocess.CompletedProcess(argv, 0)

        code, _ = sandbox.run(['docker', 'run', 'x'], 'factory-x-step', 5, self.tmp / 'log', run=docker)
        self.assertIsNone(code)
        self.assertEqual(self.calls[-1], ['docker', 'rm', '--force', 'factory-x-step'])

    def test_the_tail_keeps_only_the_end_and_strips_nothing_but_invalid_bytes(self):
        (self.tmp / 'log').write_bytes(b'a' * 100 + b'\xff' + b'end')
        self.assertEqual(sandbox.tail(self.tmp / 'log', limit=4), '�end')
        self.assertEqual(sandbox.tail(self.tmp / 'missing'), '')


class Deadline(unittest.TestCase):
    def test_remaining_time_shrinks_and_never_goes_negative(self):
        now = [100.0]
        deadline = sandbox.Deadline(900, clock=lambda: now[0])
        self.assertEqual(deadline.remaining(600), 600)
        now[0] = 800.0
        self.assertEqual(deadline.remaining(600), 200)
        now[0] = 1200.0
        self.assertEqual(deadline.remaining(600), 0)


class Results(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)

    def test_only_regular_files_with_the_suffix_are_read_within_limits(self):
        (self.dir / 'a.trx').write_bytes(b'<a/>')
        (self.dir / 'b.trx').write_bytes(b'x' * 50)
        (self.dir / 'c.txt').write_bytes(b'ignored')
        secret = self.dir.parent / f'{self.dir.name}-secret'
        secret.write_bytes(b'secret')
        self.addCleanup(secret.unlink)
        (self.dir / 'link.trx').symlink_to(secret)
        os.mkfifo(self.dir / 'fifo.trx')
        (self.dir / 'sub.trx').mkdir()
        files, problems = sandbox.read_results(self.dir, '.trx', limit=10)
        self.assertEqual(files, [b'<a/>'])
        self.assertEqual(problems, 4)  # oversized, symlink, FIFO and directory are refused and counted

    def test_the_number_of_files_is_limited(self):
        for n in range(30):
            (self.dir / f'{n:02}.xml').write_bytes(b'<a/>')
        files, problems = sandbox.read_results(self.dir, '.xml', max_files=20)
        self.assertEqual((len(files), problems), (20, 1))

    def test_a_missing_directory_has_no_results(self):
        self.assertEqual(sandbox.read_results(self.dir / 'missing', '.xml'), ([], 0))


class Paths(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend/package.json').write_text('{}')

    def test_regular_files_and_real_directories_only_without_symlinks_on_the_way(self):
        self.assertTrue(sandbox.regular(self.root, 'frontend/package.json'))
        self.assertTrue(sandbox.directory(self.root, 'frontend'))
        (self.root / 'linked').symlink_to(self.root / 'frontend', target_is_directory=True)
        (self.root / 'frontend/lock.json').symlink_to(self.root / 'frontend/package.json')
        for path in ('linked/package.json', 'frontend/lock.json', 'frontend/missing.json', 'frontend', '../x', ''):
            self.assertFalse(sandbox.regular(self.root, path), path)
        self.assertFalse(sandbox.directory(self.root, 'linked'))
        self.assertFalse(sandbox.directory(self.root, 'frontend/package.json'))


if __name__ == '__main__':
    unittest.main()
