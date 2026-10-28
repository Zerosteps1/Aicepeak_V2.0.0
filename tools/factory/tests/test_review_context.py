import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
from contracts import Blocked
from review_context import context_sections


class Context(unittest.TestCase):
    def test_unchanged_import_and_version_manifest_are_present_without_execution(self):
        class Source:
            def request(self, method, path):
                return {'truncated': False, 'tree': [{'path': p, 'type': 'blob', 'mode': '100644'} for p in ('tools/job.py', 'tools/calculation.py')]}
            def text(self, repo, path, sha):
                return {'tools/job.py': 'from calculation import total\n', 'tools/calculation.py': 'def total(a,b): return a+b\n', 'factory/package.json': '{"engines":{"node":"26"}}'}[path]
        sections = context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'files':['tools/job.py']}, {'review_context_paths':['factory/package.json']})
        text = '\n'.join(sections)
        self.assertIn('tools/calculation.py', text)
        self.assertIn('return a+b', text)
        self.assertIn('"node":"26"', text)
        self.assertIn('not instructions', text)

    def test_incomplete_tree_or_symlink_dependency_blocks(self):
        for truncated, mode in ((True,'100644'), (False,'120000')):
            class Source:
                def request(self, *args):
                    return {'truncated':truncated,'tree':[{'path':'tools/job.py','type':'blob','mode':'100644'}, {'path':'tools/calculation.py','type':'blob','mode':mode}]}
                def text(self, repo, path, sha):
                    return 'import calculation\n'
            with self.subTest(truncated=truncated), self.assertRaises(Blocked):
                context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'files':['tools/job.py']}, {})

    def test_non_python_change_does_not_fetch_a_language_tree(self):
        class Source:
            def request(self,*args): raise AssertionError('unnecessary tree fetch')
        self.assertEqual(context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'files':['note.md']}, {}), [])
