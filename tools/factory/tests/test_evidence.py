"""Product check results: parsing real tool output, bounded evidence, job summary, check summary and annotations."""
import ast
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from factory_testlib import ROOT
import evidence

FIXTURES = ROOT / 'tools/factory/tests/fixtures/product'
IMAGE_LINE = 'test image aicepeak-factory-test:0123456789abcdef: present'
RUN = 'https://github.com/fixture/repo/actions/runs/1'


def candidate():
    """A candidate tree with the files the fixtures point at."""
    root = Path(tempfile.mkdtemp())
    for path in ('backend/Broken.cs', 'backend/Aicepeak.Api.Tests/FixtureTests.cs', 'frontend/src/fixture.test.ts',
                 'frontend/src/broken.ts'):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text('x\n')
    return root


class Parsers(unittest.TestCase):
    def setUp(self):
        self.root = candidate()
        self.addCleanup(shutil.rmtree, self.root)

    def test_trx_cases_counts_and_failure_location(self):
        result = evidence.parse_trx((FIXTURES / 'backend.trx').read_bytes(), self.root)
        self.assertEqual(result['counts'], {'total': 3, 'passed': 1, 'failed': 1, 'skipped': 1})
        cases = {case['name']: case for case in result['cases']}
        failed = cases['Aicepeak.Api.Tests.FixtureTests.Fails_WithMessage']
        self.assertEqual(failed['status'], 'failed')
        self.assertTrue(failed['message'].startswith('Assert.Equal() Failure: Values differ'))
        self.assertEqual((failed['path'], failed['line']), ('backend/Aicepeak.Api.Tests/FixtureTests.cs', 11))
        self.assertIn('at Aicepeak.Api.Tests.FixtureTests.Fails_WithMessage()', failed['details'])
        self.assertEqual(cases['Aicepeak.Api.Tests.FixtureTests.Skipped']['status'], 'skipped')
        self.assertEqual(cases['Aicepeak.Api.Tests.FixtureTests.Passes']['status'], 'passed')
        self.assertIsInstance(cases['Aicepeak.Api.Tests.FixtureTests.Passes']['seconds'], float)

    def test_junit_cases_counts_and_failure_location(self):
        result = evidence.parse_junit((FIXTURES / 'vitest-junit.xml').read_bytes(), self.root, 'frontend')
        self.assertEqual(result['counts'], {'total': 14, 'passed': 12, 'failed': 1, 'skipped': 1})
        failed = [case for case in result['cases'] if case['status'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['name'], 'src/fixture.test.ts > fixture > fails with a message')
        self.assertEqual(failed[0]['message'], 'expected 1 to be 2 // Object.is equality')
        self.assertEqual((failed[0]['path'], failed[0]['line']), ('frontend/src/fixture.test.ts', 9))

    def test_msbuild_and_tsc_errors_are_deduplicated_and_mapped_to_repository_paths(self):
        errors = evidence.parse_errors((FIXTURES / 'msbuild.log').read_text(), self.root, 'backend')
        self.assertEqual(errors, [
            {'path': 'backend/Broken.cs', 'line': 4, 'message': "CS0029: Cannot implicitly convert type 'string' to 'int'"},
            {'path': 'backend/Broken.cs', 'line': 2,
             'message': 'IDE0055: Fix formatting (https://learn.microsoft.com/dotnet/fundamentals/code-analysis/style-rules/ide0055)'}])
        errors = evidence.parse_errors((FIXTURES / 'tsc.log').read_text(), self.root, 'frontend')
        self.assertEqual([(e['path'], e['line']) for e in errors], [('frontend/src/broken.ts', 1), ('frontend/src/broken.ts', 2)])
        self.assertTrue(errors[0]['message'].startswith('TS2322: '))

    def test_oxlint_problems_are_errors_with_their_rule(self):
        errors = evidence.parse_errors((FIXTURES / 'oxlint.log').read_text(), self.root, 'frontend')
        self.assertEqual([(e['path'], e['line']) for e in errors], [('frontend/src/broken.ts', 2), ('frontend/src/fixture.test.ts', 12)])
        self.assertTrue(errors[1]['message'].endswith('[Warning/vitest(no-disabled-tests)]'))

    def test_file_less_errors_keep_their_message_without_a_location(self):
        errors = evidence.parse_errors(
            "/work/backend/Aicepeak.Api.csproj : error NU1101: Unable to find package DotNetEnv. [/work/backend/Aicepeak.slnx]\n",
            self.root, 'backend')
        self.assertEqual(errors, [{'path': None, 'line': None, 'message': 'NU1101: Unable to find package DotNetEnv.'}])

    def test_paths_outside_the_candidate_never_become_annotation_paths(self):
        (self.root / 'backend/link.cs').symlink_to(self.root / 'backend/Broken.cs')
        (self.root / 'frontend/linked').symlink_to(self.root / 'frontend/src', target_is_directory=True)
        for raw, base in (('/work/../etc/passwd', ''), ('/etc/passwd', ''), ('../../etc/passwd', 'frontend'), ('/work/.git/config', ''),
                          ('/work/backend/missing.cs', ''), ('/work/backend/link.cs', ''), ('linked/broken.ts', 'frontend'),
                          ('/work/backend\\Broken.cs', ''), ('/work/backend/Broken.cs\x07', '')):
            with self.subTest(raw=raw):
                self.assertIsNone(evidence.repo_path(self.root, raw, base))
        self.assertEqual(evidence.repo_path(self.root, '/work/backend/Broken.cs'), 'backend/Broken.cs')
        self.assertEqual(evidence.repo_path(self.root, 'src/broken.ts', 'frontend'), 'frontend/src/broken.ts')

    def test_hostile_xml_is_refused(self):
        for data in (b'<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>', b'<x><y></x>', b'<x>' + b' ' * (evidence.MAX_XML + 1) + b'</x>',
                     b'\xff\xfe<x/>'):
            with self.subTest(data=data[:20]):
                with self.assertRaises(evidence.EvidenceError):
                    evidence.parse_junit(data, self.root, 'frontend')


def steps(root):
    trx = evidence.parse_trx((FIXTURES / 'backend.trx').read_bytes(), root)
    junit = evidence.parse_junit((FIXTURES / 'vitest-junit.xml').read_bytes(), root, 'frontend')
    return [
        evidence.step('factory', 'passed', 41.2, 0, tail='\n'.join(f'PASS: check {n}' for n in range(4))),
        evidence.step('backend-deps', 'passed', 12.0, 0),
        evidence.step('backend-build', 'failed', 18.5, 1, tail=(FIXTURES / 'msbuild.log').read_text(),
                      errors=evidence.parse_errors((FIXTURES / 'msbuild.log').read_text(), root, 'backend')),
        evidence.step('backend-test', 'failed', 9.0, 1, tail='x' * 100000, cases=trx['cases'],
                      note=evidence.DATABASE_NOTE),
        evidence.step('frontend-deps', 'not present'),
        evidence.step('frontend-test', 'failed', 3.0, 1, cases=junit['cases']),
        evidence.step('frontend-build', 'timeout', 300.0, None, tail='still compiling'),
    ]


class Records(unittest.TestCase):
    def setUp(self):
        self.root = candidate()
        self.addCleanup(shutil.rmtree, self.root)
        self.steps = steps(self.root)
        self.record = evidence.record(self.steps)

    def test_a_record_is_ok_only_when_every_step_passed_or_is_not_present(self):
        self.assertFalse(self.record['ok'])
        self.assertTrue(evidence.record([evidence.step('factory', 'passed', 1.0, 0), evidence.step('backend-deps', 'not present')])['ok'])
        for status in ('failed', 'timeout', 'skipped'):
            self.assertFalse(evidence.record([evidence.step('factory', status, 1.0, 1)])['ok'], status)

    def test_a_step_status_never_comes_from_parsed_files(self):
        with self.assertRaises(ValueError):
            evidence.step('backend-test', 'unknown')
        passed = evidence.step('backend-test', 'passed', 1.0, 0, cases=[{'name': 'x', 'status': 'failed'}])
        self.assertEqual(passed['status'], 'failed')  # a failed case turns a green exit red, never the other way round

    def test_the_record_is_bounded_and_keeps_failures_errors_and_the_factory_pass_lines(self):
        size = len(json.dumps(self.record).encode())
        self.assertLess(size, evidence.MAX_RECORD)
        by_name = {step['name']: step for step in self.record['steps']}
        self.assertEqual(by_name['factory']['pass_lines'], [f'PASS: check {n}' for n in range(4)])
        self.assertEqual(by_name['factory']['tail'], '')
        self.assertEqual(by_name['backend-test']['counts'], {'total': 3, 'passed': 1, 'failed': 1, 'skipped': 1})
        self.assertEqual([f['name'] for f in by_name['backend-test']['failures']], ['Aicepeak.Api.Tests.FixtureTests.Fails_WithMessage'])
        self.assertLessEqual(len(by_name['backend-test']['tail']), evidence.MAX_TAIL)
        self.assertEqual(len(by_name['backend-build']['errors']), 2)
        self.assertTrue(evidence.valid(self.record))

    def test_many_failures_are_cut_with_a_count(self):
        cases = [{'name': f'T{n}', 'status': 'failed', 'message': 'm' * 5000} for n in range(300)]
        record = evidence.record([evidence.step('backend-test', 'failed', 1.0, 1, cases=cases)])
        [step] = record['steps']
        self.assertLessEqual(len(step['failures']), evidence.MAX_ITEMS)
        self.assertEqual(step['omitted'], 300 - len(step['failures']))
        self.assertTrue(all(len(f['message']) <= evidence.MAX_MESSAGE for f in step['failures']))
        self.assertLess(len(json.dumps(record).encode()), evidence.MAX_RECORD)

    def test_invalid_records_are_refused(self):
        self.assertTrue(evidence.valid({'ok': True, 'summary': 'old evidence without steps'}))
        for broken in ({'steps': 'x'}, {'steps': [{'name': 'evil', 'status': 'passed'}]},
                       {'steps': [{'name': 'factory', 'status': 'green'}]},
                       {'steps': [{'name': 'factory', 'status': 'failed', 'failures': [{'name': 'x', 'path': '../x', 'line': 1, 'message': ''}]}]},
                       {'steps': [{'name': 'factory', 'status': 'failed', 'errors': [{'path': 'a.cs', 'line': -1, 'message': ''}]}]}):
            with self.subTest(broken=broken):
                self.assertFalse(evidence.valid(broken))


class Rendering(unittest.TestCase):
    def setUp(self):
        self.root = candidate()
        self.addCleanup(shutil.rmtree, self.root)
        self.steps = steps(self.root)
        self.record = evidence.record(self.steps)

    def test_the_check_summary_starts_with_the_step_table_and_links_the_job_summary(self):
        summary = evidence.render(self.record, IMAGE_LINE, RUN)
        lines = summary.splitlines()
        self.assertEqual(lines[0], IMAGE_LINE)
        self.assertIn('| Step | Result | Duration | Details |', summary)
        self.assertIn('| factory | ✅ | 41 s |  |', summary)
        self.assertIn('| backend-test | ❌ | 9 s | 1 of 3 tests failed |', summary)
        self.assertIn('| backend-build | ❌ | 18 s | 2 errors |', summary)
        self.assertIn('| frontend-deps | ➖ not present |  |  |', summary)
        self.assertIn('| frontend-build | ❌ timeout | 300 s |  |', summary)
        self.assertIn(evidence.DATABASE_NOTE, summary)
        self.assertIn(RUN, summary)
        self.assertIn('PASS: check 3', summary)
        self.assertIn('backend/Broken.cs:4', summary)
        self.assertLessEqual(len(summary), evidence.MAX_CHECK_SUMMARY)
        self.assertLess(summary.index('| factory |'), summary.index('PASS: check 0'))
        self.assertNotIn('more in the job summary', summary)  # every entry fits; only real overflow is counted
        many = evidence.record([evidence.step('backend-test', 'failed', 1.0, 1,
                                              cases=[{'name': f'T{n}', 'status': 'failed'} for n in range(60)])])
        self.assertIn('- … 50 more in the job summary', evidence.render(many, IMAGE_LINE, RUN))

    def test_the_job_summary_lists_every_test_case_and_the_failure_details(self):
        text = evidence.job_summary(self.steps, IMAGE_LINE)
        for name in ('Aicepeak.Api.Tests.FixtureTests.Passes', 'Aicepeak.Api.Tests.FixtureTests.Skipped',
                     'src/api/health.test.ts &gt; getHealthStatus &gt; forwards the abort signal'):
            self.assertIn(name, text)
        self.assertIn('Assert.Equal() Failure: Values differ', text)
        self.assertIn('backend/Aicepeak.Api.Tests/FixtureTests.cs:11', text)
        self.assertIn('<pre>', text)
        self.assertIn('Broken.cs(4,16): error CS0029', text)
        self.assertLessEqual(len(text.encode()), evidence.MAX_JOB_SUMMARY)

    def test_untrusted_strings_cannot_break_out_of_tables_or_mention_anyone(self):
        hostile = 'a|b`c[x](http://evil)<script>@owner #1 ![i](u)\n| injected |'
        case = {'name': hostile, 'status': 'failed', 'message': hostile, 'details': '</pre><script>@x</script>'}
        steps = [evidence.step('backend-test', 'failed', 1.0, 1, cases=[case], tail='</pre>@team')]
        for text in (evidence.render(evidence.record(steps), IMAGE_LINE, RUN), evidence.job_summary(steps, IMAGE_LINE)):
            with self.subTest(text=text[:40]):
                for forbidden in ('<script>', '</pre><', '@owner', '@x', '@team', '#1', '](http', '| injected |', '`c'):
                    self.assertNotIn(forbidden, text)

    def test_huge_job_summaries_are_cut_with_a_marker(self):
        cases = [{'name': f'Test{n} ' + 'n' * 200, 'status': 'passed', 'seconds': 0.1} for n in range(20000)]
        text = evidence.job_summary([evidence.step('backend-test', 'passed', 1.0, 0, cases=cases)], IMAGE_LINE)
        self.assertLessEqual(len(text.encode()), evidence.MAX_JOB_SUMMARY)
        self.assertIn('cut', text)

    def test_annotations_point_at_failing_tests_and_errors_only(self):
        notes = evidence.annotations(self.record)
        self.assertLessEqual(len(notes), 50)
        locations = {(note['path'], note['start_line']) for note in notes}
        self.assertEqual(locations, {('backend/Broken.cs', 4), ('backend/Broken.cs', 2),
                                     ('backend/Aicepeak.Api.Tests/FixtureTests.cs', 11), ('frontend/src/fixture.test.ts', 9)})
        for note in notes:
            self.assertEqual(note['annotation_level'], 'failure')
            self.assertEqual(note['start_line'], note['end_line'])
            self.assertLessEqual(len(note['title']), 255)
        self.assertEqual(evidence.annotations({'summary': 'old'}), [])

    def test_the_module_parses_with_python_3_11_grammar(self):
        ast.parse((ROOT / 'tools/factory/evidence.py').read_text(), feature_version=(3, 11))


if __name__ == '__main__':
    unittest.main()
