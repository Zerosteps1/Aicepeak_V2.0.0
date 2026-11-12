"""The steps of the deterministic test stage. Standard library only, trusted host code from the config branch.

Commands are constants here; a PR's package.json scripts or project files never decide what runs. Each step is its own
sandboxed docker run (tools/factory/sandbox.py) in the trusted test image; a failing step does not stop the others.
PR code runs only in those sandboxes: without network, secrets, Docker socket or the trusted checkout. Dependencies
come from the trusted fetch (tools/factory/dependencies.py). Steps that write get a throwaway copy of the candidate."""
import os
import shutil
import uuid
from pathlib import Path

import dependencies
import evidence
import sandbox

FACTORY = ['python3', '/policy/tools/factory/verify.py', '--root', '/candidate', '--trusted-root', '/policy', '--ci']
BACKEND_BUILD = ['dotnet', 'build', 'Aicepeak.slnx', '-warnaserror', '-nologo', '-tl:off', '--source', '/feeds/nuget',
                 '-p:RestoreConfigFile=/feeds/nuget.config', '-p:RestoreLockedMode=true', '-p:NuGetAudit=false']
BACKEND_TEST = ['dotnet', 'test', 'Aicepeak.slnx', '--no-build', '--nologo', '--filter', 'Category!=Database',
                '--logger', 'trx;LogFilePrefix=backend', '--results-directory', '/results']
FRONTEND_LINT = ['node_modules/.bin/oxlint', '--deny-warnings', '--format=unix']
FRONTEND_TEST = ['node_modules/.bin/vitest', 'run', '--reporter=default', '--reporter=junit',
                 '--outputFile.junit=/results/junit.xml']
FRONTEND_BUILD = ['sh', '-c', 'node_modules/.bin/tsc -b --pretty false && node_modules/.bin/vite build']
BACKEND_ENV = {'NUGET_PACKAGES': '/nuget', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1', 'DOTNET_NOLOGO': '1',
               'DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE': '1', 'MSBUILDDISABLENODEREUSE': '1',
               'DOTNET_CLI_DO_NOT_USE_MSBUILD_SERVER': '1', 'NO_COLOR': '1', 'TERM': 'dumb'}
FRONTEND_ENV = {'NO_COLOR': '1', 'FORCE_COLOR': '0', 'TERM': 'dumb', 'CI': 'true'}
TIMEOUTS = {'factory': 900, 'frontend-deps': 300, 'backend-build': 600, 'backend-test': 600, 'frontend-lint': 300,
            'frontend-test': 300, 'frontend-build': 300}
BACKEND = ('backend-deps', 'backend-build', 'backend-test')
FRONTEND = ('frontend-deps', 'frontend-lint', 'frontend-test', 'frontend-build')
BUDGET = 'not run: time budget exhausted'
NO_DEPENDENCIES = 'not run: dependencies unavailable'


class Stage:
    def __init__(self, image_id, candidate, policy, work, deadline, run=None):
        self.image_id, self.candidate, self.policy = image_id, Path(candidate), Path(policy)
        self.work, self.deadline, self.run = Path(work), deadline, run
        self.work.mkdir(parents=True, exist_ok=True)
        self.prefix = f'factory-{uuid.uuid4().hex[:12]}'
        self.user = f'{os.getuid()}:{os.getgid()}'

    def container(self, name):
        return f'{self.prefix}-{name}'

    def docker(self, name, command):
        """Run one container within the shared budget: (exit code or None on timeout, seconds, output tail), or
        None when no time is left."""
        timeout = self.deadline.remaining(TIMEOUTS[name])
        if timeout <= 0:
            return None
        log = self.work / f'{name}.log'
        code, seconds = sandbox.run(command, self.container(name), timeout, log, run=self.run)
        return code, seconds, sandbox.tail(log)

    def outcome(self, name, result, cases=(), errors=(), note=''):
        if result is None:
            return evidence.step(name, 'timeout', note=BUDGET)
        code, seconds, tail = result
        status = 'timeout' if code is None else 'passed' if code == 0 else 'failed'
        return evidence.step(name, status, seconds, code, tail, cases, errors, note)

    def sandboxed(self, name, command, mounts, env, workdir, area):
        argv = sandbox.argv(self.image_id, command, self.container(name), mounts=mounts, env=env, workdir=workdir, user=self.user)
        result = self.docker(name, argv)
        errors = evidence.parse_errors(result[2], self.candidate, area) if result else []
        return self.outcome(name, result, errors=errors)

    def tested(self, name, command, mounts, env, workdir, area, suffix, parse, note=''):
        results = self.work / f'{name}-results'
        results.mkdir()
        argv = sandbox.argv(self.image_id, command, self.container(name), mounts=[*mounts, (results, '/results', False)],
                            env=env, workdir=workdir, user=self.user)
        result = self.docker(name, argv)
        if result is None:
            return self.outcome(name, None)
        files, refused = sandbox.read_results(results, suffix)
        cases = []
        for data in files:
            try:
                cases += parse(data)['cases']
            except evidence.EvidenceError:
                refused += 1
        notes = [note] if note else []
        if refused:
            notes.append('a result file was refused')
        elif not files:
            notes.append('no test results were written')
        if (refused or not files) and result[0] == 0:
            result = (1, *result[1:])  # exit 0 without readable results is not a passed test run
        return self.outcome(name, result, cases, evidence.parse_errors(result[2], self.candidate, area), '; '.join(notes))

    def copy(self, area):
        """A writable throwaway copy of the candidate for one area (symlinks copied as links, never followed)."""
        target = self.work / f'{area}-work'
        shutil.copytree(self.candidate, target, symlinks=True)
        return target

    def factory(self):
        argv = sandbox.argv(self.image_id, FACTORY, self.container('factory'),
                            mounts=[(self.candidate, '/candidate', True), (self.policy, '/policy', True)], workdir='/candidate')
        return self.outcome('factory', self.docker('factory', argv))

    def backend(self):
        if not sandbox.regular(self.candidate, 'backend/Aicepeak.slnx'):
            return [evidence.step(name, 'not present') for name in BACKEND]
        feeds = self.work / 'feeds'
        started = self.deadline.clock()
        try:
            packages = dependencies.nuget_packages(self.candidate)
            dependencies.fetch_nuget(packages, feeds / 'nuget')
            dependencies.write_nuget_config(feeds)
        except dependencies.DependencyError as exc:
            return [evidence.step('backend-deps', 'failed', round(self.deadline.clock() - started, 1), tail=str(exc), note=str(exc)),
                    *(evidence.step(name, 'skipped', note=NO_DEPENDENCIES) for name in BACKEND[1:])]
        deps = evidence.step('backend-deps', 'passed', round(self.deadline.clock() - started, 1), 0,
                             tail=f'{len(packages)} NuGet packages from nuget.org')
        work, packages_folder = self.copy('backend'), self.work / 'nuget'
        packages_folder.mkdir()
        mounts = [(work, '/work', False), (feeds, '/feeds', True), (packages_folder, '/nuget', False)]
        build = self.sandboxed('backend-build', BACKEND_BUILD, mounts, BACKEND_ENV, '/work/backend', 'backend')
        if build['status'] != 'passed':
            return [deps, build, evidence.step('backend-test', 'skipped', note='not run: backend-build failed')]
        test = self.tested('backend-test', BACKEND_TEST, mounts, BACKEND_ENV, '/work/backend', 'backend', '.trx',
                           lambda data: evidence.parse_trx(data, self.candidate), evidence.DATABASE_NOTE)
        return [deps, build, test]

    def frontend(self):
        if not (sandbox.directory(self.candidate, 'frontend') and sandbox.regular(self.candidate, 'frontend/package.json')
                and sandbox.regular(self.candidate, 'frontend/package-lock.json')):
            return [evidence.step(name, 'not present') for name in FRONTEND]

        def unavailable(reason, result=None):
            code, seconds, tail = result or (None, None, reason)
            return [evidence.step('frontend-deps', 'failed', seconds, code, tail, note=reason),
                    *(evidence.step(name, 'skipped', note=NO_DEPENDENCIES) for name in FRONTEND[1:])]

        source = self.candidate / 'frontend'
        if os.path.lexists(source / 'node_modules'):
            return unavailable('frontend/node_modules must not be committed')
        manifest, lock = (source / 'package.json').read_bytes(), (source / 'package-lock.json').read_bytes()
        try:
            dependencies.npm_check(manifest, lock)
        except dependencies.DependencyError as exc:
            return unavailable(str(exc))
        deps = self.work / 'npm'
        deps.mkdir()
        (deps / 'package.json').write_bytes(manifest)
        (deps / 'package-lock.json').write_bytes(lock)
        result = self.docker('frontend-deps', dependencies.npm_fetch_argv(self.image_id, deps, self.container('frontend-deps'), self.user))
        if result is None:
            return [evidence.step('frontend-deps', 'timeout', note=BUDGET),
                    *(evidence.step(name, 'skipped', note=NO_DEPENDENCIES) for name in FRONTEND[1:])]
        if result[0] != 0 or not sandbox.directory(deps, 'node_modules'):
            return unavailable('npm ci failed', result if result[0] != 0 else (1, *result[1:]))
        work = self.copy('frontend')
        if not sandbox.directory(work, 'frontend') or os.path.lexists(work / 'frontend/node_modules'):
            return unavailable('unexpected frontend folder')
        os.rename(deps / 'node_modules', work / 'frontend/node_modules')
        fetched = self.outcome('frontend-deps', result)
        mounts = [(work, '/work', False)]
        return [fetched,
                self.sandboxed('frontend-lint', FRONTEND_LINT, mounts, FRONTEND_ENV, '/work/frontend', 'frontend'),
                self.tested('frontend-test', FRONTEND_TEST, mounts, FRONTEND_ENV, '/work/frontend', 'frontend', '.xml',
                            lambda data: evidence.parse_junit(data, self.candidate, 'frontend')),
                self.sandboxed('frontend-build', FRONTEND_BUILD, mounts, FRONTEND_ENV, '/work/frontend', 'frontend')]


def run_all(image_id, candidate, policy, work, deadline, run=None):
    """Every step of the stage, in evidence.STEPS order."""
    stage = Stage(image_id, candidate, policy, work, deadline, run)
    return [stage.factory(), *stage.backend(), *stage.frontend()]
