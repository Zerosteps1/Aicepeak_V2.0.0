import base64
import hashlib
import unittest

from factory_testlib import SessionRepos, git
import contracts
import engine
import github_api
import session
from contracts import Blocked

PNG = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'


def placeholder(raw):
    return (f'[binary or non-UTF-8 file, content not reviewed: {len(raw)} bytes, SHA-256 '
            f'{hashlib.sha256(raw).hexdigest()}; judge whether a file of this kind belongs at this path]')


class Placeholder(unittest.TestCase):
    def test_only_text_passes_and_only_a_changed_file_becomes_a_placeholder(self):
        self.assertEqual(contracts.utf8('Grüße\n'.encode(), 'x'), 'Grüße\n')
        for raw in (PNG, b'\xff\xfe latin'):
            with self.subTest(raw=raw), self.assertRaisesRegex(contracts.NotText, '^not text$') as raised:
                contracts.utf8(raw, 'not text')
            self.assertEqual(raised.exception.placeholder, placeholder(raw))
            self.assertEqual(contracts.changed_text(lambda: contracts.utf8(raw, 'not text')), placeholder(raw))
        # Any other refusal (a missing file, a symlink, an oversized source) still blocks the review.
        with self.assertRaisesRegex(Blocked, 'unsupported source'):
            contracts.changed_text(lambda: contracts.require(False, 'unsupported source'))


class SeniorReview(unittest.TestCase):
    def test_a_binary_changed_file_is_named_not_read_and_the_northstar_stays_text_only(self):
        files = {'frontend/mark.png': PNG, 'README.md': b'# Readme\n', 'NORTHSTAR.md': b'North star\n'}

        class Source(github_api.GitHub):
            def __init__(self):
                pass

            def request(self, method, path, data=None):
                name = path.split('/contents/', 1)[1].split('?', 1)[0]
                return {'type': 'file', 'encoding': 'base64', 'content': base64.b64encode(files[name]).decode()}

            def pages(self, path, field=None):
                if path.endswith('/files'):
                    return [{'filename': 'frontend/mark.png', 'status': 'added'},
                            {'filename': 'README.md', 'status': 'modified'}]
                return []

        snapshot = {'repository': 'fixture/repo', 'pr': 1, 'head_sha': 'a' * 40, 'base_sha': 'b' * 40,
                    'policy_sha': 'b' * 40, 'base_ref': 'production', 'files': ['frontend/mark.png', 'README.md']}
        config = {'northstar_path': 'NORTHSTAR.md', 'maintainers': [], 'publisher_app_id': 7,
                  'limits': {'review_input_bytes': 800000}}
        material = engine.review_material(Source(), snapshot, config, {})
        self.assertIn('UNTRUSTED HEAD FILE frontend/mark.png\n' + placeholder(PNG), material)
        self.assertNotIn('UNTRUSTED BASE FILE frontend/mark.png', material)
        self.assertIn('UNTRUSTED HEAD FILE README.md\n# Readme\n', material)
        self.assertIn(contracts.NOT_TEXT_RULE, engine.review_prompt())
        files['NORTHSTAR.md'] = b'\xff\xfe north star'
        with self.assertRaisesRegex(Blocked, '^binary or non-UTF-8 source cannot be completely reviewed: NORTHSTAR.md$'):
            engine.review_material(Source(), snapshot, config, {})


class Preflight(SessionRepos, unittest.TestCase):
    def commit(self, name, raw):
        (self.candidate / name).write_bytes(raw)
        git(self.candidate, 'add', name)
        git(self.candidate, 'commit', '-qm', name)
        return git(self.candidate, 'rev-parse', 'HEAD')

    def test_a_binary_changed_file_is_named_and_cited_context_stays_text_only(self):
        base = self.commit('tools/factory/old.bin', b'\x00\x01')
        self.commit('tools/factory/mark.png', PNG)
        state = lambda context: session.candidate_state(self.candidate, self.config, self.base, 'docs/work/TEST.md',
                                                        context, 'testing', base, self.gh)
        _, names, sources = state([])
        self.assertEqual(names, ['tools/factory/mark.png'])
        self.assertEqual({source['id']: source['text'] for source in sources if source['path'] == names[0]},
                         {'head:tools/factory/mark.png': placeholder(PNG)})
        with self.assertRaisesRegex(Blocked, '^binary or non-UTF-8 source cannot be reviewed: tools/factory/old.bin$'):
            state(['tools/factory/old.bin'])


if __name__ == '__main__':
    unittest.main()
