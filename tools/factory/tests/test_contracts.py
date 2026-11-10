import copy
import json
import subprocess
import unittest

from factory_testlib import ROOT, fixture_config
from contracts import (REVIEWER, Blocked, allowed_patch, assert_current, authentic_check, binding, gates, handoff, maintainer,
                       safe_path, validate_review)


class Gates(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()
        # policy_sha is the config branch tip, base_sha the target branch tip.
        self.snapshot = dict(repository='fixture/repo', pr=1, head_sha='a'*40, base_sha='e'*40, base_ref='testing', policy_sha='b'*40, run_id=3, run_attempt=1, files=['src/math.py'])
        self.review = {**{k:v for k,v in self.snapshot.items() if k not in ('files', 'base_ref')}, 'model':'gpt-6-astra','effort':'high','scope':['src/math.py'],'evidence':['actual test exit 0'],'limitations':[],'complete':True,'outcome':'pass','summary':'Correct small change','findings':[]}
        self.schema = json.loads((ROOT/'factory/review.schema.json').read_text())
        self.pr = {'state':'open','draft':False,'head':{'sha':'a'*40,'repo':{'full_name':'fixture/repo'}},'base':{'ref':'testing','sha':'e'*40}}

    def test_clean_change_is_not_forced_to_have_findings(self):
        self.assertEqual(validate_review(self.review,self.schema,self.snapshot),'pass')

    def test_generation_schema_rejects_partial_finding_identifiers(self):
        pattern = self.schema['properties']['findings']['items']['properties']['id']['pattern']
        finding = dict(id='F-001', kind='defect', confidence='high', priority='P1',
                       file='src/math.py', line=2, impact='wrong total', evidence='2+2 yields 5',
                       requirement='sum', minimal_fix='correct addition', verification='2+2 equals 4')
        # JSON Schema uses ECMAScript search semantics, not Python re.search.
        # In particular, ECMAScript without the m flag rejects a trailing newline.
        # Node is already part of the pinned Factory runtime; no provider call.
        cases = [('F-001', True), ('SMOKE_EXPLANATION', True), ('F-1', True),
                 ('f-1', False), ('prefix-F-001', False), ('F-001-suffix', False),
                 ('F 001', False), ('F.001', False), ('F-001/x', False),
                 ('F-001\n', False), ('F-001\r', False), ('F-001\r\n', False),
                 ('F-001\u2028', False), ('F-001\u2029', False)]
        result = subprocess.run(
            ['node', '-e', "const p=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
             "const regex=new RegExp(p.pattern);"
             "process.stdout.write(JSON.stringify(p.ids.map(id=>regex.test(id))));"],
            input=json.dumps({'pattern': pattern, 'ids': [item[0] for item in cases]}),
            text=True, capture_output=True, check=True, timeout=10)
        generation_accepts = json.loads(result.stdout)
        self.assertEqual(len(generation_accepts), len(cases))
        for (identifier, valid), accepted in zip(cases, generation_accepts):
            with self.subTest(identifier=identifier):
                self.assertIs(accepted, valid,
                                 'generation must not accept an ID rejected by the local contract')
                self.review.update(outcome='changes_requested', findings=[{**finding, 'id': identifier}])
                if valid:
                    self.assertEqual(validate_review(self.review, self.schema, self.snapshot), 'changes_requested')
                else:
                    with self.assertRaisesRegex(Blocked, r'review\.findings\[\]\.id: pattern'):
                        validate_review(self.review, self.schema, self.snapshot)

    def test_the_reviewer_is_fixed_in_code_and_named_by_the_review_schema(self):
        self.assertEqual(REVIEWER, {'model': 'gpt-6-astra', 'effort': 'high'})
        self.assertEqual({key: self.schema['properties'][key]['const'] for key in REVIEWER}, REVIEWER)
        # Without the schema's constants the code still refuses any other reviewer.
        loose = copy.deepcopy(self.schema)
        for key in REVIEWER:
            del loose['properties'][key]['const']
        self.assertEqual(validate_review(self.review, loose, self.snapshot), 'pass')
        for key, value in (('model', 'gpt-6'), ('effort', 'medium')):
            with self.subTest(key=key), self.assertRaisesRegex(Blocked, 'wrong reviewer'):
                validate_review({**self.review, key: value}, loose, self.snapshot)
            with self.subTest(key=key, schema='strict'), self.assertRaisesRegex(Blocked, f'review.{key}: incorrect constant'):
                validate_review({**self.review, key: value}, self.schema, self.snapshot)

    def test_blocking_finding_cannot_be_published_as_pass(self):
        self.review['findings']=[dict(id='F-1',kind='defect',confidence='high',priority='P1',file='src/math.py',line=2,impact='wrong total',evidence='2+2 yields 5',requirement='sum',minimal_fix='correct addition',verification='2+2 equals 4')]
        with self.assertRaises(Blocked): validate_review(self.review,self.schema,self.snapshot)

    def test_confidence_never_hides_a_blocking_defect(self):
        self.review.update(outcome='changes_requested', findings=[dict(id='F-1', kind='defect', confidence='low', priority='P1', file='src/math.py', line=2, impact='wrong total', evidence='2+2 yields 5', requirement='sum', minimal_fix='correct addition', verification='2+2 equals 4')])
        self.assertEqual(validate_review(self.review,self.schema,self.snapshot), 'changes_requested')
        self.review['outcome']='pass'
        with self.assertRaisesRegex(Blocked,'invalid pass'):
            validate_review(self.review,self.schema,self.snapshot)

    def test_questions_are_not_disguised_as_blocking_defects(self):
        self.review.update(outcome='changes_requested', findings=[dict(id='F-1', kind='question', confidence='low', priority='P1', file='src/math.py', line=2, impact='uncertain', evidence='missing context', requirement='sum', minimal_fix='ask for context', verification='inspect requirement')])
        with self.assertRaisesRegex(Blocked,'only defects'):
            validate_review(self.review,self.schema,self.snapshot)

    def test_missing_scope_api_errors_and_limits_never_green(self):
        for field, value in [('scope',[]),('complete',False),('limitations',['file missing']),('effort','medium'),('run_id',4)]:
            review=copy.deepcopy(self.review);review[field]=value
            with self.subTest(field=field), self.assertRaises(Blocked): validate_review(review,self.schema,self.snapshot)
        self.assertEqual(gates('blocked',False,True),{'factory/deterministic':'failure','factory/senior-review':'failure'})

    def test_new_head_target_tip_target_branch_or_config_tip_invalidate_review(self):
        assert_current(self.snapshot,self.pr,'b'*40,'e'*40)
        for path,key,message in [('head','sha','stale head'),('base','sha','stale base'),('base','ref','target branch changed')]:
            pr=copy.deepcopy(self.pr);pr[path][key]='c'*40
            with self.subTest(path=path,key=key),self.assertRaisesRegex(Blocked,message):assert_current(self.snapshot,pr,'b'*40,'e'*40)
        for policy_tip,base_tip,message in [('c'*40,'e'*40,'stale policy'),('b'*40,'c'*40,'stale base')]:
            with self.subTest(policy_tip=policy_tip,base_tip=base_tip),self.assertRaisesRegex(Blocked,message):
                assert_current(self.snapshot,self.pr,policy_tip,base_tip)
        for change,message in [({'state':'closed'},'closed'),({'draft':True},'draft'),({'head':{'sha':'a'*40,'repo':{'full_name':'fork/repo'}}},'fork')]:
            with self.subTest(change=change),self.assertRaisesRegex(Blocked,message):
                assert_current(self.snapshot,{**self.pr,**change},'b'*40,'e'*40)

    def test_binding_names_the_target_branch_in_seven_fields(self):
        self.assertEqual(binding(self.snapshot),f"fixture/repo:1:{'a'*40}:{'b'*40}:testing:3:1")
        self.assertEqual(len(binding(self.snapshot).split(':')),7)
        self.assertNotEqual(binding(self.snapshot),binding({**self.snapshot,'base_ref':'production'}))

    def test_draft_never_passes(self):
        self.assertEqual(gates('pass',True,True,True)['factory/senior-review'],'failure')

    def test_path_traversal_and_factory_changes_rejected(self):
        for p in ['../x','/tmp/x','x/../../y','.git/config','a\\b','a\nb']:
            with self.subTest(p=p),self.assertRaises(Blocked):safe_path(p)
        with self.assertRaises(Blocked):allowed_patch(['.github/workflows/anything.yml'],{'allowed_paths':['.github/']},self.config)
        allowed_patch(['src/math.py'],{'allowed_paths':['src/']},self.config)

    def test_forged_comment_or_other_app_cannot_authorize_remediation(self):
        check={'app':{'id':7},'name':'factory/senior-review','head_sha':'a'*40,'status':'completed','external_id':f"fixture/repo:1:{'a'*40}:{'b'*40}:testing:3:1",'details_url':'https://github.com/fixture/repo/actions/runs/3'}
        authentic_check(check,self.snapshot,self.config)
        # A binding without the target branch, or with another one, never counts.
        for external_id in (f"fixture/repo:1:{'a'*40}:{'b'*40}:3:1", f"fixture/repo:1:{'a'*40}:{'b'*40}:production:3:1"):
            with self.subTest(external_id=external_id),self.assertRaisesRegex(Blocked,'binding'):
                authentic_check({**check,'external_id':external_id},self.snapshot,self.config)
        check['app']['id']=8
        with self.assertRaises(Blocked):authentic_check(check,self.snapshot,self.config)

    def test_no_commands_in_handoff(self):
        body='```factory-handoff\n'+json.dumps({'runner':'claude','task':'docs/work/A.md','owner':'test-human'})+'\n```'
        self.assertEqual(handoff(body,self.config)['runner'],'claude')
        with self.assertRaises(Blocked):handoff(body.replace('claude','sh -c evil'),self.config)
        # Only the Claude author runs automatically (ADR-0005); a Codex author needs a reviewed change.
        with self.assertRaisesRegex(Blocked,'allowlisted'):handoff(body.replace('claude','codex'),self.config)
        with self.assertRaises(Blocked):handoff(body+'\n'+body,self.config)


class Maintainers(unittest.TestCase):
    def test_a_maintainer_is_a_configured_user_id_whose_login_matches_in_any_case(self):
        config = {'maintainers': [None, {'login': 'Alice', 'id': 101}, {'login': 'bob', 'id': 102}]}
        alice = {'type': 'User', 'id': 101, 'login': 'Alice'}
        self.assertEqual(maintainer(alice, config), {'login': 'Alice', 'id': 101})
        self.assertEqual(maintainer({**alice, 'login': 'aLICE'}, config), {'login': 'Alice', 'id': 101})
        self.assertEqual(maintainer({'type': 'User', 'id': 102, 'login': 'Bob'}, config)['login'], 'bob')
        refused = {'renamed account': {**alice, 'login': 'alice-new'}, 'recreated account': {**alice, 'id': 999},
                   'another maintainer\'s id': {**alice, 'id': 102}, 'bot': {**alice, 'type': 'Bot'},
                   'no type': {'id': 101, 'login': 'Alice'}, 'id as text': {**alice, 'id': '101'},
                   'no login': {'type': 'User', 'id': 101}, 'login not text': {**alice, 'login': None},
                   'no user': None, 'a login alone': 'Alice'}
        for name, user in refused.items():
            with self.subTest(name):
                self.assertIsNone(maintainer(user, config))


if __name__=='__main__':unittest.main()
