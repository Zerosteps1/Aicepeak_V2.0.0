"""Branch model: validation and production branches, gates, review modes and span-only config edits."""
import copy
import difflib
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
import branches
import branch_fixture
from contracts import Blocked

RETIRED = branches.RESERVED[0]  # the former default branch name; never a branch again


def model_config():
    """A complete branch model with every gate and review mode."""
    return {'default_branch': 'testing', 'config_branch': 'production',
            'maintainers': [{'login': 'Zerosteps1', 'id': 1}],
            'branches': {'schema_version': 1,
                         'validation': [{'name': 'testing', 'gate': 'full', 'kinds': ['factory', 'product']},
                                        {'name': 'quick', 'gate': 'tests', 'kinds': ['smoke']},
                                        {'name': 'frozen', 'gate': 'none', 'kinds': []}],
                         'production': [{'name': 'production', 'review': 'maintainer-manual'},
                                        {'name': 'stable', 'review': 'initiated'},
                                        {'name': 'archive', 'review': 'no'}]}}


class Problems(unittest.TestCase):
    def setUp(self):
        self.config = model_config()

    def problems(self, change):
        config = copy.deepcopy(self.config)
        change(config)
        return branches.problems(config)

    def test_repository_and_complete_models_are_valid(self):
        self.assertEqual(branches.problems(json.loads((ROOT / 'factory/config.json').read_text())), [])
        self.assertEqual(branches.problems(self.config), [])

    def test_schema_violations_are_named(self):
        validation = lambda c: c['branches']['validation']
        cases = [
            (lambda c: c.pop('branches'), 'branches needs exactly schema_version, validation and production'),
            (lambda c: c['branches'].update(extra=1), 'branches needs exactly schema_version, validation and production'),
            (lambda c: c.update(branches=[]), 'branches needs exactly schema_version, validation and production'),
            (lambda c: c['branches'].update(schema_version=2), 'branches.schema_version must be 1'),
            (lambda c: c['branches'].update(validation=[]), 'branches.validation needs 1 to 20 entries'),
            (lambda c: c['branches'].update(validation={}), 'branches.validation needs 1 to 20 entries'),
            (lambda c: validation(c).extend({'name': f'v{i}', 'gate': 'none', 'kinds': []} for i in range(18)),
             'branches.validation needs 1 to 20 entries'),
            (lambda c: c['branches']['production'].extend({'name': f'p{i}', 'review': 'no'} for i in range(3)),
             'branches.production needs 1 to 5 entries'),
            (lambda c: validation(c).append('quick'), 'each validation branch needs exactly gate, kinds, name'),
            (lambda c: validation(c)[1].pop('gate'), 'each validation branch needs exactly gate, kinds, name'),
            (lambda c: c['branches']['production'][1].update(gate='full'), 'each production branch needs exactly name, review'),
        ]
        for change, message in cases:
            with self.subTest(message=message):
                self.assertIn(message, self.problems(change))

    def test_names_must_match_the_pattern_and_avoid_reserved_names(self):
        for name in ('Testing', '-x', 'x-', 'a_b', 'a/b', 'a.b', '', 'x' * 41, 7, None):
            with self.subTest(name=name):
                found = self.problems(lambda c: c['branches']['validation'][2].update(name=name))
                self.assertTrue(any(p.startswith(f'invalid branch name {name!r}') for p in found), found)
        for name in ('a', '9', 'a-b', 'x' * 40):
            with self.subTest(name=name):
                self.assertEqual(self.problems(lambda c: c['branches']['validation'][2].update(name=name)), [])
        # The retired default branch, Git's special names and maintainer logins (case-insensitive) are reserved.
        for name in (*branches.RESERVED, 'zerosteps1'):
            with self.subTest(name=name):
                self.assertIn(f'branch name {name} is reserved',
                              self.problems(lambda c: c['branches']['validation'][2].update(name=name)))

    def test_names_are_unique_across_levels(self):
        self.assertIn('branch quick is listed twice',
                      self.problems(lambda c: c['branches']['production'][2].update(name='quick')))
        self.assertIn('branch stable is listed twice',
                      self.problems(lambda c: c['branches']['production'].append({'name': 'stable', 'review': 'no'})))

    def test_gate_review_and_kind_values(self):
        self.assertIn('quick: gate must be one of full, tests, none',
                      self.problems(lambda c: c['branches']['validation'][1].update(gate='strict')))
        self.assertIn('stable: review must be one of no, initiated, maintainer-manual',
                      self.problems(lambda c: c['branches']['production'][1].update(review='yes')))
        for kinds in (['docs'], ['smoke', 'smoke'], 'smoke', None):
            with self.subTest(kinds=kinds):
                self.assertIn('quick: kinds must be distinct values of factory, product, smoke',
                              self.problems(lambda c: c['branches']['validation'][1].update(kinds=kinds)))

    def test_every_kind_is_routed_exactly_once(self):
        self.assertIn('kind smoke is routed to both quick and frozen',
                      self.problems(lambda c: c['branches']['validation'][2].update(kinds=['smoke'])))
        self.assertIn('kind smoke is routed to no validation branch',
                      self.problems(lambda c: c['branches']['validation'][1].update(kinds=[])))

    def test_config_branch_is_production_and_default_branch_is_validation(self):
        for change in (lambda c: c.update(config_branch='testing'), lambda c: c.update(config_branch='missing'),
                       lambda c: c.pop('config_branch')):
            self.assertIn('config_branch must be a production branch', self.problems(change))
        for change in (lambda c: c.update(default_branch='production'), lambda c: c.update(default_branch='missing'),
                       lambda c: c.pop('default_branch')):
            self.assertIn('default_branch must be a validation branch', self.problems(change))

    def test_every_violation_is_named_in_one_pass(self):
        def change(config):
            config['branches']['validation'][0].update(name=RETIRED)
            config['branches']['production'][1].update(review='later')
            config['config_branch'] = 'quick'
        found = self.problems(change)
        self.assertEqual(found, [f'branch name {RETIRED} is reserved', 'stable: review must be one of no, initiated, maintainer-manual',
                                 'config_branch must be a production branch', 'default_branch must be a validation branch'])
        with self.assertRaises(Blocked) as raised:
            config = copy.deepcopy(self.config)
            change(config)
            branches.parse(config)
        for problem in found:
            self.assertIn(problem, str(raised.exception))


class Model(unittest.TestCase):
    def setUp(self):
        self.model = branches.parse(model_config())

    def test_accessors(self):
        m = self.model
        self.assertEqual((m.config_branch, m.default_branch), ('production', 'testing'))
        self.assertEqual(m.names, ['testing', 'quick', 'frozen', 'production', 'stable', 'archive'])
        self.assertEqual([m.level(n) for n in ('testing', 'stable', 'feature', None)], ['validation', 'production', None, None])
        self.assertEqual([m.gate(n) for n in ('testing', 'quick', 'frozen', 'production', 'feature')], ['full', 'tests', 'none', None, None])
        self.assertEqual([m.gated(n) for n in ('testing', 'quick', 'frozen', 'production', 'feature')], [True, True, False, False, False])
        self.assertEqual([m.review(n) for n in ('production', 'stable', 'archive', 'testing')], ['maintainer-manual', 'initiated', 'no', None])
        self.assertEqual([m.route(k) for k in branches.KINDS], ['testing', 'testing', 'quick'])

    def test_required_checks_follow_the_gate_and_the_review_mode(self):
        m = self.model
        self.assertEqual(m.required_checks('testing'), ('factory/deterministic', 'factory/senior-review'))
        self.assertEqual(m.required_checks('quick'), ('factory/deterministic',))
        self.assertEqual(m.required_checks('frozen'), ())
        self.assertEqual(m.required_checks('production'), ('factory/deterministic', 'factory/production/production'))
        self.assertEqual([n for n in m.production if m.review_required(n)], ['production'])
        self.assertEqual(m.required_checks('stable'), ('factory/deterministic', 'factory/production/stable'))
        self.assertEqual(m.required_checks('archive'), ('factory/deterministic', 'factory/production/archive'))
        self.assertEqual(branches.production_check('stable'), 'factory/production/stable')
        self.assertEqual((branches.DETERMINISTIC, branches.SENIOR), ('factory/deterministic', 'factory/senior-review'))
        with self.assertRaisesRegex(Blocked, 'not a listed branch'):
            m.required_checks('feature')

    def test_a_finished_config_branch_change_is_followed_once(self):
        old = model_config()
        moved = branches.with_config_branch(old, 'stable')
        configs = {'production': old, 'stable': moved}
        self.assertEqual(branches.follow(configs.get, 'production'), ('production', old))
        configs['production'] = moved  # the change is merged into the old config branch
        self.assertEqual(branches.follow(configs.get, 'production'), ('stable', moved))
        configs['stable'] = old  # the new branch does not name itself yet
        with self.assertRaisesRegex(Blocked, 'not finished'):
            branches.follow(configs.get, 'production')
        configs['stable'] = branches.with_config_branch(old, 'archive')  # a second hop is never followed
        with self.assertRaisesRegex(Blocked, 'not finished'):
            branches.follow(configs.get, 'production')
        unlisted = copy.deepcopy(moved)
        unlisted['config_branch'] = 'feature'
        with self.assertRaisesRegex(Blocked, 'breaks the branch model'):
            branches.follow({'production': unlisted, 'feature': unlisted}.get, 'production')
        with self.assertRaisesRegex(Blocked, 'unavailable'):
            branches.follow({}.get, 'production')

    def test_the_repository_model_is_valid(self):
        # Only validity: config PRs change the branch list and run these trusted tests against it.
        self.assertEqual(branches.problems(json.loads((ROOT / 'factory/config.json').read_text())), [])

    def test_the_fixed_test_model_is_the_delivered_one(self):
        config = branch_fixture.load(ROOT)
        self.assertEqual(branches.problems(config), [])
        m = branches.parse(config)
        self.assertEqual((m.config_branch, m.default_branch, m.gate('testing'), m.review('production')),
                         ('production', 'testing', 'full', 'maintainer-manual'))
        self.assertEqual({m.route(k) for k in branches.KINDS}, {'testing'})
        self.assertEqual(json.loads(branch_fixture.text(ROOT)), config)


class Edits(unittest.TestCase):
    def setUp(self):
        self.config = model_config()
        # The real layout with the fixed branch model: a config PR may change the candidate's branch list.
        self.text = branch_fixture.text(ROOT)

    def test_helpers_change_only_the_branch_list(self):
        added = branches.with_validation(self.config, 'next', 'full', ['smoke', 'product'])
        self.assertEqual([(e['name'], e['kinds']) for e in added['branches']['validation']],
                         [('testing', ['factory']), ('quick', []), ('frozen', []), ('next', ['smoke', 'product'])])
        changed = branches.with_validation(self.config, 'quick', 'full', ['smoke'])
        self.assertEqual(changed['branches']['validation'][1], {'name': 'quick', 'gate': 'full', 'kinds': ['smoke']})
        self.assertEqual(self.config, model_config(), 'helpers never mutate their input')
        self.assertEqual(branches.with_production(self.config, 'stable', 'no')['branches']['production'][1],
                         {'name': 'stable', 'review': 'no'})
        self.assertEqual(branches.with_production(self.config, 'edge', 'initiated')['branches']['production'][-1],
                         {'name': 'edge', 'review': 'initiated'})
        removed = branches.without(self.config, 'quick')
        self.assertEqual([e['name'] for e in removed['branches']['validation']], ['testing', 'frozen'])
        self.assertEqual(removed['branches']['validation'][0]['kinds'], ['factory', 'product', 'smoke'])
        self.assertEqual([e['name'] for e in branches.without(self.config, 'stable')['branches']['production']],
                         ['production', 'archive'])
        self.assertEqual(branches.with_config_branch(self.config, 'stable')['config_branch'], 'stable')
        for name in ('production', 'testing'):
            with self.subTest(name=name), self.assertRaisesRegex(Blocked, 'config or default branch'):
                branches.without(self.config, name)

    def test_unchanged_edit_keeps_the_real_config_text_byte_identical(self):
        self.assertEqual(branches.edited(self.text, lambda config: config), self.text)

    def changed_lines(self, before, after):
        return [line for line in difflib.ndiff(before.splitlines(), after.splitlines()) if line[:2] in ('- ', '+ ')]

    def test_edits_splice_only_the_branches_and_config_branch_spans_of_the_real_config(self):
        text = branches.edited(self.text, lambda c: branches.with_validation(c, 'quick', 'tests', ['smoke']))
        text = branches.edited(text, lambda c: branches.with_production(c, 'stable', 'initiated'))
        text = branches.edited(text, lambda c: branches.with_config_branch(c, 'stable'))
        config = json.loads(text)
        self.assertEqual(config['config_branch'], 'stable')
        self.assertEqual(config['branches']['validation'][1], {'name': 'quick', 'gate': 'tests', 'kinds': ['smoke']})
        original = json.loads(self.text)
        rest = lambda c: {k: v for k, v in c.items() if k not in ('branches', 'config_branch')}
        self.assertEqual(rest(config), rest(original))
        self.assertEqual(self.changed_lines(self.text, text), [
            '-   "config_branch": "production",', '+   "config_branch": "stable",',
            '-       {"name": "testing", "gate": "full", "kinds": ["factory", "product", "smoke"]}',
            '+       {"name": "testing", "gate": "full", "kinds": ["factory", "product"]},',
            '+       {"name": "quick", "gate": "tests", "kinds": ["smoke"]}',
            '-       {"name": "production", "review": "maintainer-manual"}',
            '+       {"name": "production", "review": "maintainer-manual"},',
            '+       {"name": "stable", "review": "initiated"}'])
        # Everything outside the two spans, including formatting, is untouched.
        head = self.text.index('\n  "config_branch": ')
        tail = self.text.index('\n  "require_second_human_review"')
        self.assertEqual(text[:head], self.text[:head])
        self.assertTrue(text.endswith(self.text[tail:]))
        back = branches.edited(text, lambda c: branches.with_config_branch(c, 'production'))
        back = branches.edited(back, lambda c: branches.without(c, 'stable'))
        back = branches.edited(back, lambda c: branches.without(c, 'quick'))
        self.assertEqual(back, self.text)

    def test_edits_that_break_the_model_or_touch_other_keys_are_refused(self):
        cases = [(lambda c: branches.without(c, 'production'), 'config or default branch'),
                 (lambda c: branches.without(c, 'testing'), 'config or default branch'),
                 (lambda c: branches.with_config_branch(c, 'testing'), 'would break the branch model: config_branch must be a production branch'),
                 (lambda c: branches.with_validation(c, RETIRED, 'full', []), f'would break the branch model: branch name {RETIRED} is reserved'),
                 (lambda c: branches.with_validation(c, 'quick', 'sometimes', ['smoke']), 'would break the branch model'),
                 (lambda c: {**c, 'repository': 'other/repo'}, 'may change only branches and config_branch'),
                 (lambda c: {**c, 'default_branch': 'quick', 'branches': branches.with_validation(c, 'quick', 'full', [])['branches']},
                  'may change only branches and config_branch')]
        for change, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(Blocked, message):
                branches.edited(self.text, change)
        # The last production branch is always the config branch, so it can never be removed.
        config = json.loads(self.text)
        self.assertEqual([e['name'] for e in config['branches']['production']], [config['config_branch']])
        with self.assertRaisesRegex(Blocked, 'not valid JSON'):
            branches.edited('{', lambda c: c)
        with self.assertRaisesRegex(Blocked, 'exactly one top-level config_branch'):
            branches.edited(self.text.replace('\n  "config_branch": ', '\n    "config_branch": '), lambda c: c)


if __name__ == '__main__':
    unittest.main()
