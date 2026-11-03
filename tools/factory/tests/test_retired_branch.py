"""AC-14: branch names come from the config branch, so trusted code never names the retired default branch."""
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
import branches

RETIRED = 'main'
WORD = re.compile(rf'\b{RETIRED}\b')
CALL = re.compile(rf'\b{RETIRED}\(')  # `def main(` and `main(` calls; `__main__` has no word boundary
DEFINITION = re.compile(r"RESERVED = \((?:'[a-z]+', )*'[a-z]+'\)")


def sources(root):
    """Trusted factory code (tests excluded), the CLI installer, the workflows and the dispatcher."""
    factory = root / 'tools/factory'
    found = [p for p in factory.rglob('*.py') if 'tests' not in p.relative_to(factory).parts]
    found += [*(factory / 'cli').glob('*.sh'), *(root / '.github/workflows').glob('*.yml'),
              *(root / '.github/scripts').glob('*.py')]
    return sorted(found)


def offending(name, text):
    """(line number, line) of every use of the retired name as a word, apart from the entry-point idiom and the
    definition of branches.RESERVED."""
    return [(number, line) for number, line in enumerate(text.splitlines(), 1)
            if WORD.search(CALL.sub('', line))
            and not (name == 'tools/factory/branches.py' and DEFINITION.fullmatch(line))]


class RetiredBranchName(unittest.TestCase):
    def test_trusted_code_workflows_and_installer_never_name_the_retired_default_branch(self):
        files = {p.relative_to(ROOT).as_posix(): p for p in sources(ROOT)}
        for expected in ('tools/factory/session.py', 'tools/factory/merge_safety.py', 'tools/factory/promotion.py',
                         'tools/factory/bypass.py', 'tools/factory/settings.py', 'tools/factory/cli/branching.py',
                         'tools/factory/cli/install-factory-cli.sh', '.github/workflows/factory.yml',
                         '.github/workflows/factory-promotion.yml', '.github/scripts/dispatch_factory.py'):
            self.assertIn(expected, files)
        self.assertFalse([name for name in files if '/tests/' in name])
        found = [f'{name}:{number}: {line.strip()}' for name, path in files.items()
                 for number, line in offending(name, path.read_text())]
        self.assertEqual(found, [])
        # The retired name stays reserved, and its one allowed literal is that definition.
        self.assertIn(RETIRED, branches.RESERVED)
        self.assertEqual(sum(bool(DEFINITION.fullmatch(line))
                             for line in files['tools/factory/branches.py'].read_text().splitlines()), 1)

    def test_the_scan_flags_every_use_but_the_entry_point_idiom_and_the_reserved_list(self):
        flagged = ['--ref main', "    branches: [main]", "ref = 'refs/heads/main'", '"main"', 'git push origin main',
                   'the main branch', 'main (the old default)', "DEFAULT = 'main'; main()"]
        allowed = ['def main(argv=None):', '    sys.exit(main())', "if __name__ == '__main__':", 'session.main([])',
                   'maintainers domain mainly', 'remain']
        for line in flagged:
            with self.subTest(flagged=line):
                self.assertEqual(offending('tools/factory/session.py', line), [(1, line)])
        for line in allowed:
            with self.subTest(allowed=line):
                self.assertEqual(offending('tools/factory/session.py', line), [])
        reserved = "RESERVED = ('main', 'master', 'head')"
        self.assertEqual(offending('tools/factory/branches.py', reserved), [])
        self.assertEqual(offending('tools/factory/session.py', reserved), [(1, reserved)])
        self.assertEqual(offending('tools/factory/branches.py', reserved + "  # default: 'main'"), [(1, reserved + "  # default: 'main'")])


if __name__ == '__main__':
    unittest.main()
