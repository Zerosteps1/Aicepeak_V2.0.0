"""factory/install_tools.py: the pinned check tools, SHA-256 verified, for the factory image and maintainers' Macs."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from factory_testlib import ROOT, Response, use
use('factory')
import install_tools  # noqa: E402

PLATFORMS = ('linux_amd64', 'linux_arm64', 'darwin_amd64', 'darwin_arm64')


def archive(*members):
    """A release tarball: (name, bytes) regular files, or (name, None) as a symlink."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            if data is None:
                info.type, info.linkname = tarfile.SYMTYPE, '/etc/passwd'
                tar.addfile(info)
            else:
                info.size, info.mode = len(data), 0o755
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def locked(data, key='darwin_arm64'):
    return {'actionlint': {'version': '1.7.12', 'repository': 'rhysd/actionlint',
                           key: {'asset': f'actionlint_1.7.12_{key}.tar.gz', 'sha256': hashlib.sha256(data).hexdigest()}},
            'gitleaks': {'version': '8.30.1', 'repository': 'gitleaks/gitleaks',
                         key: {'asset': f'gitleaks_8.30.1_{key}.tar.gz', 'sha256': '0' * 64}}}


class InstallTools(unittest.TestCase):
    def test_the_lock_pins_every_check_tool_for_linux_and_macos(self):
        lock = json.loads((ROOT / 'factory/tools.lock.json').read_text())
        self.assertEqual(sorted(lock), ['actionlint', 'gitleaks'])
        for name, item in lock.items():
            for key in PLATFORMS:
                with self.subTest(tool=name, platform=key):
                    asset = item[key]
                    self.assertRegex(asset['sha256'], '^[0-9a-f]{64}$')
                    self.assertTrue(asset['asset'].startswith(f"{name}_{item['version']}_{key.split('_')[0]}_"))
                    self.assertTrue(asset['asset'].endswith('.tar.gz'))
            self.assertEqual(len({item[key]['sha256'] for key in PLATFORMS}), len(PLATFORMS))

    def test_platform_keys(self):
        for system, machine, key in (('darwin', 'arm64', 'darwin_arm64'), ('darwin', 'x86_64', 'darwin_amd64'),
                                     ('linux', 'aarch64', 'linux_arm64'), ('linux', 'x86_64', 'linux_amd64')):
            self.assertEqual(install_tools.platform_key(system, machine), key)
        for system, machine in (('win32', 'AMD64'), ('darwin', 'ppc'), ('freebsd13', 'amd64')):
            with self.assertRaisesRegex(ValueError, 'no pinned tools for'):
                install_tools.platform_key(system, machine)

    def test_installs_only_a_verified_binary_and_replaces_a_symlink_instead_of_writing_through(self):
        content = b'#!/bin/sh\necho pinned\n'
        data = archive(('README.md', b'readme'), ('actionlint', content))
        lock, urls = locked(data), []

        def fetch(url):
            urls.append(url)
            return Response(data)
        with tempfile.TemporaryDirectory() as temp:
            destination, elsewhere = Path(temp) / 'bin', Path(temp) / 'brew-actionlint'
            destination.mkdir()
            elsewhere.write_bytes(b'another installation')
            (destination / 'actionlint').symlink_to(elsewhere)
            self.assertEqual(install_tools.install(lock, destination, 'darwin_arm64', ['actionlint'], fetch),
                             [destination / 'actionlint'])
            self.assertEqual(urls, ['https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_darwin_arm64.tar.gz'])
            self.assertFalse((destination / 'actionlint').is_symlink())
            self.assertEqual((destination / 'actionlint').read_bytes(), content)
            self.assertEqual((destination / 'actionlint').stat().st_mode & 0o777, 0o755)
            self.assertEqual(elsewhere.read_bytes(), b'another installation')
            self.assertEqual(sorted(p.name for p in destination.iterdir()), ['actionlint'])  # no README, no leftovers
            for only, key, problem in ((['gitleaks'], 'darwin_arm64', 'tool digest mismatch: gitleaks'),
                                       (['gh'], 'darwin_arm64', 'not in the lock: gh'),
                                       (['actionlint'], 'linux_amd64', 'no pinned actionlint for linux_amd64')):
                with self.subTest(only=only, key=key), self.assertRaisesRegex(ValueError, problem):
                    install_tools.install(lock, destination, key, only, fetch)
            self.assertFalse((destination / 'gitleaks').exists())
            unsafe = archive(('actionlint', None))
            with self.assertRaisesRegex(ValueError, 'unsafe tool member'):
                install_tools.install(locked(unsafe), destination, 'darwin_arm64', ['actionlint'], lambda url: Response(unsafe))
            self.assertEqual((destination / 'actionlint').read_bytes(), content)  # a refused archive changes nothing
            oversized = b'x' * 30_000_001
            with self.assertRaisesRegex(ValueError, 'tool digest mismatch: actionlint'):
                install_tools.install(locked(oversized), destination, 'darwin_arm64', ['actionlint'], lambda url: Response(oversized))

    def test_main_reports_a_problem_without_a_traceback(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stderr(io.StringIO()) as stderr:
            code = install_tools.main(['--lock', str(Path(temp) / 'missing.json'), '--destination', temp])
        self.assertEqual(code, 1)
        self.assertTrue(stderr.getvalue().startswith('BLOCKED: '))
        self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
