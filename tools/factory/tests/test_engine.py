"""Boundary regressions with real Git/stdlib and GitHub mocked only at transport."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(os.environ.get('FACTORY_CANDIDATE',Path(__file__).resolve().parents[3]))
sys.path.insert(0,str(ROOT/'tools/factory'))
import engine
import verify
from contracts import Blocked


class Transport:
    def __init__(self, config):
        self.config=config
        self.checks={}
        self.comments=[]
        self.labels=set()
        self.calls=[]
        self.runs={}
        self.files=[{'filename':'example.txt','status':'modified'}]
        self.task={'status':'approved','kind':'factory','allowed_paths':['example.txt']}
        self.compare={'status':'ahead','behind_by':0}
        self.pr={'number':1,'state':'open','draft':False,'changed_files':1,
                 'head':{'sha':'a'*40,'repo':{'full_name':'fixture/repo'}},
                 'base':{'ref':'main','sha':'b'*40},
                 'body':'```factory-handoff\n'+json.dumps({'runner':'claude','task':'docs/work/TEST.md','owner':'test-human'})+'\n```'}

    def request(self,method,path,data=None):
        self.calls.append((method,path,data))
        if method=='GET':
            if path.endswith('/check-runs/'+path.rsplit('/',1)[-1]) and '/check-runs/' in path:
                return copy.deepcopy(self.checks[int(path.rsplit('/',1)[-1])])
            if path=='/repos/fixture/repo':return {'full_name':'fixture/repo','default_branch':'main'}
            if path.endswith('/pulls/1'):return copy.deepcopy(self.pr)
            if path.endswith('/git/ref/heads/main'):return {'object':{'sha':'b'*40}}
            if '/compare/' in path:return copy.deepcopy(self.compare)
        if method=='PATCH' and '/check-runs/' in path:
            self.checks[int(path.rsplit('/',1)[-1])].update(copy.deepcopy(data))
            return {}
        if method=='GET' and '/actions/runs/' in path:
            return copy.deepcopy(self.runs[int(path.rsplit('/',1)[-1])])
        if method=='POST' and path.endswith('/issues/1/labels'):
            self.labels.update(data['labels'])
            return {}
        if method=='DELETE' and '/issues/1/labels/' in path:
            self.labels.remove(path.rsplit('/',1)[-1])
            return {}
        if path.endswith('/labels'):return {}
        if method=='POST' and path.endswith('/check-runs'):
            item={**data,'id':len(self.checks)+1,'app':{'id':7}}
            self.checks[item['id']]=copy.deepcopy(item)
            return item
        if method=='POST' and path.endswith('/comments'):
            self.comments.append({**data,'performed_via_github_app':{'id':7},'user':{'type':'Bot','id':77}})
            return {'id':len(self.comments)}
        raise AssertionError((method,path))

    def pages(self,path,field=None):
        if path.endswith('/issues/1/comments'):return copy.deepcopy(self.comments)
        if path.endswith('/issues/1/labels'):return [{'name':name} for name in sorted(self.labels)]
        if path.endswith('/files'):return copy.deepcopy(self.files)
        return []

    def text(self,*args):return '```factory-task\n'+json.dumps(self.task)+'\n```'


class EngineBoundaries(unittest.TestCase):
    def setUp(self):
        self.config=json.loads((ROOT/'factory/config.json').read_text())
        self.config.update(repository='fixture/repo',publisher_app_id=7,
                           maintainers=[{'id':1,'login':'test-human'}])
        self.transport=Transport(self.config)
        self.snapshot={'repository':'fixture/repo','pr':1,'head_sha':'a'*40,
                       'base_sha':'b'*40,'policy_sha':'b'*40,'run_id':1,'run_attempt':1}
        self.env=patch.dict(os.environ,{'GITHUB_SHA':'b'*40,'GITHUB_RUN_ID':'1',
                    'GITHUB_RUN_ATTEMPT':'1','FACTORY_RETRY':'false'})
        self.env.start();self.addCleanup(self.env.stop)

    def capture_snapshot(self):
        captured={}
        with patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'emit',side_effect=lambda name,value:captured.update({name:value})):
            engine.snapshot_stage(argparse.Namespace(pr=1,feedback_kind='',feedback_id=0),self.config)
        return captured['snapshot']

    def test_forcepush_cannot_reset_budget_or_round_limit(self):
        rounds=self.config['limits']['max_rounds']
        for n in range(rounds):
            engine.reserve(self.transport,{**self.snapshot,'head_sha':str(n)*40},self.config,'factory/author-reservation',1,str(n))
        with self.assertRaisesRegex(Blocked,'correction rounds exhausted'):
            engine.reserve(self.transport,{**self.snapshot,'head_sha':'f'*40},self.config,'factory/author-reservation',1,'fourth')
        # No commit-list traversal: the PR-scoped App ledger still owns old heads.
        self.assertEqual(len(engine.pr_checks(self.transport,self.snapshot,self.config)),rounds)
        self.config['limits']['max_cost_usd']=rounds  # every round reserved 1 USD
        with self.assertRaisesRegex(Blocked,'cost reservation'):
            engine.reserve(self.transport,self.snapshot,self.config,'factory/senior-review',1,'new-head')

    def test_northstar_approval_alone_does_not_authorize_product_development(self):
        self.config['northstar_approved'] = True
        self.config['product_checks_ready'] = False
        self.transport.task['kind'] = 'product'
        with self.assertRaisesRegex(Blocked, 'product checks not implemented/approved'):
            self.capture_snapshot()

    def test_duplicate_input_cannot_reserve_or_push_twice(self):
        engine.reserve(self.transport,self.snapshot,self.config,'factory/senior-review',1,'same')
        with self.assertRaisesRegex(Blocked,'duplicate'):
            engine.reserve(self.transport,self.snapshot,self.config,'factory/senior-review',1,'same')
        self.assertEqual(len(self.transport.checks),1)

    def test_fake_ledger_comment_has_no_authority(self):
        self.transport.comments=[{'performed_via_github_app':{'id':8},'body':'<!-- factory-ledger:v1 -->\n{"check_id":99}'}]
        self.assertEqual(engine.pr_checks(self.transport,self.snapshot,self.config),[])
        self.assertEqual(self.transport.calls,[])

    def test_draft_then_ready_same_head_receives_new_review(self):
        self.transport.pr['draft']=True
        draft=self.capture_snapshot()
        self.transport.pr['draft']=False
        ready=self.capture_snapshot()
        self.assertNotEqual(draft['reservation']['key'],ready['reservation']['key'])
        # The reviewer runs on a subscription seat (ADR-0005); no USD is reserved for it.
        self.assertEqual(draft['reservation']['reserved_usd'],0)
        self.assertEqual(ready['reservation']['reserved_usd'],0)

    def test_rename_cannot_escape_task_source_or_control_classification(self):
        self.transport.files=[{'filename':'example.txt','previous_filename':'.github/control.yml','status':'renamed'}]
        with self.assertRaisesRegex(Blocked,'rename source'):
            self.capture_snapshot()
        self.transport.task['allowed_paths'].append('.github/')
        self.assertTrue(self.capture_snapshot()['control_changed'])

    def test_rerun_cannot_reuse_snapshot_or_model_budget(self):
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}):
            with self.assertRaisesRegex(Blocked,'reruns'):
                engine.current(self.transport,self.snapshot,self.config)
            with self.assertRaisesRegex(Blocked,'fresh retry'):
                self.capture_snapshot()
        self.assertEqual(self.transport.calls,[])

    def test_human_feedback_changed_during_run_blocks_write(self):
        snapshot=self.capture_snapshot()
        with patch.object(engine,'all_feedback',return_value=[{'body':'New human instruction'}]):
            with self.assertRaisesRegex(Blocked,'feedback changed'):
                engine.current(self.transport,snapshot,self.config)

    def test_pipeline_has_no_api_billed_review_path(self):
        self.assertFalse(hasattr(engine,'call_model') or hasattr(engine,'review_stage'))
        workflow=(ROOT/'.github/workflows/factory.yml').read_text()
        self.assertNotIn('OPENAI_API_KEY',workflow)
        self.assertNotIn('name: Senior review',workflow)
        settings=json.loads((ROOT/'factory/github-settings.json').read_text())
        self.assertNotIn('OPENAI_API_KEY',settings['environment_secrets']+settings['optional_environment_secrets'])

    def test_author_job_federates_instead_of_holding_an_anthropic_key(self):
        workflow=(ROOT/'.github/workflows/factory.yml').read_text()
        author=workflow.split('\n  author:\n',1)[1].split('\n  push:\n',1)[0]
        self.assertIn('id-token: write',author)
        smoke=workflow.split('\n  wif-smoke:\n',1)[1].split('\n  snapshot:\n',1)[0]
        self.assertIn('id-token: write', smoke)
        self.assertEqual(workflow.count('id-token: write'),2)
        self.assertNotIn('ANTHROPIC_API_KEY',workflow)
        settings=json.loads((ROOT/'factory/github-settings.json').read_text())
        self.assertNotIn('ANTHROPIC_API_KEY',settings['environment_secrets']+settings['optional_environment_secrets'])

    def publish(self,tests_ok=True):
        snapshot=self.capture_snapshot()
        tests={'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'run_id':1,'ok':tests_ok,'exit_code':0 if tests_ok else 1,'summary':'trusted output'}
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'TESTS_JSON':json.dumps(tests),'TEST_JOB_RESULT':'success' if tests_ok else 'failure'}
        with patch.dict(os.environ,env), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'verify_run') as run:
            engine.publish_stage(self.config)
        self.assertEqual(run.call_args.args[3],{self.config['test_job']:['success','failure']})
        return snapshot,tests

    def test_publish_leaves_senior_review_awaiting_local_reviewer(self):
        snapshot,tests=self.publish()
        check=self.transport.checks[snapshot['check_id']]
        self.assertEqual(check['status'],'in_progress')
        record=json.loads(check['output']['text'])
        self.assertEqual((record['phase'],record['snapshot'],record['tests']),('awaiting_review',snapshot,tests))
        deterministic=[c for c in self.transport.checks.values() if c['name']=='factory/deterministic']
        self.assertEqual([c['conclusion'] for c in deterministic],['success'])
        self.assertIn('local_review.py --pr 1',self.transport.comments[-1]['body'])
        self.assertEqual(self.transport.labels,{'awaiting-senior-review'})

    def test_failed_tests_complete_review_without_requesting_it(self):
        snapshot,_=self.publish(tests_ok=False)
        check=self.transport.checks[snapshot['check_id']]
        self.assertEqual((check['status'],check['conclusion']),('completed','failure'))
        self.assertEqual(json.loads(check['output']['text'])['phase'],'completed')
        self.assertEqual(self.transport.labels,{'needs-author-action'})

    def test_head_without_current_main_is_not_published_as_tested_merge_state(self):
        # GitHub moves pr.base.sha on a push that never merged main (PRs #4/#5): base equality is not inclusion.
        self.transport.compare={'status':'diverged','behind_by':2}
        snapshot=self.capture_snapshot()
        tests={'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'run_id':1,'ok':True,'exit_code':0,'summary':'trusted output'}
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'TESTS_JSON':json.dumps(tests),'TEST_JOB_RESULT':'success'}
        with patch.dict(os.environ,env), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'verify_run'):
            engine.publish_stage(self.config)
        self.assertIn(('GET','/repos/fixture/repo/compare/'+'b'*40+'...'+'a'*40+'?per_page=1',None),self.transport.calls)
        deterministic=[c for c in self.transport.checks.values() if c['name']=='factory/deterministic']
        self.assertEqual([c['conclusion'] for c in deterministic],['failure'])
        check=self.transport.checks[snapshot['check_id']]
        self.assertEqual((check['status'],check['conclusion'],json.loads(check['output']['text'])['phase']),('completed','failure','completed'))
        self.assertIn('Update branch',check['output']['summary'])
        self.assertEqual(self.transport.labels,{'needs-author-action'})
        self.assertFalse(any('local_review.py' in c['body'] for c in self.transport.comments))
        self.transport.compare={'status':'identical','behind_by':0}
        self.assertTrue(engine.contains_base(self.transport,'fixture/repo','b'*40,'b'*40))
        with self.assertRaisesRegex(Blocked,'invalid commit identifier'):
            engine.contains_base(self.transport,'fixture/repo','main','a'*40)

    def test_installation_transport_allows_only_the_exact_compare_route_with_dots(self):
        import github_api
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,limit):return b'{"status":"identical","behind_by":0}'
        with patch.object(github_api.urllib.request,'urlopen',return_value=Response()) as opened:
            self.assertTrue(engine.contains_base(github_api.GitHub('token'),'fixture/repo','b'*40,'b'*40))
        self.assertEqual(opened.call_args.args[0].full_url,'https://api.github.com/repos/fixture/repo/compare/'+'b'*40+'...'+'b'*40+'?per_page=1')
        for unsafe in ('/repos/fixture/repo/contents/../x','/repos/fixture/repo/compare/'+'b'*40+'..'+'a'*40,'//evil',
                       '/repos/../repo/compare/'+'b'*40+'...'+'a'*40+'?per_page=1'):
            with self.subTest(unsafe=unsafe), patch.object(github_api.urllib.request,'urlopen') as opened, self.assertRaisesRegex(Blocked,'unsafe API path'):
                github_api.GitHub('token').request('GET',unsafe)
            opened.assert_not_called()

    def test_review_prompt_names_the_policy_and_the_incomplete_review_rule(self):
        # A real Astra/high review reported factory/policy.md as missing and returned
        # complete=false with changes_requested, which the gate must discard.
        prompt=engine.review_prompt()
        self.assertTrue(prompt.startswith('TRUSTED POLICY factory/policy.md'))
        self.assertIn((ROOT/'factory/policy.md').read_text(),prompt)
        self.assertIn('complete=false is only valid with outcome blocked',prompt)
        schema=json.loads((ROOT/'factory/review.schema.json').read_text())
        self.assertIn('outcome blocked',schema['properties']['complete']['description'])

    def test_new_passing_head_hands_the_next_step_to_the_reviewer(self):
        self.transport.labels={'needs-author-action','awaiting-senior-review'}
        self.publish()
        self.assertEqual(self.transport.labels,{'awaiting-senior-review'})

    def test_draft_is_blocked_without_an_author_handoff(self):
        self.transport.pr['draft']=True
        self.transport.labels={'awaiting-senior-review','needs-author-action'}
        snapshot=self.capture_snapshot()
        tests={'repository':'fixture/repo','head_sha':'a'*40,'policy_sha':'b'*40,'run_id':1,'ok':True,'exit_code':0,'summary':'trusted output'}
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'TESTS_JSON':json.dumps(tests),'TEST_JOB_RESULT':'success'}
        with patch.dict(os.environ,env), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'verify_run'):
            engine.publish_stage(self.config)
        deterministic=[c for c in self.transport.checks.values() if c['name']=='factory/deterministic']
        self.assertEqual([c['conclusion'] for c in deterministic],['failure'])
        self.assertEqual(self.transport.checks[snapshot['check_id']]['conclusion'],'failure')
        self.assertEqual(self.transport.labels,set())
        self.assertFalse(any(c['body'].startswith('needs-author-action') for c in self.transport.comments))

    def reviewed(self,outcome='changes_requested'):
        snapshot,tests=self.publish()
        findings=[{'id':'F-1','kind':'defect','confidence':'high','priority':'P1','file':'example.txt','line':1,'impact':'i','evidence':'e','requirement':'r','minimal_fix':'m','verification':'v'}] if outcome=='changes_requested' else []
        review={**{k:snapshot[k] for k in ('repository','pr','head_sha','base_sha','policy_sha','run_id','run_attempt')},'model':'gpt-6-astra','effort':'high',
                'scope':['example.txt'],'evidence':[],'limitations':[],'complete':True,'outcome':outcome,'summary':'s','findings':findings}
        check=self.transport.checks[snapshot['check_id']]
        record=json.loads(check['output']['text'])
        check.update(status='completed',conclusion='failure',output={'text':json.dumps({**record,'phase':'completed','review':review})})
        self.transport.runs[2]={'triggering_actor':{'type':'User','id':1}}
        return snapshot

    def correction(self,check_id):
        captured={}
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'emit',side_effect=lambda name,value:captured.update({name:value})):
            engine.correction_stage(argparse.Namespace(pr=1,check_id=check_id),self.config)
        return captured

    def test_exhausted_correction_budget_posts_human_handoff(self):
        self.config['automatic_correction']=True
        snapshot=self.reviewed()
        with patch.object(engine, 'reserve', side_effect=Blocked('correction rounds exhausted')):
            with self.assertRaisesRegex(Blocked, 'rounds exhausted'):
                self.correction(snapshot['check_id'])
        self.assertIn('needs-author-action', self.transport.comments[-1]['body'])
        self.assertIn('correction rounds exhausted', self.transport.comments[-1]['body'])

    def test_correction_is_disabled_until_shadow_phase_ends(self):
        snapshot=self.reviewed()
        self.config['automatic_correction']=False
        with self.assertRaisesRegex(Blocked,'shadow phase'):
            self.correction(snapshot['check_id'])

    def test_correction_reserves_author_round_for_authentic_changes_requested(self):
        snapshot=self.reviewed()
        self.config['automatic_correction']=True
        captured=self.correction(snapshot['check_id'])
        self.assertEqual(captured['snapshot'],snapshot)
        state=captured['author']
        self.assertEqual((state['enabled'],state['check_id'],state['run_id']),(True,snapshot['check_id'],2))
        reservation=self.transport.checks[state['reservation_id']]
        self.assertEqual((reservation['name'],reservation['external_id']),('factory/author-reservation',engine.bind(snapshot)))
        with self.assertRaisesRegex(Blocked,'duplicate'):
            self.correction(snapshot['check_id'])

    def test_correction_rejects_pass_foreign_app_and_unverified_actor(self):
        self.config['automatic_correction']=True
        snapshot=self.reviewed(outcome='pass')
        with self.assertRaisesRegex(Blocked,'does not authorize'):
            self.correction(snapshot['check_id'])
        self.setUp();self.config['automatic_correction']=True
        snapshot=self.reviewed()
        self.transport.checks[snapshot['check_id']]['app']={'id':8}
        with self.assertRaisesRegex(Blocked,'publisher App'):
            self.correction(snapshot['check_id'])
        self.setUp();self.config['automatic_correction']=True
        snapshot=self.reviewed()
        self.transport.runs[2]={'triggering_actor':{'type':'Bot','id':1}}
        with self.assertRaisesRegex(Blocked,'maintainer'):
            self.correction(snapshot['check_id'])

    def test_newer_review_at_same_sha_revokes_old_correction_authority(self):
        self.config['automatic_correction']=True
        old=self.reviewed()
        self.transport.runs[3]={'triggering_actor':{'type':'User','id':1}}
        with patch.dict(os.environ, {'GITHUB_RUN_ID':'3', 'FACTORY_RETRY':'true'}):
            newer=self.capture_snapshot()
        before=len(self.transport.checks)
        self.assertGreater(newer['check_id'],old['check_id'])
        with self.assertRaisesRegex(Blocked,'superseded'):
            self.correction(old['check_id'])
        self.assertEqual(len(self.transport.checks),before)

    def test_newer_review_revokes_an_already_reserved_author_and_push(self):
        self.config['automatic_correction']=True
        old=self.reviewed()
        state=self.correction(old['check_id'])['author']
        self.transport.runs[3]={'triggering_actor':{'type':'User','id':1}}
        with patch.dict(os.environ, {'GITHUB_RUN_ID':'3', 'FACTORY_RETRY':'true'}):
            self.capture_snapshot()
        env={'SNAPSHOT_JSON':json.dumps(old),'AUTHOR_JSON':json.dumps(state),'GITHUB_RUN_ID':'2'}
        with patch.dict(os.environ,env), patch.object(engine,'GitHub',return_value=self.transport), patch.object(engine,'verify_run'):
            with self.assertRaisesRegex(Blocked,'superseded'):
                engine.verified_author_input(self.config)

    def test_author_stages_verify_the_correction_run(self):
        snapshot=self.reviewed()
        self.config['automatic_correction']=True
        state=self.correction(snapshot['check_id'])['author']
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'AUTHOR_JSON':json.dumps(state),'GITHUB_RUN_ID':'2'}
        with patch.dict(os.environ,env), patch.object(engine,'GitHub',return_value=self.transport), patch.object(engine,'verify_run') as run:
            engine.verified_author_input(self.config)
        self.assertEqual(run.call_args.kwargs,{'run_id':2})
        self.assertEqual(run.call_args.args[3],{'Correction gate':['success']})
        with patch.dict(os.environ,{**env,'GITHUB_RUN_ID':'3'}), patch.object(engine,'GitHub',return_value=self.transport), patch.object(engine,'verify_run'):
            with self.assertRaisesRegex(Blocked,'another run'):
                engine.verified_author_input(self.config)

    def test_author_failure_publishes_only_fixed_launcher_reasons(self):
        blocked=lambda reason:(json.dumps({'status':'blocked','reason':reason})+'\n').encode()
        self.assertEqual(engine.author_failure(blocked('docker failed (1): mkdir /work/x: Permission denied sk-ant-secret')),'docker failed (1)')
        self.assertEqual(engine.author_failure(b'model chatter\n'+blocked('credential broker did not become ready')),'credential broker did not become ready')
        self.assertEqual(engine.author_failure(blocked("Command '['docker', '--env', 'TOKEN=ghs_secret']' timed out after 900 seconds")),'launcher command timed out')
        self.assertEqual(engine.author_failure(blocked('expected bounded regular file: /home/runner/secret')),'unclassified launcher error (details withheld)')
        self.assertEqual(engine.author_failure(b'',b'{"status":"passed"}\n'),'no launcher report')
        self.assertEqual(engine.author_failure(b'',blocked('worker CLI version mismatch')),'worker CLI version mismatch')
        for leaked in ('docker failed (1): token','missing proxy-only environment: X=1','unclassified',42):
            self.assertFalse(engine.publishable_failure(leaked))
        self.assertTrue(engine.publishable_failure('missing proxy-only environment: ANTHROPIC_API_KEY, CONTEXT7_API_KEY'))

    def test_atomic_write_rejects_rewind_and_second_identical_push(self):
        class RefAPI:
            def __init__(self):self.head='a'*40
            def request(self,method,path,data=None):
                if path=='/repos/fixture/repo':return {'full_name':'fixture/repo','node_id':'fixture-node'}
                assert path=='/graphql' and method=='POST'
                payload=data['variables']['input']
                # Live schema (GraphQL introspection 2026-10-28): UpdateRefsInput has clientMutationId,
                # repositoryId and refUpdates; 'updates' does not exist (live push failed, run 40766190552).
                assert set(payload)<={'clientMutationId','repositoryId','refUpdates'},payload
                update=payload['refUpdates'][0]
                assert set(update)<={'name','beforeOid','afterOid','force'},update
                assert update['force'] is False
                if update.get('beforeOid')!=self.head:return {'errors':[{'message':'ref changed'}]}
                self.head=update['afterOid']
                return {'data':{'updateRefs':{'clientMutationId':None}}}
        api=RefAPI();api.head='0'*40  # The branch was concurrently rewound to an ancestor.
        with self.assertRaisesRegex(Blocked,'atomic branch update'):
            engine.update_branch(api,'fixture/repo','work','a'*40,'c'*40)
        self.assertEqual(api.head,'0'*40)
        api.head='a'*40
        engine.update_branch(api,'fixture/repo','work','a'*40,'c'*40)
        with self.assertRaises(Blocked):engine.update_branch(api,'fixture/repo','work','a'*40,'c'*40)

    def test_real_git_rename_retains_deleted_source_in_patch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree=Path(tmp)
            def git(*args):return subprocess.check_output(['git','-c','core.hooksPath=/dev/null','-C',tmp,*args],stderr=subprocess.DEVNULL)
            git('init','-q');(tree/'old.txt').write_text('exact same content\n')
            git('add','old.txt');git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture')
            git('mv','old.txt','new.txt')
            self.assertEqual(set(engine.staged_paths(tree)),{'old.txt','new.txt'})

    def test_trusted_suite_detects_broken_candidate_despite_startup_hijack(self):
        with tempfile.TemporaryDirectory() as tmp:
            trusted=Path(tmp)/'trusted';candidate=Path(tmp)/'candidate'
            (trusted/'tools/factory/tests').mkdir(parents=True)
            (candidate/'tools/factory/tests').mkdir(parents=True)
            (candidate/'factory').mkdir()
            shutil.copy2(ROOT/'tools/factory/tests/test_contracts.py',trusted/'tools/factory/tests/test_contracts.py')
            for name in ('config.json','review.schema.json'):shutil.copy2(ROOT/'factory'/name,candidate/'factory'/name)
            code=(ROOT/'tools/factory/contracts.py').read_text()
            code=code.replace('def validate_review(review, schema, snapshot):','def validate_review(review, schema, snapshot):\n    return "pass"')
            (candidate/'tools/factory/contracts.py').write_text(code)
            (candidate/'unittest.py').write_text('raise SystemExit(0)\n')
            (candidate/'sitecustomize.py').write_text('raise SystemExit(0)\n')
            with self.assertRaisesRegex(ValueError,'FAILED'):
                verify.unit_tests(candidate,trusted)


if __name__=='__main__':unittest.main()
