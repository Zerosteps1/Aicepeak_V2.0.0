"""The steps of the deterministic test stage: trusted commands, isolation, dependencies and results per step."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory_testlib import ROOT
import dependencies
import evidence
import sandbox
import steps

ID = 'sha256:' + 'c' * 64
FIXTURES = ROOT / 'tools/factory/tests/fixtures/product'


def candidate(root, backend=True, frontend=True):
    """A minimal candidate: recorded copies of the product's manifests and lock files (fixtures, so that a PR's own
    product files never decide the factory's tests), and the files the result fixtures point at."""
    if backend:
        (root / 'backend/Aicepeak.Api.Tests').mkdir(parents=True)
        (root / 'backend/Aicepeak.slnx').write_text('<Solution />')
        shutil.copy2(FIXTURES / 'nuget-lock.json', root / 'backend/packages.lock.json')
        (root / 'backend/Aicepeak.Api.Tests/FixtureTests.cs').write_text('x')
        (root / 'backend/Broken.cs').write_text('x')
    if frontend:
        (root / 'frontend/src').mkdir(parents=True)
        shutil.copy2(FIXTURES / 'npm-manifest.json', root / 'frontend/package.json')
        shutil.copy2(FIXTURES / 'npm-lock.json', root / 'frontend/package-lock.json')
        (root / 'frontend/src/fixture.test.ts').write_text('x')
        (root / 'frontend/src/broken.ts').write_text('x')
    return root


class FakeDocker:
    """Answers docker runs by container name: exit code, log text and result files written into the /results mount."""
    def __init__(self, codes=None, logs=None, results=None, timeouts=()):
        self.codes, self.logs, self.results, self.timeouts = codes or {}, logs or {}, results or {}, timeouts
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if argv[1] == 'rm':
            return subprocess.CompletedProcess(argv, 0)
        step = argv[argv.index('--name') + 1].split('-', 2)[2]
        mounts = {spec.split(',')[2][4:]: spec.split(',')[1][4:] for spec in (argv[i + 1] for i, a in enumerate(argv) if a == '--mount')}
        if step in self.timeouts:
            raise subprocess.TimeoutExpired(argv, kwargs['timeout'])
        if step == 'frontend-deps':
            (Path(mounts['/deps']) / 'node_modules/.bin').mkdir(parents=True)
        for name, data in self.results.get(step, {}).items():
            (Path(mounts['/results']) / name).write_bytes(data)
        kwargs['stdout'].write(self.logs.get(step, f'{step} output\n').encode())
        return subprocess.CompletedProcess(argv, self.codes.get(step, 0))

    def step_argv(self, step):
        return [argv for argv in self.calls if argv[1] == 'run' and argv[argv.index('--name') + 1].endswith('-' + step)]


def green_results():
    junit = (FIXTURES / 'vitest-junit.xml').read_bytes().replace(b'<failure', b'<x-failure').replace(b'</failure>', b'</x-failure>')
    trx = (FIXTURES / 'backend.trx').read_bytes().replace(b'outcome="Failed"', b'outcome="Passed"')
    return {'backend-test': {'backend.trx': trx}, 'frontend-test': {'junit.xml': junit}}


class Stage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.candidate = candidate(self.tmp / 'candidate')
        self.policy = self.tmp / 'policy'
        self.fetched = []

    def fetch(self, packages, feed, **kwargs):
        self.fetched.append(packages)
        Path(feed).mkdir(parents=True, exist_ok=True)
        return 0

    def run_steps(self, docker, seconds=900, **kwargs):
        clock = kwargs.pop('clock', None)
        deadline = sandbox.Deadline(seconds, **({'clock': clock} if clock else {}))
        with mock.patch.object(steps.dependencies, 'fetch_nuget', side_effect=self.fetch):
            return steps.run_all(ID, self.candidate, self.policy, tempfile.mkdtemp(dir=self.tmp), deadline, run=docker, **kwargs)

    def by_name(self, results):
        return {item['name']: item for item in results}

    def test_all_steps_run_in_order_and_pass(self):
        docker = FakeDocker(results=green_results())
        results = self.run_steps(docker)
        self.assertEqual([item['name'] for item in results], list(evidence.STEPS))
        self.assertEqual({item['status'] for item in results}, {'passed'}, results)
        self.assertEqual(len(self.fetched), 1)
        self.assertIn(('npgsql', '10.0.3'), self.fetched[0])
        backend_test = self.by_name(results)['backend-test']
        self.assertEqual(backend_test['note'], evidence.DATABASE_NOTE)
        self.assertEqual(evidence.counts(backend_test['cases'])['total'], 3)

    def test_commands_are_trusted_constants_whatever_the_package_scripts_say(self):
        package = json.loads((self.candidate / 'frontend/package.json').read_text())
        package['scripts'] = {'lint': 'true', 'test': 'true', 'build': 'true', 'prelint': 'curl evil'}
        (self.candidate / 'frontend/package.json').write_text(json.dumps(package))
        docker = FakeDocker(results=green_results())
        self.run_steps(docker)
        commands = {step: docker.step_argv(step)[0][docker.step_argv(step)[0].index(ID) + 1:] for step in
                    ('backend-build', 'backend-test', 'frontend-lint', 'frontend-test', 'frontend-build')}
        self.assertEqual(commands['frontend-lint'], steps.FRONTEND_LINT)
        self.assertEqual(commands['frontend-test'], steps.FRONTEND_TEST)
        self.assertEqual(commands['frontend-build'], steps.FRONTEND_BUILD)
        self.assertEqual(commands['backend-build'], steps.BACKEND_BUILD)
        self.assertEqual(commands['backend-test'], steps.BACKEND_TEST)
        self.assertIn('--filter', steps.BACKEND_TEST)
        self.assertFalse(any(argv[argv.index(ID) + 1:argv.index(ID) + 3] == ['npm', 'run'] for argv in docker.calls if argv[1] == 'run'))

    def test_every_sandbox_step_keeps_the_isolation_and_writable_steps_run_as_the_runner_user(self):
        docker = FakeDocker(results=green_results())
        with mock.patch.object(steps.os, 'getuid', return_value=1001), mock.patch.object(steps.os, 'getgid', return_value=121):
            self.run_steps(docker)
        for argv in docker.calls:
            if argv[1] != 'run':
                continue
            name = argv[argv.index('--name') + 1]
            with self.subTest(step=name):
                expected = 'bridge' if name.endswith('frontend-deps') else 'none'
                self.assertEqual(argv[argv.index('--network') + 1], expected)
                for flags in (['--read-only'], ['--cap-drop', 'ALL'], ['--security-opt', 'no-new-privileges'],
                              ['--pids-limit', '256'], ['--memory', '2g'], ['--cpus', '2'], ['--log-driver', 'none']):
                    self.assertTrue(any(argv[i:i + len(flags)] == flags for i in range(len(argv))), flags)
                if name.endswith('-factory'):
                    self.assertNotIn('--user', argv)
                    self.assertEqual([argv[i + 1].split(',')[-1] for i, a in enumerate(argv) if a == '--mount'], ['readonly', 'readonly'])
                else:
                    self.assertEqual(argv[argv.index('--user') + 1], '1001:121')
                    self.assertFalse(any(str(self.policy) in a for a in argv))

    def test_a_failing_step_does_not_stop_the_others(self):
        docker = FakeDocker(codes={'frontend-lint': 1, 'backend-build': 1},
                            logs={'frontend-lint': (FIXTURES / 'oxlint.log').read_text(),
                                  'backend-build': (FIXTURES / 'msbuild.log').read_text()},
                            results=green_results())
        results = self.by_name(self.run_steps(docker))
        self.assertEqual(results['frontend-lint']['status'], 'failed')
        self.assertEqual([e['path'] for e in results['frontend-lint']['errors']], ['frontend/src/broken.ts', 'frontend/src/fixture.test.ts'])
        self.assertEqual(results['frontend-test']['status'], 'passed')
        self.assertEqual(results['frontend-build']['status'], 'passed')
        self.assertEqual(results['backend-build']['status'], 'failed')
        self.assertEqual(results['backend-build']['errors'][0]['path'], 'backend/Broken.cs')
        self.assertEqual((results['backend-test']['status'], results['backend-test']['note']),
                         ('skipped', 'not run: backend-build failed'))
        self.assertEqual(docker.step_argv('backend-test'), [])

    def test_failed_tests_fail_the_step_even_with_exit_code_zero(self):
        docker = FakeDocker(results={'backend-test': {'backend.trx': (FIXTURES / 'backend.trx').read_bytes()},
                                     'frontend-test': {'junit.xml': (FIXTURES / 'vitest-junit.xml').read_bytes()}})
        results = self.by_name(self.run_steps(docker))
        self.assertEqual(results['backend-test']['status'], 'failed')
        self.assertEqual(results['frontend-test']['status'], 'failed')

    def test_a_test_step_without_readable_results_fails(self):
        results = self.by_name(self.run_steps(FakeDocker(results={'backend-test': {'backend.trx': b'<!DOCTYPE x><x/>'}})))
        self.assertEqual(results['backend-test']['status'], 'failed')
        self.assertIn('result', results['backend-test']['note'])
        self.assertEqual(results['frontend-test']['status'], 'failed')
        self.assertIn('no test results', results['frontend-test']['note'])

    def test_missing_or_symlinked_areas_are_not_present(self):
        shutil.rmtree(self.candidate / 'backend')
        shutil.move(self.candidate / 'frontend', self.tmp / 'elsewhere')
        (self.candidate / 'frontend').symlink_to(self.tmp / 'elsewhere', target_is_directory=True)
        docker = FakeDocker()
        results = self.run_steps(docker)
        self.assertEqual([item['status'] for item in results], ['passed'] + ['not present'] * 7)
        self.assertEqual([argv[argv.index('--name') + 1].split('-', 2)[2] for argv in docker.calls], ['factory'])
        self.assertEqual(self.fetched, [])

    def test_dependency_problems_fail_their_row_and_skip_the_area(self):
        lock = json.loads((self.candidate / 'frontend/package-lock.json').read_text())
        lock['packages']['node_modules/vite']['resolved'] = 'https://evil.example/vite.tgz'
        (self.candidate / 'frontend/package-lock.json').write_text(json.dumps(lock))
        (self.candidate / 'backend/packages.lock.json').unlink()
        docker = FakeDocker()
        results = self.by_name(self.run_steps(docker))
        self.assertEqual(results['frontend-deps']['status'], 'failed')
        self.assertIn('registry.npmjs.org', results['frontend-deps']['tail'])
        self.assertIn('registry.npmjs.org', results['frontend-deps']['note'])  # the reason shows next to the table
        self.assertIn('packages.lock.json', results['backend-deps']['note'])
        self.assertEqual(results['backend-deps']['status'], 'failed')
        self.assertIn('packages.lock.json', results['backend-deps']['tail'])
        for name in ('backend-build', 'backend-test', 'frontend-lint', 'frontend-test', 'frontend-build'):
            self.assertEqual((results[name]['status'], results[name]['note']), ('skipped', 'not run: dependencies unavailable'))
        self.assertEqual([argv[argv.index('--name') + 1].split('-', 2)[2] for argv in docker.calls], ['factory'])

    def test_a_failed_npm_fetch_or_committed_node_modules_fail_the_frontend_dependencies(self):
        results = self.by_name(self.run_steps(FakeDocker(codes={'frontend-deps': 1}, logs={'frontend-deps': 'npm ERR! 404'},
                                                         results=green_results())))
        self.assertEqual(results['frontend-deps']['status'], 'failed')
        self.assertIn('npm ERR! 404', results['frontend-deps']['tail'])
        self.assertEqual(results['frontend-test']['status'], 'skipped')
        (self.candidate / 'frontend/node_modules').mkdir()
        results = self.by_name(self.run_steps(FakeDocker(results=green_results())))
        self.assertIn('must not be committed', results['frontend-deps']['tail'])

    def test_the_npm_fetch_sees_only_the_manifest_and_the_lock(self):
        (self.candidate / 'frontend/.npmrc').write_text('registry=https://evil.example/\n')
        seen = []

        class Recording(FakeDocker):
            def __call__(self, argv, **kwargs):
                if argv[1] == 'run' and argv[argv.index('--name') + 1].endswith('frontend-deps'):
                    deps = next(a for a in argv if a.endswith(',dst=/deps')).split(',')[1][4:]
                    seen.append(sorted(os.listdir(deps)))
                return super().__call__(argv, **kwargs)

        self.run_steps(Recording(results=green_results()))
        self.assertEqual(seen, [['package-lock.json', 'package.json']])

    def test_timeouts_and_an_exhausted_budget_give_timeout_rows(self):
        docker = FakeDocker(timeouts=('frontend-test',), results=green_results())
        results = self.by_name(self.run_steps(docker))
        self.assertEqual(results['frontend-test']['status'], 'timeout')
        self.assertIn(['docker', 'rm', '--force'], [argv[:3] for argv in docker.calls])
        now = [0.0]
        docker = FakeDocker(results=green_results())

        def tick(argv, **kwargs):
            now[0] += 400
            return docker(argv, **kwargs)

        results = self.by_name(self.run_steps(tick, seconds=900, clock=lambda: now[0]))
        late = [name for name, item in results.items() if item['note'] == 'not run: time budget exhausted']
        self.assertTrue(late)
        self.assertTrue(all(results[name]['status'] == 'timeout' for name in late))


if __name__ == '__main__':
    unittest.main()
