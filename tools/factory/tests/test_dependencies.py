"""Trusted dependency fetch: lock-file checks, the npm fetch container and NuGet downloads into an offline feed."""
import io
import json
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path

from factory_testlib import ROOT
import dependencies

ID = 'sha256:' + 'c' * 64
INTEGRITY = 'sha512-' + 'A' * 86 + '=='
HASH = 'B' * 86 + '=='


def lock(**packages):
    entries = {'': {'name': 'app', 'devDependencies': {'vite': '^8.3.6'}}}
    entries.update(packages or {'node_modules/vite': {'version': '8.3.8', 'resolved': dependencies.NPM_REGISTRY + 'vite/-/vite-8.3.8.tgz',
                                                     'integrity': INTEGRITY}})
    return json.dumps({'name': 'app', 'lockfileVersion': 3, 'packages': entries}).encode()


PACKAGE = json.dumps({'name': 'app', 'scripts': {'postinstall': 'curl evil'}, 'devDependencies': {'vite': '^8.3.6'}}).encode()


class NpmCheck(unittest.TestCase):
    def test_the_real_frontend_lock_passes(self):
        dependencies.npm_check((ROOT / 'frontend/package.json').read_bytes(), (ROOT / 'frontend/package-lock.json').read_bytes())

    def test_registry_packages_with_sha512_pass(self):
        dependencies.npm_check(PACKAGE, lock())
        dependencies.npm_check(PACKAGE, lock(**{'node_modules/a/node_modules/b': {'version': '1.0.0', 'inBundle': True}}))

    def test_non_registry_sources_and_weak_integrity_are_refused(self):
        good = {'version': '1', 'resolved': dependencies.NPM_REGISTRY + 'x/-/x-1.tgz', 'integrity': INTEGRITY}
        for name, entry, problem in (
                ('git', {**good, 'resolved': 'git+ssh://git@github.com/x/x.git'}, 'registry'),
                ('other host', {**good, 'resolved': 'https://evil.example/x.tgz'}, 'registry'),
                ('query', {**good, 'resolved': good['resolved'] + '?x=1'}, 'registry'),
                ('no resolved', {'version': '1', 'integrity': INTEGRITY}, 'registry'),
                ('sha1', {**good, 'integrity': 'sha1-' + 'A' * 27 + '='}, 'integrity'),
                ('link', {'link': True, 'resolved': '../x'}, 'link')):
            with self.subTest(name=name), self.assertRaisesRegex(dependencies.DependencyError, problem):
                dependencies.npm_check(PACKAGE, lock(**{'node_modules/x': entry}))
        for key in ('node_modules/../../etc', 'src/x', 'node_modules/x/../../y'):
            with self.subTest(key=key), self.assertRaisesRegex(dependencies.DependencyError, 'package path'):
                dependencies.npm_check(PACKAGE, lock(**{key: good}))

    def test_package_json_may_not_point_outside_the_registry(self):
        for field, spec in (('dependencies', 'git+https://github.com/x/y.git'), ('devDependencies', 'github:x/y'),
                            ('optionalDependencies', 'file:../x'), ('peerDependencies', 'https://evil/x.tgz'),
                            ('dependencies', 'x/y'), ('overrides', {'a': {'b': 'link:../b'}})):
            with self.subTest(field=field, spec=spec), self.assertRaisesRegex(dependencies.DependencyError, 'specifier'):
                dependencies.npm_check(json.dumps({field: {'a': spec}}).encode(), lock())
        with self.assertRaisesRegex(dependencies.DependencyError, 'workspaces'):
            dependencies.npm_check(json.dumps({'workspaces': ['x']}).encode(), lock())

    def test_size_and_format_limits(self):
        with self.assertRaisesRegex(dependencies.DependencyError, 'too large'):
            dependencies.npm_check(PACKAGE, b' ' * (dependencies.MAX_NPM_LOCK + 1))
        with self.assertRaisesRegex(dependencies.DependencyError, 'lockfileVersion'):
            dependencies.npm_check(PACKAGE, json.dumps({'lockfileVersion': 1, 'packages': {}}).encode())
        with self.assertRaisesRegex(dependencies.DependencyError, 'JSON'):
            dependencies.npm_check(b'{', lock())


class NpmFetch(unittest.TestCase):
    def test_the_fetch_container_runs_npm_ci_without_scripts_or_project_config_and_sees_only_the_two_files(self):
        argv = dependencies.npm_fetch_argv(ID, '/tmp/x/deps', 'factory-x-frontend-deps', '1001:121')
        self.assertEqual(argv[argv.index('--network') + 1], 'bridge')
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a == '--mount'], ['type=bind,src=/tmp/x/deps,dst=/deps'])
        self.assertEqual(argv[argv.index(ID):], [ID, 'npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--include=dev',
                                                 '--registry=' + dependencies.NPM_REGISTRY])
        env = [argv[i + 1] for i, a in enumerate(argv) if a == '--env']
        self.assertIn('npm_config_userconfig=/tmp/no-user-npmrc', env)
        self.assertIn('npm_config_globalconfig=/tmp/no-global-npmrc', env)
        self.assertFalse(any('TOKEN' in item or 'GITHUB' in item for item in env))
        for flags in (['--read-only'], ['--cap-drop', 'ALL'], ['--security-opt', 'no-new-privileges'], ['--user', '1001:121'],
                      ['--workdir', '/deps']):
            self.assertTrue(any(argv[i:i + len(flags)] == flags for i in range(len(argv))), flags)


def nuget_lock(packages, version=2):
    return json.dumps({'version': version, 'dependencies': {'net10.0': packages}})


class NugetPackages(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / 'backend/Tests').mkdir(parents=True)

    def write(self, path, text):
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text)

    def test_the_real_backend_lock_files_are_read(self):
        packages = dependencies.nuget_packages(ROOT)
        self.assertIn(('npgsql.entityframeworkcore.postgresql', '10.0.3'), packages)
        self.assertNotIn(('aicepeak.api', ''), packages)
        self.assertEqual(len(packages), len(set(packages)))

    def test_packages_are_deduplicated_case_insensitively_and_projects_skipped(self):
        self.write('backend/packages.lock.json', nuget_lock({'Npgsql': {'type': 'Direct', 'resolved': '10.0.3', 'contentHash': HASH}}))
        self.write('backend/Tests/packages.lock.json', nuget_lock({
            'npgsql': {'type': 'Transitive', 'resolved': '10.0.3', 'contentHash': HASH},
            'App': {'type': 'Project'}}))
        self.write('backend/obj/packages.lock.json', nuget_lock({'Ignored': {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': HASH}}))
        self.assertEqual(dependencies.nuget_packages(self.root), [('npgsql', '10.0.3')])

    def test_conflicting_or_malformed_entries_are_refused(self):
        for packages, problem in (
                ({'A': {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': HASH},
                  'a': {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': 'C' * 86 + '=='}}, 'conflicting'),
                ({'../evil': {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': HASH}}, 'name'),
                ({'A': {'type': 'Direct', 'resolved': '1.0.0/../../x', 'contentHash': HASH}}, 'version'),
                ({'A': {'type': 'Direct', 'resolved': '1.0.0', 'contentHash': 'short'}}, 'contentHash'),
                ({'A': {'type': 'Weird', 'resolved': '1.0.0', 'contentHash': HASH}}, 'type')):
            with self.subTest(problem=problem):
                self.write('backend/packages.lock.json', nuget_lock(packages))
                with self.assertRaisesRegex(dependencies.DependencyError, problem):
                    dependencies.nuget_packages(self.root)
        self.write('backend/packages.lock.json', nuget_lock({}, version=1))
        with self.assertRaisesRegex(dependencies.DependencyError, 'version'):
            dependencies.nuget_packages(self.root)

    def test_a_symlinked_lock_file_or_no_lock_file_is_refused(self):
        with self.assertRaisesRegex(dependencies.DependencyError, 'packages.lock.json'):
            dependencies.nuget_packages(self.root)
        outside = self.root / 'outside.json'
        outside.write_text(nuget_lock({}))
        (self.root / 'backend/packages.lock.json').symlink_to(outside)
        with self.assertRaisesRegex(dependencies.DependencyError, 'packages.lock.json'):
            dependencies.nuget_packages(self.root)


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, answers):
        self.answers, self.urls = answers, []

    def open(self, url, timeout):
        self.urls.append(url)
        answer = self.answers[url] if isinstance(self.answers, dict) else self.answers
        answer = answer.pop(0) if isinstance(answer, list) else answer
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'x', {}, None)


class NugetFetch(unittest.TestCase):
    def setUp(self):
        self.feed = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.feed)

    def test_packages_are_downloaded_from_the_flat_container_into_a_flat_feed(self):
        url = dependencies.NUGET_FLAT + 'npgsql/10.0.3/npgsql.10.0.3.nupkg'
        opener = FakeOpener({url: b'nupkg-bytes'})
        dependencies.fetch_nuget([('npgsql', '10.0.3')], self.feed, opener=opener)
        self.assertEqual(opener.urls, [url])
        self.assertEqual((self.feed / 'npgsql.10.0.3.nupkg').read_bytes(), b'nupkg-bytes')

    def test_missing_packages_redirects_and_size_limits_are_reported(self):
        for answer, problem in ((http_error('u', 404), 'not on nuget.org'), (http_error('u', 302), 'redirect'),
                                (b'x' * 11, 'too large')):
            with self.subTest(problem=problem), self.assertRaisesRegex(dependencies.DependencyError, problem):
                dependencies.fetch_nuget([('a', '1.0.0')], self.feed, opener=FakeOpener(answer), max_bytes=10, sleep=lambda s: None)

    def test_server_errors_are_retried_and_then_named_as_an_outage(self):
        opener = FakeOpener([http_error('u', 503), urllib.error.URLError('reset'), b'ok'])
        dependencies.fetch_nuget([('a', '1.0.0')], self.feed, opener=opener, sleep=lambda s: None)
        self.assertEqual(len(opener.urls), 3)
        opener = FakeOpener(http_error('u', 503))
        with self.assertRaisesRegex(dependencies.DependencyError, 'nuget.org unavailable'):
            dependencies.fetch_nuget([('a', '1.0.0')], self.feed, opener=opener, sleep=lambda s: None)

    def test_the_offline_config_has_only_the_local_feed_and_no_audit_source(self):
        path = dependencies.write_nuget_config(self.feed)
        text = path.read_text()
        self.assertIn('<clear />', text)
        self.assertIn('value="/feeds/nuget"', text)
        self.assertNotIn('nuget.org', text)
        self.assertIn('<auditSources>', text)

    def test_redirects_are_refused_by_the_real_opener(self):
        handler = [h for h in dependencies.opener().handlers if isinstance(h, dependencies.NoRedirect)]
        self.assertEqual(len(handler), 1)


if __name__ == '__main__':
    unittest.main()
