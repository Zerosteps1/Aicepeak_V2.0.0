import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
from contracts import Blocked, allowed_patch, assert_current, authentic_check, gates, handoff, safe_path, validate_review


class Gates(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / 'factory/config.json').read_text())
        self.config.update(publisher_app_id=7, maintainers=[{'login':'human-fixture','id':1}])
        self.snapshot = dict(repository='fixture/repo', pr=1, head_sha='a'*40, base_sha='b'*40, policy_sha='b'*40, run_id=3, run_attempt=1, files=['src/math.py'])
        self.review = {**{k:v for k,v in self.snapshot.items() if k!='files'}, 'model':'gpt-6-astra','effort':'high','scope':['src/math.py'],'evidence':['actual test exit 0'],'limitations':[],'complete':True,'outcome':'pass','summary':'Correct small change','findings':[]}
        self.schema = json.loads((ROOT/'factory/review.schema.json').read_text())
        self.pr = {'state':'open','draft':False,'head':{'sha':'a'*40,'repo':{'full_name':'fixture/repo'}},'base':{'sha':'b'*40}}

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

    def test_new_head_and_new_base_invalidate_review(self):
        assert_current(self.snapshot,self.pr,'b'*40)
        for path in ['head','base']:
            pr=copy.deepcopy(self.pr);pr[path]['sha']='c'*40
            with self.subTest(path=path),self.assertRaises(Blocked):assert_current(self.snapshot,pr,'b'*40)

    def test_draft_never_passes(self):
        self.assertEqual(gates('pass',True,True,True)['factory/senior-review'],'failure')

    def test_path_traversal_and_factory_changes_rejected(self):
        for p in ['../x','/tmp/x','x/../../y','.git/config','a\\b','a\nb']:
            with self.subTest(p=p),self.assertRaises(Blocked):safe_path(p)
        with self.assertRaises(Blocked):allowed_patch(['.github/workflows/anything.yml'],{'allowed_paths':['.github/']},self.config)
        allowed_patch(['src/math.py'],{'allowed_paths':['src/']},self.config)

    def test_forged_comment_or_other_app_cannot_authorize_remediation(self):
        check={'app':{'id':7},'name':'factory/senior-review','head_sha':'a'*40,'status':'completed','external_id':f"fixture/repo:1:{'a'*40}:{'b'*40}:3:1",'details_url':'https://github.com/fixture/repo/actions/runs/3'}
        authentic_check(check,self.snapshot,self.config)
        check['app']['id']=8
        with self.assertRaises(Blocked):authentic_check(check,self.snapshot,self.config)

    def test_no_commands_in_handoff(self):
        body='```factory-handoff\n'+json.dumps({'runner':'claude','task':'docs/work/A.md','owner':'human-fixture'})+'\n```'
        self.assertEqual(handoff(body,self.config)['runner'],'claude')
        with self.assertRaises(Blocked):handoff(body.replace('claude','sh -c evil'),self.config)
        # Only the Claude author runs automatically (ADR-0005); a Codex author needs a reviewed change.
        with self.assertRaisesRegex(Blocked,'allowlisted'):handoff(body.replace('claude','codex'),self.config)
        with self.assertRaises(Blocked):handoff(body+'\n'+body,self.config)


if __name__=='__main__':unittest.main()
