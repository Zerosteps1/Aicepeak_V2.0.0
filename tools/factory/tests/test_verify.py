"""verify.py's file walk skips installed dependencies (node_modules) on a maintainer's machine; with --ci it checks everything."""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_testlib import ROOT
import verify

# A token-shaped fake value that gitleaks' default rules report, built at runtime so this file holds no such literal.
SECRET = 'const token = "' + 'ghp' + '_' + hashlib.sha256(b'fake').hexdigest()[:36] + '";\n'


def dependencies(root):
    """node_modules content that fails every check: invalid JSON, a broken link and a symlink."""
    package = root / 'frontend/node_modules/pkg'
    package.mkdir(parents=True)
    (package / 'package.json').write_text('{"name": "pkg", // comment\n}')
    (package / 'README.md').write_text('[docs](missing.md)\n')
    (root / 'frontend/node_modules/.bin').mkdir()
    (root / 'frontend/node_modules/.bin/tool').symlink_to('../pkg/package.json')
    return package


class HostSkip(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)

    def test_host_runs_skip_node_modules_and_ci_runs_check_it(self):
        dependencies(self.root)
        # Past the walk, structural() reads factory/config.json, which this tree lacks.
        with self.assertRaises(FileNotFoundError):
            verify.structural(self.root, ROOT, skip=verify.HOST_SKIP)
        with self.assertRaisesRegex(ValueError, 'symlink in candidate'):
            verify.structural(self.root, ROOT)
        (self.root / 'frontend/node_modules/.bin/tool').unlink()
        with self.assertRaises(ValueError):
            verify.structural(self.root, ROOT)

    def test_only_folders_named_node_modules_are_skipped(self):
        self.assertEqual(verify.HOST_SKIP, ('node_modules',))
        (self.root / 'frontend/node_modules_extra').mkdir(parents=True)
        (self.root / 'frontend/node_modules_extra/bad.json').write_text('{')
        with self.assertRaises(ValueError):
            verify.structural(self.root, ROOT, skip=verify.HOST_SKIP)

    def test_a_root_inside_a_node_modules_folder_is_still_checked(self):
        root = self.root / 'node_modules/checkout'
        root.mkdir(parents=True)
        (root / 'bad.json').write_text('{')
        with self.assertRaises(ValueError):
            verify.structural(root, ROOT, skip=verify.HOST_SKIP)


@unittest.skipUnless(shutil.which('gitleaks'), 'gitleaks is not on PATH (it is in the test image)')
class HostGitleaks(unittest.TestCase):
    def scan(self, root):
        return subprocess.run(['gitleaks', 'dir', '--no-banner', '--redact', '--config', str(ROOT / 'factory/gitleaks.toml'), str(root)],
                              capture_output=True, text=True, timeout=120).returncode

    def test_the_trusted_rules_ignore_node_modules_in_every_run_and_find_secrets_elsewhere(self):
        # Upstream default allowlist (gitleaks config/gitleaks.toml): the walk's host-only skip needs no gitleaks change.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'frontend/node_modules/pkg').mkdir(parents=True)
            (root / 'frontend/node_modules/pkg/config.js').write_text(SECRET)
            self.assertEqual(self.scan(root), 0)
            (root / 'frontend/src').mkdir()
            (root / 'frontend/src/config.js').write_text(SECRET)
            self.assertEqual(self.scan(root), 1)


if __name__ == '__main__':
    unittest.main()
