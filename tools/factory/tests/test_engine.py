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
        self.calls=[]
        self.files=[{'filename':'example.txt','status':'modified'}]
        self.task={'status':'approved','kind':'factory','allowed_paths':['example.txt']}
        self.pr={'number':1,'state':'open','draft':False,'changed_files':1,
                 'head':{'sha':'a'*40,'repo':{'full_name':'fixture/repo'}},
                 'base':{'ref':'main','sha':'b'*40},
                 'body':'```factory-handoff\n'+json.dumps({'runner':'codex','task':'docs/work/TEST.md','owner':'test-human'})+'\n```'}

    def request(self,method,path,data=None):
        self.calls.append((method,path,data))
        if method=='GET':
            if path.endswith('/check-runs/'+path.rsplit('/',1)[-1]) and '/check-runs/' in path:
                return copy.deepcopy(self.checks[int(path.rsplit('/',1)[-1])])
            if path=='/repos/fixture/repo':return {'full_name':'fixture/repo','default_branch':'main'}
            if path.endswith('/pulls/1'):return copy.deepcopy(self.pr)
            if path.endswith('/git/ref/heads/main'):return {'object':{'sha':'b'*40}}
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

    def test_forcepush_cannot_reset_budget_or_three_round_limit(self):
        for n in range(3):
            engine.reserve(self.transport,{**self.snapshot,'head_sha':str(n)*40},self.config,'factory/author-reservation',1,str(n))
        with self.assertRaisesRegex(Blocked,'three correction'):
            engine.reserve(self.transport,{**self.snapshot,'head_sha':'f'*40},self.config,'factory/author-reservation',1,'fourth')
        # No commit-list traversal: the PR-scoped App ledger still owns old heads.
        self.assertEqual(len(engine.pr_checks(self.transport,self.snapshot,self.config)),3)
        self.config['limits']['max_cost_usd']=3
        with self.assertRaisesRegex(Blocked,'cost reservation'):
            engine.reserve(self.transport,self.snapshot,self.config,'factory/senior-review',1,'new-head')

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
        self.assertEqual(draft['reservation']['reserved_usd'],0)
        self.assertGreater(ready['reservation']['reserved_usd'],0)

    def test_rename_cannot_escape_task_source_or_control_classification(self):
        self.transport.files=[{'filename':'example.txt','previous_filename':'.github/control.yml','status':'renamed'}]
        with self.assertRaisesRegex(Blocked,'rename source'):
            self.capture_snapshot()
        self.transport.task['allowed_paths'].append('.github/')
        self.assertTrue(self.capture_snapshot()['control_changed'])

    def test_rerun_cannot_reuse_snapshot_or_model_budget(self):
        with patch.dict(os.environ,{'GITHUB_RUN_ATTEMPT':'2'}), patch.object(engine,'call_model') as model:
            with self.assertRaisesRegex(Blocked,'reruns'):
                engine.current(self.transport,self.snapshot,self.config)
            with self.assertRaisesRegex(Blocked,'fresh retry'):
                self.capture_snapshot()
            model.assert_not_called()
        self.assertEqual(self.transport.calls,[])

    def test_human_feedback_changed_during_run_blocks_write(self):
        snapshot=self.capture_snapshot()
        with patch.object(engine,'all_feedback',return_value=[{'body':'New human instruction'}]):
            with self.assertRaisesRegex(Blocked,'feedback changed'):
                engine.current(self.transport,snapshot,self.config)

    def test_missing_api_key_fails_before_request(self):
        with patch.dict(os.environ,{},clear=True), patch.object(engine.urllib.request,'urlopen') as network:
            with self.assertRaisesRegex(Blocked,'OPENAI_API_KEY missing'):
                engine.call_model({},1)
            network.assert_not_called()

    def test_atomic_write_rejects_rewind_and_second_identical_push(self):
        class RefAPI:
            def __init__(self):self.head='a'*40
            def request(self,method,path,data=None):
                if path=='/repos/fixture/repo':return {'full_name':'fixture/repo','node_id':'fixture-node'}
                assert path=='/graphql' and method=='POST'
                update=data['variables']['input']['updates'][0]
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
