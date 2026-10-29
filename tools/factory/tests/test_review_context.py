import json
import copy
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
from contracts import Blocked
from review_context import context_sections


class Context(unittest.TestCase):
    def supplemental_source(self):
        class Source:
            def __init__(self):
                self.reads = []
                self.mode = '100644'
                self.app = 7
            def request(self, method, path):
                if '/git/trees/' in path:
                    return {'truncated': False, 'tree': [
                        {'path': 'tools/session.py', 'type': 'blob', 'mode': self.mode}]}
                if '/check-runs/' in path:
                    return {'id': 12, 'name': 'factory/senior-review', 'app': {'id': self.app},
                            'head_sha': 'c'*40, 'external_id': 'fixture/repo:20:'+ 'c'*40 + ':'+'d'*40+':34:1',
                            'status': 'completed', 'conclusion': 'failure',
                            'output': {'summary': 'Missing evidence; no approval.', 'text': '{"outcome":"blocked"}'}}
                if path.endswith('/actions/runs/34'):
                    return {'id': 34, 'repository': {'full_name': 'fixture/repo'},
                            'head_sha': 'd'*40, 'path': '.github/workflows/factory.yml',
                            'status': 'completed', 'conclusion': 'failure', 'run_attempt': 1}
                raise AssertionError(path)
            def pages(self, path, field=None):
                return [{'id': 56, 'name': 'Author correction', 'status': 'completed', 'conclusion': 'failure'}]
            def text(self, repo, path, sha):
                self.reads.append((path, sha))
                return 'raise RuntimeError("source must never execute")\n'
        return Source()

    def supplemental_config(self):
        return {'publisher_app_id': 7, 'workflow': '.github/workflows/factory.yml',
                'review_context_rules': [{'changed_paths': ['README.md', 'docs/guide/'],
                                          'paths': ['tools/session.py'], 'checks': [12], 'runs': [34]}]}

    def supplemental_snapshot(self, files=None):
        return {'repository': 'fixture/repo', 'head_sha': 'a'*40, 'policy_sha': 'b'*40,
                'files': files or ['README.md']}

    def test_documentation_gets_selected_head_source_and_historical_failure_evidence(self):
        source = self.supplemental_source()
        text = '\n'.join(context_sections(source, self.supplemental_snapshot(), self.supplemental_config()))
        self.assertIn(('tools/session.py', 'a'*40), source.reads)
        self.assertIn('source must never execute', text)
        self.assertIn('Missing evidence; no approval.', text)
        self.assertIn('Author correction', text)
        self.assertIn('failure', text)
        self.assertIn('not approval of this PR', text)

    def test_supplement_does_not_expand_unrelated_or_similarly_named_paths(self):
        source = self.supplemental_source()
        for path in ['unrelated.md', 'docs/guidelines/a.md']:
            self.assertEqual(context_sections(source, self.supplemental_snapshot([path]), self.supplemental_config()), [])
        self.assertEqual(source.reads, [])
        self.assertTrue(context_sections(source, self.supplemental_snapshot(['docs/guide/a.md']), self.supplemental_config()))

    def test_supplement_missing_file_symlink_and_foreign_publisher_block(self):
        for mode, app in [('120000', 7), ('100644', 999)]:
            source = self.supplemental_source(); source.mode = mode; source.app = app
            with self.subTest(mode=mode, app=app), self.assertRaises(Blocked):
                context_sections(source, self.supplemental_snapshot(), self.supplemental_config())
        config = self.supplemental_config(); config['review_context_rules'][0]['paths'] = ['missing.py']
        with self.assertRaises(Blocked):
            context_sections(self.supplemental_source(), self.supplemental_snapshot(), config)

    def test_invalid_or_oversized_context_configuration_blocks_before_reads(self):
        cases = [('paths', ['../secret']), ('paths', ['/etc/passwd']), ('paths', ['https://evil.test/a']),
                 ('checks', [True]), ('checks', ['12']), ('runs', [-1]),
                 ('paths', [f'file{i}.md' for i in range(31)]), ('changed_paths', [])]
        for field, value in cases:
            config = self.supplemental_config(); config['review_context_rules'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(Blocked):
                context_sections(self.supplemental_source(), self.supplemental_snapshot(), config)

    def test_multiple_matching_rules_share_the_total_file_limit(self):
        config = self.supplemental_config()
        rule = config['review_context_rules'][0]
        rule['paths'] = [f'a{i}.md' for i in range(20)]
        second = copy.deepcopy(rule); second['paths'] = [f'b{i}.md' for i in range(20)]
        config['review_context_rules'].append(second)
        with self.assertRaisesRegex(Blocked, 'combined review context limit'):
            context_sections(self.supplemental_source(), self.supplemental_snapshot(), config)

    def test_incomplete_tree_foreign_run_and_wrong_head_binding_block(self):
        for kind in ('tree', 'run', 'head'):
            source = self.supplemental_source(); request = source.request
            def altered(method, path):
                value = request(method, path)
                if kind == 'tree' and '/git/trees/' in path: value['truncated'] = True
                if kind == 'run' and path.endswith('/actions/runs/34'): value['repository']['full_name'] = 'other/repo'
                if kind == 'head' and '/check-runs/' in path: value['head_sha'] = 'f'*40
                return value
            source.request = altered
            with self.subTest(kind=kind), self.assertRaises(Blocked):
                context_sections(source, self.supplemental_snapshot(), self.supplemental_config())

    def test_changed_selected_source_is_not_duplicated(self):
        config = self.supplemental_config(); config['review_context_rules'][0]['paths'] = ['README.md']
        source = self.supplemental_source()
        context_sections(source, self.supplemental_snapshot(), config)
        self.assertEqual(source.reads, [])

    def test_operating_document_rule_supplies_documented_tool_implementations(self):
        config = json.loads((ROOT/'factory/config.json').read_text())
        rules = [r for r in config['review_context_rules'] if 'README.md' in r['changed_paths']]
        selected = {p for r in rules for p in r['paths']}
        self.assertTrue({'tools/factory/doctor.py', 'tools/factory/local_review.py',
                         'tools/factory/session.py', 'tools/factory/clients.py', 'tools/factory/verify.py'} <= selected)

    def test_supplemental_sources_count_against_existing_complete_material_limit(self):
        import engine
        source = self.supplemental_source()
        source.pages = lambda path, field=None: ([{'filename': 'README.md', 'status': 'modified'}]
                                                 if path.endswith('/files') else [])
        snapshot = {**self.supplemental_snapshot(), 'pr': 1, 'base_sha': 'b'*40,
                    'handoff': {'task': 'docs/work/TEST.md'}}
        config = {**self.supplemental_config(), 'northstar_path': None, 'maintainers': [],
                  'limits': {'review_input_bytes': 800000}}
        config['review_context_rules'][0].update(checks=[], runs=[])
        without = {**config, 'review_context_rules': []}
        baseline = engine.review_material(source, snapshot, without, {})
        config['limits']['review_input_bytes'] = len(baseline.encode()) + 18000 + 1
        with self.assertRaisesRegex(Blocked, 'review input budget exceeded'):
            engine.review_material(source, snapshot, config, {})

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

    def test_parent_directory_import_is_included_without_executing_path_setup(self):
        sources = {
            'tools/factory/tests/test_protocol.py':
                'import sys\nfrom pathlib import Path\n'
                'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n'
                'from contracts import validate_review\nraise RuntimeError("must not execute")\n',
            'tools/factory/contracts.py': 'def validate_review(): return "local contract evidence"\n',
        }
        class Source:
            def request(self, method, path):
                return {'truncated': False, 'tree': [{'path': p, 'type': 'blob', 'mode': '100644'} for p in sources]}
            def text(self, repo, path, sha):
                self_outer.assertEqual(sha, 'a' * 40)
                return sources[path]
        self_outer = self
        sections = context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,
                                              'files':['tools/factory/tests/test_protocol.py']}, {})
        text = '\n'.join(sections)
        self.assertIn('UNTRUSTED UNCHANGED DEPENDENCY tools/factory/contracts.py', text)
        self.assertIn('local contract evidence', text)

    def test_ambiguous_ancestor_imports_remain_visible_as_evidence(self):
        sources = {'tools/factory/tests/test_protocol.py': 'from rules import verdict\n',
                   'tools/factory/rules.py': 'verdict = "nearest"\n',
                   'tools/rules.py': 'verdict = "outer"\n'}
        class Source:
            def request(self, method, path):
                return {'truncated': False, 'tree': [{'path': p, 'type': 'blob', 'mode': '100644'} for p in sources]}
            def text(self, repo, path, sha):
                return sources[path]
        sections = context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,
                                              'files':['tools/factory/tests/test_protocol.py']}, {})
        text = '\n'.join(sections)
        self.assertIn('verdict = "nearest"', text)
        self.assertIn('verdict = "outer"', text)

    def test_non_python_change_does_not_fetch_a_language_tree(self):
        class Source:
            def request(self,*args): raise AssertionError('unnecessary tree fetch')
        self.assertEqual(context_sections(Source(), {'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'files':['note.md']}, {}), [])
