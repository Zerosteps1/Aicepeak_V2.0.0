"""Boundary regressions with real Git/stdlib and GitHub mocked only at transport."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(os.environ.get('FACTORY_CANDIDATE',Path(__file__).resolve().parents[3]))
sys.path.insert(0,str(ROOT/'tools/factory'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import branch_fixture
import branches
import bypass
import contracts
import engine
import issue_fixture
import issues
import verify
from contracts import Blocked

HEAD, POLICY, BASE = 'a'*40, 'b'*40, 'e'*40  # PR head, config branch tip (production), target tip (testing)
ENV = {'GITHUB_SHA':POLICY,'GITHUB_REF':'refs/heads/production','GITHUB_RUN_ID':'1','GITHUB_RUN_ATTEMPT':'1','FACTORY_RETRY':'false'}
POSTED = '2026-11-01T10:00:00Z'  # when the human comments were posted; heads are committed a minute earlier
DISPATCHER = {'type':'Bot','id':41898282,'login':'github-actions[bot]'}


def job(workflow, name):
    """One job's text of a workflow, wherever the job sits."""
    rest=workflow.split(f'\n  {name}:\n',1)[1]
    return next((rest[:i] for i in range(len(rest)) if rest.startswith('\n  ',i) and rest[i+3:i+4].isalnum()),rest)


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
        self.tips={'production':POLICY,'testing':BASE}
        self.foreign=[]
        self.texts=[]
        self.committed='2026-11-01T09:59:00Z'
        self.pr={'number':1,'state':'open','draft':False,'changed_files':1,
                 'head':{'sha':HEAD,'ref':'ftrutschnig/TEST','repo':{'full_name':'fixture/repo'}},
                 'base':{'ref':'testing','sha':BASE},
                 'body':'```factory-handoff\n'+json.dumps({'runner':'claude','task':'docs/work/TEST.md','owner':'test-human'})+'\n```'}

    def comment(self,body,user=None,pr=1):
        """A human issue comment as the API returns it; other PRs' comments are not listed on PR 1."""
        ident=self.next_comment=getattr(self,'next_comment',1000)+1
        (self.comments if pr==1 else self.foreign).append({'id':ident,'body':body,'user':user or {'type':'User','id':1,'login':'test-human'},
                              'issue_url':f'https://api.github.com/repos/fixture/repo/issues/{pr}',
                              'html_url':f'https://github.com/fixture/repo/pull/{pr}#issuecomment-{ident}','created_at':POSTED,'updated_at':POSTED})
        return ident

    def request(self,method,path,data=None):
        self.calls.append((method,path,data))
        if method=='GET':
            if path.endswith('/check-runs/'+path.rsplit('/',1)[-1]) and '/check-runs/' in path:
                return copy.deepcopy(self.checks[int(path.rsplit('/',1)[-1])])
            if path=='/repos/fixture/repo':return {'full_name':'fixture/repo','default_branch':'testing'}
            if path.endswith('/pulls/1'):return copy.deepcopy(self.pr)
            if '/git/ref/heads/' in path:
                name=path.rsplit('/heads/',1)[1]
                if name not in self.tips:raise Blocked('GitHub GET ref: HTTP 404')
                return {'object':{'sha':self.tips[name],'type':'commit'}}
            if '/issues/comments/' in path:
                return copy.deepcopy(next(c for c in self.comments+self.foreign if c.get('id')==int(path.rsplit('/',1)[-1])))
            if '/compare/' in path:return copy.deepcopy(self.compare)
            if '/commits/' in path and '/check-runs' not in path:
                return {'sha':path.rsplit('/',1)[-1],'commit':{'committer':{'date':self.committed}}}
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
        if '/check-runs?' in path:
            sha=path.split('/commits/',1)[1].split('/',1)[0]
            return [copy.deepcopy(c) for c in self.checks.values() if c['head_sha']==sha and c['name']=='factory/deterministic']
        return []

    def text(self,*args):
        self.texts.append(args)
        return '```factory-task\n'+json.dumps(self.task)+'\n```'


class IssueTransport(Transport):
    """The PR transport plus a work-order issue #57 on the same faked repository."""
    def __init__(self, config):
        super().__init__(config)
        self.hub = issue_fixture.IssueHub(config)

    def request(self,method,path,data=None):
        if self.hub.owns(path):
            return self.hub.request(method,path,data)
        return super().request(method,path,data)

    def pages(self,path,field=None):
        if self.hub.owns(path):
            return self.hub.pages(path,field)
        return super().pages(path,field)


class EngineBoundaries(unittest.TestCase):
    def setUp(self):
        # Config PRs change the candidate's branch model; every other value comes from the candidate.
        self.config=branch_fixture.load(ROOT)
        self.config.update(repository='fixture/repo',publisher_app_id=7,
                           maintainers=[{'id':1,'login':'test-human'}])
        self.transport=Transport(self.config)
        self.snapshot={'repository':'fixture/repo','pr':1,'head_sha':HEAD,'base_ref':'testing',
                       'base_sha':BASE,'policy_sha':POLICY,'run_id':1,'run_attempt':1}
        self.env=patch.dict(os.environ,ENV)
        self.env.start();self.addCleanup(self.env.stop)

    def capture_snapshot(self):
        captured={}
        with patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'emit',side_effect=lambda name,value:captured.update({name:value})):
            engine.snapshot_stage(argparse.Namespace(pr=1,feedback_kind='',feedback_id=0),self.config)
        return captured['snapshot']

    def senior_checks(self):
        return [c for c in self.transport.checks.values() if c['name']=='factory/senior-review']

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

    def test_an_issue_work_order_is_pinned_and_any_later_edit_makes_the_run_stale(self):
        self.transport=IssueTransport(self.config)
        self.transport.hub.issue()
        self.transport.hub.approve(paths=('example.txt',))
        self.transport.pr['body']='```factory-handoff\n'+json.dumps({'runner':'claude','task':'#57','owner':'test-human'})+'\n```'
        snapshot=self.capture_snapshot()
        order=issues.approved(self.transport.hub,self.config,57)
        self.assertEqual(snapshot['task'],{'status':'approved','kind':'factory','allowed_paths':['example.txt']})
        self.assertEqual(snapshot['task_pin'],issues.pin_of(order))
        self.assertEqual(self.transport.texts,[])  # no work-order file was read
        engine.unchanged(self.transport,snapshot,self.config)
        self.assertEqual(issues.text_for(self.transport,self.config,'fixture/repo','#57',POLICY,snapshot['task_pin']),order['text'])
        issue=self.transport.hub.issues[57]
        issue['body']+='\nAC-3: more scope.'
        with self.assertRaisesRegex(Blocked,'edited after its approval'):
            engine.unchanged(self.transport,snapshot,self.config)
        self.transport.hub.approve(paths=('example.txt',))  # accepted again: another work order for this run
        with self.assertRaisesRegex(Blocked,'changed since this run'):
            engine.unchanged(self.transport,snapshot,self.config)

    def test_an_unapproved_or_out_of_scope_issue_blocks_the_snapshot(self):
        self.transport=IssueTransport(self.config)
        self.transport.hub.issue()
        self.transport.pr['body']='```factory-handoff\n'+json.dumps({'runner':'claude','task':'#57','owner':'test-human'})+'\n```'
        with self.assertRaisesRegex(Blocked,'not an approved work order'):
            self.capture_snapshot()
        self.transport.hub.approve(paths=('docs/',))
        with self.assertRaisesRegex(Blocked,'PR outside approved task'):
            self.capture_snapshot()
        self.assertEqual(self.senior_checks(),[])

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

    def test_issue_runs_never_start_a_pr_job_and_pr_runs_never_start_an_issue_job(self):
        workflow=(ROOT/'.github/workflows/factory.yml').read_text()
        condition=lambda name:re.search(r'\n    if: (.*)\n',job(workflow,name))[1]
        for name in ('wif-smoke','snapshot','review-coordinate','correction','review-request','bypass'):
            self.assertIn("inputs.issue == '0'",condition(name),name)
        for name in ('issue-review','issue-accept'):
            self.assertIn("inputs.pr == '0'",condition(name),name)
            self.assertIn("inputs.issue != '0'",condition(name),name)
        self.assertEqual(condition('issue-publish'),"always() && needs.issue-review.result != 'skipped'")
        # Jobs that re-check a pinned issue with the workflow token may read issues; none may write them.
        for name in ('tests','author','push','issue-review'):
            self.assertIn('issues: read',job(workflow,name),name)
        self.assertNotIn('issues: write',workflow)

    def test_author_job_federates_instead_of_holding_an_anthropic_key(self):
        workflow=(ROOT/'.github/workflows/factory.yml').read_text()
        self.assertIn('id-token: write',job(workflow,'author'))
        self.assertIn('id-token: write',job(workflow,'wif-smoke'))
        # The issue reviewer federates too, without any App key; the jobs holding the publisher key never federate.
        self.assertIn('id-token: write',job(workflow,'issue-review'))
        self.assertNotIn('APP_PRIVATE_KEY',job(workflow,'issue-review'))
        for name in ('issue-publish','issue-accept'):
            self.assertNotIn('id-token',job(workflow,name))
        self.assertEqual(workflow.count('id-token: write'),3)
        self.assertNotIn('ANTHROPIC_API_KEY',workflow)
        settings=json.loads((ROOT/'factory/github-settings.json').read_text())
        self.assertNotIn('ANTHROPIC_API_KEY',settings['environment_secrets']+settings['optional_environment_secrets'])

    def publish(self,tests_ok=True):
        snapshot=self.capture_snapshot()
        tests={'repository':'fixture/repo','head_sha':snapshot['head_sha'],'policy_sha':POLICY,'run_id':snapshot['run_id'],'ok':tests_ok,'exit_code':0 if tests_ok else 1,'summary':'trusted output'}
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

    def test_head_without_current_target_tip_is_not_published_as_tested_merge_state(self):
        # GitHub moves pr.base.sha on a push that never reached the head (PRs #4/#5): base equality is not inclusion.
        self.transport.compare={'status':'diverged','behind_by':2}
        snapshot=self.capture_snapshot()
        tests={'repository':'fixture/repo','head_sha':HEAD,'policy_sha':POLICY,'run_id':1,'ok':True,'exit_code':0,'summary':'trusted output'}
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'TESTS_JSON':json.dumps(tests),'TEST_JOB_RESULT':'success'}
        with patch.dict(os.environ,env), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'verify_run'):
            engine.publish_stage(self.config)
        # Inclusion is checked against the target branch tip, not the config tip.
        self.assertIn(('GET','/repos/fixture/repo/compare/'+BASE+'...'+HEAD+'?per_page=1',None),self.transport.calls)
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
            engine.contains_base(self.transport,'fixture/repo','testing','a'*40)

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
        tests={'repository':'fixture/repo','head_sha':HEAD,'policy_sha':POLICY,'run_id':1,'ok':True,'exit_code':0,'summary':'trusted output'}
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
        self.assertEqual((reservation['name'],reservation['external_id']),('factory/author-reservation',contracts.binding(snapshot)))
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
            for name in ('test_contracts.py','branch_fixture.py'):
                for tree in (trusted,candidate):shutil.copy2(ROOT/'tools/factory/tests'/name,tree/'tools/factory/tests'/name)
            (candidate/'factory/config.json').write_text(branch_fixture.text(ROOT))
            shutil.copy2(ROOT/'factory/review.schema.json',candidate/'factory/review.schema.json')
            shutil.copy2(ROOT/'tools/factory/branches.py',candidate/'tools/factory/branches.py')
            code=(ROOT/'tools/factory/contracts.py').read_text()
            # The intact candidate passes the trusted suite: the failure below comes from the broken validation alone.
            (candidate/'tools/factory/contracts.py').write_text(code)
            verify.unit_tests(candidate,trusted)
            code=code.replace('def validate_review(review, schema, snapshot):','def validate_review(review, schema, snapshot):\n    return "pass"')
            (candidate/'tools/factory/contracts.py').write_text(code)
            (candidate/'unittest.py').write_text('raise SystemExit(0)\n')
            (candidate/'sitecustomize.py').write_text('raise SystemExit(0)\n')
            with self.assertRaisesRegex(ValueError,'FAILED'):
                verify.unit_tests(candidate,trusted)

    # FACTORY-008: config branch, validation gates, production mode, /review and /bypass.

    def test_every_stage_runs_only_on_the_config_branch(self):
        self.config['automatic_correction']=True
        stages={'snapshot':lambda:engine.snapshot_stage(argparse.Namespace(pr=1,feedback_kind='',feedback_id=0),self.config),
                'test':lambda:engine.test_stage(self.config),'publish':lambda:engine.publish_stage(self.config),
                'correction':lambda:engine.correction_stage(argparse.Namespace(pr=1,check_id=1),self.config),
                'author':lambda:engine.author_stage(self.config,argparse.Namespace(patch='patch.diff')),
                'push':lambda:engine.push_stage(self.config,argparse.Namespace(patch='patch.diff')),
                'author-failed':lambda:engine.author_failed_stage(self.config),
                'review-request':lambda:engine.review_request_stage(argparse.Namespace(pr=1,comment_id=5,head=HEAD),self.config),
                'bypass':lambda:engine.bypass_stage(argparse.Namespace(pr=1,comment_id=5,head=HEAD),self.config)}
        for ref in ('refs/heads/testing','refs/heads/ftrutschnig/TEST','refs/heads/production/x','production',None):
            for name,stage in stages.items():
                with self.subTest(ref=ref,stage=name), patch.dict(os.environ,{}), \
                        patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'GitHub',return_value=self.transport):
                    if ref is None:os.environ.pop('GITHUB_REF')
                    else:os.environ['GITHUB_REF']=ref
                    with self.assertRaisesRegex(Blocked,'factory jobs must run on the config branch'):stage()
        self.assertEqual(self.transport.calls,[])

    def test_command_line_names_the_new_stages(self):
        for stage,function in (('review-request','review_request_stage'),('bypass','bypass_stage')):
            with self.subTest(stage=stage), patch.object(engine,function) as called, \
                    patch.object(sys,'argv',['engine.py',stage,'--pr','3','--comment-id','42','--head',HEAD]):
                self.assertEqual(engine.main(),0)
            args=called.call_args.args[0]
            self.assertEqual((args.pr,args.comment_id,args.head),(3,42,HEAD))

    def test_snapshot_runs_the_config_tip_and_binds_the_target_branch(self):
        snapshot=self.capture_snapshot()
        self.assertEqual((snapshot['policy_sha'],snapshot['base_sha'],snapshot['base_ref'],snapshot['mode'],snapshot['gate'],snapshot['review_request']),
                         (POLICY,BASE,'testing','validation','full',None))
        self.assertEqual(self.transport.checks[snapshot['check_id']]['external_id'],f'fixture/repo:1:{HEAD}:{POLICY}:testing:1:1')
        # The work order is read at the config tip, never from the target branch.
        self.assertEqual(self.transport.texts,[('fixture/repo','docs/work/TEST.md',POLICY)])
        with patch.dict(os.environ,{'GITHUB_SHA':BASE}),self.assertRaisesRegex(Blocked,'current config branch tip'):
            self.capture_snapshot()
        self.transport.pr['base']['sha']='c'*40
        with self.assertRaisesRegex(Blocked,'current tip of its target branch'):
            self.capture_snapshot()

    def test_moved_config_tip_target_tip_or_target_branch_make_a_snapshot_stale(self):
        snapshot=self.capture_snapshot()
        engine.current(self.transport,snapshot,self.config)
        cases=[('stale policy',lambda t:t.tips.update(production='c'*40)),
               ('stale base',lambda t:t.tips.update(testing='c'*40)),
               ('stale base',lambda t:t.pr['base'].update(sha='c'*40)),
               ('target branch changed',lambda t:t.pr['base'].update(ref='production',sha=POLICY)),
               ('stale head',lambda t:t.pr['head'].update(sha='c'*40))]
        for message,change in cases:
            self.transport.tips={'production':POLICY,'testing':BASE}
            self.transport.pr['base']={'ref':'testing','sha':BASE};self.transport.pr['head']['sha']=HEAD
            change(self.transport)
            with self.subTest(message=message),self.assertRaisesRegex(Blocked,message):
                engine.current(self.transport,snapshot,self.config)

    def test_new_target_tip_with_the_same_head_gets_a_fresh_run(self):
        first=self.capture_snapshot()
        self.transport.tips['testing']='c'*40;self.transport.pr['base']['sha']='c'*40
        second=self.capture_snapshot()
        self.assertNotEqual(first['reservation']['key'],second['reservation']['key'])
        self.assertEqual(len(self.senior_checks()),2)

    def tests_gate(self):
        self.config.update(branches.with_validation(self.config,'quick','tests',['smoke']))
        self.transport.tips['quick']='c'*40
        self.transport.pr['base']={'ref':'quick','sha':'c'*40}

    def test_tests_gate_publishes_only_deterministic_and_never_reviews_or_corrects(self):
        self.tests_gate()
        snapshot,_=self.publish()
        self.assertEqual((snapshot['mode'],snapshot['gate'],snapshot['check_id'],snapshot['reservation'],snapshot['feedback_digest']),
                         ('validation','tests',None,None,None))
        self.assertEqual([(c['name'],c['conclusion']) for c in self.transport.checks.values()],[('factory/deterministic','success')])
        self.assertFalse(any(c['body'].startswith('<!-- factory-ledger') for c in self.transport.comments))
        self.assertIn('not part of the `tests` gate',self.transport.comments[-1]['body'])
        self.assertNotIn('local_review.py',self.transport.comments[-1]['body'])
        self.assertEqual(self.transport.labels,set())
        # Human comments do not bind a deterministic-only run.
        self.transport.comment('Looks fine')
        engine.current(self.transport,snapshot,self.config)
        # Even an authenticated changes_requested receipt cannot start a correction.
        review={**{k:snapshot[k] for k in ('repository','pr','head_sha','base_sha','policy_sha','run_id','run_attempt')},'model':'gpt-6-astra','effort':'high',
                'scope':['example.txt'],'evidence':[],'limitations':[],'complete':True,'outcome':'changes_requested','summary':'s',
                'findings':[{'id':'F-1','kind':'defect','confidence':'high','priority':'P1','file':'example.txt','line':1,'impact':'i','evidence':'e','requirement':'r','minimal_fix':'m','verification':'v'}]}
        forged=self.transport.request('POST','/repos/fixture/repo/check-runs',{'name':'factory/senior-review','head_sha':HEAD,'status':'completed',
            'external_id':contracts.binding(snapshot),'details_url':engine.run_url(snapshot),
            'output':{'text':json.dumps({'phase':'completed','snapshot':snapshot,'review':review})}})
        self.config['automatic_correction']=True
        self.transport.runs[2]={'triggering_actor':{'type':'User','id':1}}
        with self.assertRaisesRegex(Blocked,'full validation'):
            self.correction(forged['id'])
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'AUTHOR_JSON':json.dumps({'enabled':True,'run_id':2})}
        with patch.dict(os.environ,env),self.assertRaisesRegex(Blocked,'full validation'):
            engine.verified_author_input(self.config)

    def test_failed_tests_gate_hands_back_to_the_author_without_review(self):
        self.tests_gate()
        self.publish(tests_ok=False)
        self.assertEqual(self.senior_checks(),[])
        self.assertEqual(self.transport.labels,{'needs-author-action'})

    def test_gate_none_unlisted_bases_and_listed_heads_are_refused(self):
        self.config.update(branches.with_validation(self.config,'frozen','none',[]))
        self.transport.tips.update(frozen='c'*40,other='d'*40)
        for base,message in (('frozen','gate none'),('other','not a listed branch')):
            self.transport.pr['base']={'ref':base,'sha':self.transport.tips[base]}
            with self.subTest(base=base),self.assertRaisesRegex(Blocked,message):
                self.capture_snapshot()
        self.transport.pr['base']={'ref':'testing','sha':BASE}
        for head in ('testing','production','frozen'):
            self.transport.pr['head']['ref']=head
            with self.subTest(head=head),self.assertRaisesRegex(Blocked,'feature branch'):
                self.capture_snapshot()
        self.assertEqual(self.transport.checks,{})

    def promotion(self):
        self.transport.pr['base']={'ref':'production','sha':POLICY}
        self.transport.pr['head']['ref']='testing'
        self.transport.pr['body']='Promote testing'
        self.transport.files=[{'filename':'src/app.py','status':'modified'},{'filename':'.github/workflows/x.yml','status':'added'}]
        self.transport.pr['changed_files']=2

    def test_every_production_head_gets_deterministic_tests_without_work_order_or_review(self):
        self.promotion()
        snapshot,_=self.publish()
        self.assertEqual((snapshot['mode'],snapshot['gate'],snapshot['handoff'],snapshot['task'],snapshot['check_id'],snapshot['feedback_digest'],snapshot['base_ref']),
                         ('production','tests',None,None,None,None,'production'))
        self.assertEqual((snapshot['files'],snapshot['control_changed']),(['src/app.py','.github/workflows/x.yml'],True))
        self.assertEqual([(c['name'],c['conclusion'],c['external_id']) for c in self.transport.checks.values()],
                         [('factory/deterministic','success',contracts.binding(snapshot))])
        self.assertIn('comments `/review`; `factory/production/production` needs it to pass',self.transport.comments[-1]['body'])
        self.assertEqual(self.transport.texts,[])
        self.assertEqual(self.transport.labels,set())
        self.transport.pr['head']['sha']='c'*40
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish()
        self.assertEqual(self.senior_checks(),[])
        self.assertEqual([c['head_sha'] for c in self.transport.checks.values()],[HEAD,'c'*40])
        self.config['branches']['production'][0]['review']='no'
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'3'}):
            self.publish()
        self.assertIn('not used for production',self.transport.comments[-1]['body'])

    def test_promotion_tests_any_complete_diff_but_a_review_keeps_the_file_limit(self):
        self.promotion()
        many=self.config['limits']['max_changed_files']+1
        self.transport.files=[{'filename':f'src/m{i}.py','status':'modified'} for i in range(many)]
        self.transport.pr['changed_files']=many
        snapshot,_=self.publish()
        self.assertEqual(len(snapshot['files']),many)
        comment=self.transport.comment('/review')
        with self.assertRaisesRegex(Blocked,'oversized'):
            self.review_request(comment)
        self.transport.pr['changed_files']=many+1
        with self.assertRaisesRegex(Blocked,'incomplete'):
            self.capture_snapshot()

    def review_request(self,comment_id,run_id=5,head=None):
        """The head defaults to the one the dispatcher saw: the PR's current head."""
        captured={}
        with patch.dict(os.environ,{'GITHUB_RUN_ID':str(run_id)}), patch.object(engine,'installation',return_value=self.transport), \
                patch.object(engine,'verify_run') as run, patch.object(engine,'emit',side_effect=lambda name,value:captured.update({name:value})):
            engine.review_request_stage(argparse.Namespace(pr=1,comment_id=comment_id,head=self.transport.pr['head']['sha'] if head is None else head),self.config)
        return captured['snapshot'],run

    def test_review_request_reserves_the_senior_review_once_for_the_current_head(self):
        self.promotion()
        self.publish()
        comment=self.transport.comment('/review please check the migration')
        snapshot,run=self.review_request(comment)
        self.assertEqual((snapshot['mode'],snapshot['review_request'],snapshot['handoff'],snapshot['task'],snapshot['run_id']),
                         ('production',comment,None,None,5))
        self.assertIsNotNone(snapshot['feedback_digest'])
        check=self.transport.checks[snapshot['check_id']]
        record=json.loads(check['output']['text'])
        self.assertEqual((check['name'],check['status'],check['external_id'],record['phase'],record['snapshot']),
                         ('factory/senior-review','in_progress',contracts.binding(snapshot),'awaiting_review',snapshot))
        self.assertEqual({k:record['tests'][k] for k in ('repository','head_sha','policy_sha','run_id','ok','exit_code')},
                         {'repository':'fixture/repo','head_sha':HEAD,'policy_sha':POLICY,'run_id':1,'ok':True,'exit_code':0})
        # The test evidence is the pipeline run that published factory/deterministic for this head.
        self.assertEqual(run.call_args.kwargs,{'run_id':1})
        self.assertEqual(run.call_args.args[3],{'Snapshot':['success'],self.config['test_job']:['success'],'Publish gates':['success']})
        self.assertEqual(self.transport.labels,{'awaiting-senior-review'})
        self.assertIn('local_review.py --pr 1',self.transport.comments[-1]['body'])
        with self.assertRaisesRegex(Blocked,'duplicate'):
            self.review_request(comment,run_id=6)
        # A new head gets its tests but never restarts the review.
        self.transport.pr['head']['sha']='c'*40
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'7'}):
            self.publish()
        self.assertEqual([c['head_sha'] for c in self.senior_checks()],[HEAD])
        with self.assertRaisesRegex(Blocked,'stale head'):
            engine.unchanged(self.transport,snapshot,self.config)

    def test_review_request_accepts_only_a_maintainer_review_comment_on_an_open_production_pr(self):
        self.promotion()
        self.publish()
        cases=[(self.transport.comment('/review',user={'type':'User','id':2,'login':'someone'}),'maintainer'),
               (self.transport.comment('/review',user={'type':'User','id':1,'login':'impostor'}),'maintainer'),
               (self.transport.comment('/review',user={'type':'Bot','id':1,'login':'test-human'}),'maintainer'),
               (self.transport.comment('/review',pr=2),'another PR'),
               (self.transport.comment('please /review'),'not a /review command'),
               (self.transport.comment('/reviewed already'),'not a /review command'),(0,'invalid')]
        for ident,message in cases:
            with self.subTest(message=message,ident=ident),self.assertRaisesRegex(Blocked,message):
                self.review_request(ident)
        # GitHub never lists a maintainer ID under another login; drop the forged item before real snapshots.
        self.transport.comments=[c for c in self.transport.comments if c['user'].get('login')!='impostor']
        comment=self.transport.comment('/review')
        self.config['branches']['production'][0]['review']='no'
        with self.assertRaisesRegex(Blocked,'review mode no'):
            self.review_request(comment)
        self.config['branches']['production'][0]['review']='initiated'
        self.transport.pr['state']='closed'
        with self.assertRaisesRegex(Blocked,'open PRs into a production branch'):
            self.review_request(comment)
        self.transport.pr['state']='open'
        self.transport.pr['draft']=True
        with self.assertRaisesRegex(Blocked,'draft'):
            self.review_request(comment)
        self.transport.pr.update(draft=False,base={'ref':'testing','sha':BASE})
        with self.assertRaisesRegex(Blocked,'production branch'):
            self.review_request(comment)
        self.assertEqual(self.senior_checks(),[])
        self.transport.pr['base']={'ref':'production','sha':POLICY}
        self.review_request(comment)
        self.assertEqual(len(self.senior_checks()),1)

    def test_review_request_needs_passed_tests_of_this_head_and_config_tip(self):
        self.promotion()
        comment=self.transport.comment('/review')
        with self.assertRaisesRegex(Blocked,'has not run'):
            self.review_request(comment)
        self.publish(tests_ok=False)
        with self.assertRaisesRegex(Blocked,'did not pass'):
            self.review_request(comment)
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish()
        moved='c'*40  # production is also the config branch: a merge moves both tips
        self.transport.tips['production']=moved;self.transport.pr['base']['sha']=moved
        with patch.dict(os.environ,{'GITHUB_SHA':moved}),self.assertRaisesRegex(Blocked,'has not run'):
            self.review_request(comment)
        self.assertEqual(self.senior_checks(),[])

    def bypass(self,body=None,ident=None,run_id=9,head=None,env=None):
        """The dispatcher (github-actions[bot]) starts the run with the head it saw: the PR's current head."""
        ident=ident or self.transport.comment(body)
        self.transport.runs.setdefault(run_id,{'id':run_id,'triggering_actor':DISPATCHER})
        with patch.dict(os.environ,{'GITHUB_RUN_ID':str(run_id),**(env or {})}), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'emit'):
            engine.bypass_stage(argparse.Namespace(pr=1,comment_id=ident,head=self.transport.pr['head']['sha'] if head is None else head),self.config)
        return ident

    def bypasses(self):
        return [c for c in self.transport.checks.values() if c['output']['title'].startswith('Bypassed by')]

    def test_bypass_passes_the_required_checks_of_exactly_the_current_head(self):
        ident=self.bypass('/bypass  runner outage,\n see incident 12 ')
        bound={'repository':'fixture/repo','pr':1,'head_sha':HEAD,'policy_sha':POLICY,'base_ref':'testing','run_id':9,'run_attempt':1}
        checks=self.bypasses()
        self.assertEqual([c['name'] for c in checks],['factory/deterministic','factory/senior-review'])
        for check in checks:
            self.assertEqual((check['head_sha'],check['status'],check['conclusion'],check['app']['id'],check['external_id'],check['details_url']),
                             (HEAD,'completed','success',7,contracts.binding(bound),'https://github.com/fixture/repo/actions/runs/9'))
            self.assertEqual(check['external_id'].split(':'),['fixture/repo','1',HEAD,POLICY,'testing','9','1'])
            self.assertEqual((check['output']['title'],check['output']['summary']),('Bypassed by test-human','Reason: runner outage, see incident 12'))
            self.assertEqual(json.loads(check['output']['text']),
                             {'bypass':{'login':'test-human','id':1,'comment_id':ident,'reason':'runner outage, see incident 12'}})
        self.assertIn('bypassed by test-human',self.transport.comments[-1]['body'])
        self.assertFalse(any(c['body'].startswith('<!-- factory-ledger') for c in self.transport.comments))

    def test_bypass_follows_the_gate_and_never_passes_the_production_check(self):
        self.tests_gate()
        self.bypass('/bypass flaky runner')
        self.assertEqual([c['name'] for c in self.bypasses()],['factory/deterministic'])
        self.transport.checks.clear()
        self.promotion()
        # maintainer-manual: the production check itself demands the AI review, so only deterministic is bypassed here.
        self.bypass('/bypass urgent promotion')
        self.assertEqual([c['name'] for c in self.bypasses()],['factory/deterministic'])
        self.transport.checks.clear()
        self.config['branches']['production'][0]['review']='initiated'
        self.bypass('/bypass urgent promotion')
        self.assertEqual([c['name'] for c in self.bypasses()],['factory/deterministic'])
        self.assertFalse(any(c['name'].startswith('factory/production/') for c in self.transport.checks.values()))

    def test_bypass_needs_a_maintainer_a_reason_and_a_non_work_order_pr(self):
        cases=[(self.transport.comment('/bypass reason',user={'type':'User','id':2,'login':'someone'}),'maintainer'),
               (self.transport.comment('/bypass'),'reason'),(self.transport.comment('/bypass   \n '),'reason'),
               (self.transport.comment('/bypass '+'x'*501),'reason'),(self.transport.comment('/bypassing it'),'not a /bypass command'),
               (self.transport.comment('/review'),'not a /bypass command'),(self.transport.comment('/bypass ok',pr=2),'another PR')]
        for ident,message in cases:
            with self.subTest(message=message),self.assertRaisesRegex(Blocked,message):
                self.bypass(ident=ident)
        self.assertEqual(self.bypasses(),[])
        self.bypass('/bypass '+'x'*500)
        self.assertEqual(len(self.bypasses()),2)
        self.transport.checks.clear()
        self.promotion()
        self.transport.pr['head']['ref']='ftrutschnig/workorders'
        self.transport.files=[{'filename':'docs/work/FACTORY-009.md','status':'added'},{'filename':'factory/config.json','status':'modified'}]
        with self.assertRaisesRegex(Blocked,'cannot be bypassed'):
            self.bypass('/bypass approvals missing')
        self.transport.files=[{'filename':'src/app.py','status':'renamed','previous_filename':'docs/work/OLD.md'},
                              {'filename':'docs/work/sub/X.md','status':'added'}]
        self.bypass('/bypass not a work-order PR')  # type (c): its production check still fails
        self.assertEqual(len(self.bypasses()),1)
        self.transport.checks.clear()
        self.config.update(branches.with_validation(self.config,'frozen','none',[]))
        self.transport.tips.update(frozen='c'*40,other='d'*40)
        for base in ('frozen','other'):
            self.transport.pr['base']={'ref':base,'sha':self.transport.tips[base]}
            with self.subTest(base=base),self.assertRaisesRegex(Blocked,'no factory checks to bypass'):
                self.bypass('/bypass whatever')
        self.transport.pr.update(state='closed',base={'ref':'testing','sha':BASE})
        with self.assertRaisesRegex(Blocked,'open PRs'):
            self.bypass('/bypass whatever')
        self.assertEqual(self.bypasses(),[])

    def test_bypass_publishes_nothing_for_a_moved_head_or_tip(self):
        original=self.transport.request
        def moving(method,path,data=None):
            value=original(method,path,data)
            if method=='GET' and path.endswith('/pulls/1'):self.transport.pr['head']['sha']='c'*40
            return value
        with patch.object(self.transport,'request',side_effect=moving),self.assertRaisesRegex(Blocked,'stale head'):
            self.bypass('/bypass outage')
        self.transport.pr['head']['sha']=HEAD
        with patch.dict(os.environ,{'GITHUB_SHA':'c'*40}),self.assertRaisesRegex(Blocked,'stale policy'):
            self.bypass('/bypass outage')
        self.transport.tips['testing']='c'*40
        with self.assertRaisesRegex(Blocked,'stale base'):
            self.bypass('/bypass outage')
        self.assertEqual(self.bypasses(),[])

    def test_corrections_push_only_to_unlisted_feature_branches(self):
        for branch in ('testing','production'):
            with self.subTest(branch=branch),self.assertRaisesRegex(Blocked,'listed branch'):
                engine.correction_branch(self.config,{'head':{'ref':branch}})
        self.assertEqual(engine.correction_branch(self.config,{'head':{'ref':'ftrutschnig/TEST'}}),'ftrutschnig/TEST')
        for unsafe in ('a/../b','a b'):
            with self.subTest(unsafe=unsafe),self.assertRaisesRegex(Blocked,'unsafe'):
                engine.correction_branch(self.config,{'head':{'ref':unsafe}})

    def test_legacy_six_field_review_binding_never_authorizes_a_correction(self):
        self.config['automatic_correction']=True
        snapshot=self.reviewed()
        check=self.transport.checks[snapshot['check_id']]
        check['external_id']=':'.join(['fixture/repo','1',HEAD,POLICY,'1','1'])
        with self.assertRaisesRegex(Blocked,'binding'):
            self.correction(snapshot['check_id'])
        record=json.loads(check['output']['text'])
        record['snapshot']={k:v for k,v in snapshot.items() if k!='base_ref'}
        check['output']['text']=json.dumps(record)
        with self.assertRaisesRegex(Blocked,'legacy'):
            self.correction(snapshot['check_id'])

    def test_verify_fails_on_any_branch_model_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=branch_fixture.load(ROOT)
            config['config_branch']='testing'
            config['branches']['validation'][0]['kinds']=['factory']
            (Path(tmp)/'factory').mkdir()
            (Path(tmp)/'factory/config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'invalid branch configuration: kind product is routed to no validation branch.*config_branch must be a production branch'):
                verify.structural(Path(tmp),ROOT)

    def test_owned_trusted_modules_name_no_fixed_branch(self):
        for name in ('engine','github_api','local_review','local_review_queue','verify'):
            source=(ROOT/'tools/factory'/(name+'.py')).read_text()
            with self.subTest(module=name):
                for retired in branches.RESERVED[:2]:
                    # Branch names come from the config; a function name or script guard is not one.
                    self.assertNotRegex(source.replace(f'def {retired}(','').replace(f'{retired}()',''),rf'\b{retired}\b')
                self.assertNotIn("config['required_checks']",source)
                self.assertNotIn('engine.bind(',source)

    # Review fixes: commands bind their head (D3), a moved config tip is no author action (D2), a bypass survives a re-run (D4).

    def edit(self,ident,when='2026-11-01T10:05:00Z'):
        next(c for c in self.transport.comments if c.get('id')==ident)['updated_at']=when

    def test_edited_review_or_bypass_comment_is_refused(self):
        self.promotion()
        self.publish()
        review,bypass=self.transport.comment('/review'),self.transport.comment('/bypass outage')
        self.edit(review);self.edit(bypass)
        with self.assertRaisesRegex(Blocked,'the command comment was edited; post a new comment'):
            self.review_request(review)
        with self.assertRaisesRegex(Blocked,'the command comment was edited; post a new comment'):
            self.bypass(ident=bypass)
        self.assertEqual((self.senior_checks(),self.bypasses()),([],[]))

    def test_review_or_bypass_for_another_head_is_refused(self):
        self.promotion()
        self.publish()
        review,bypass=self.transport.comment('/review'),self.transport.comment('/bypass outage')
        for head in ('c'*40,'',HEAD[:12],HEAD.upper()):
            with self.subTest(head=head):
                with self.assertRaisesRegex(Blocked,'the PR head changed after the command; post a new `/review`'):
                    self.review_request(review,head=head)
                with self.assertRaisesRegex(Blocked,'the PR head changed after the command; post a new `/bypass`'):
                    self.bypass(ident=bypass,head=head)
        # The head moved between the dispatcher's read and the snapshot: the reservation is refused too.
        original=self.transport.request
        def moving(method,path,data=None):
            value=original(method,path,data)
            if method=='GET' and path.endswith('/pulls/1'):self.transport.pr['head']['sha']='c'*40
            return value
        with patch.object(self.transport,'request',side_effect=moving),self.assertRaisesRegex(Blocked,'head changed after the command'):
            self.review_request(review,head=HEAD)
        self.assertEqual((self.senior_checks(),self.bypasses()),([],[]))

    def test_bypass_of_a_head_committed_after_the_comment_is_refused(self):
        ident=self.transport.comment('/bypass outage')
        self.transport.committed='2026-11-01T10:00:01Z'
        with self.assertRaisesRegex(Blocked,'the head is newer than the `/bypass` comment; post a new `/bypass`'):
            self.bypass(ident=ident)
        self.assertEqual(self.bypasses(),[])
        self.transport.committed=POSTED
        self.bypass(ident=ident)
        self.assertEqual(len(self.bypasses()),2)

    def test_bypass_run_started_by_another_account_is_refused(self):
        self.config['maintainers'].append({'id':2,'login':'other-human'})
        ident=self.transport.comment('/bypass outage')
        for number,actor in enumerate(({'type':'User','id':2,'login':'other-human'},{'type':'User','id':3,'login':'stranger'},
                                       {'type':'User','id':1,'login':'impostor'},{'type':'Bot','id':5,'login':'factory-publisher[bot]'},
                                       {**DISPATCHER,'type':'User'}),start=20):
            self.transport.runs[number]={'id':number,'triggering_actor':actor}
            with self.subTest(actor=actor['login']),self.assertRaisesRegex(Blocked,'started by the dispatcher or by the author of the comment'):
                self.bypass(ident=ident,run_id=number)
        self.assertEqual(self.bypasses(),[])
        self.transport.runs[30]={'id':30,'triggering_actor':{'type':'User','id':1,'login':'test-human'}}
        self.bypass(ident=ident,run_id=30)  # the comment's own author dispatched it
        self.bypass(ident=ident,run_id=31)  # the dispatcher
        self.assertEqual(len(self.bypasses()),4)

    def test_bypass_rerun_attempt_is_refused(self):
        with self.assertRaisesRegex(Blocked,'dispatch a fresh /bypass'):
            self.bypass('/bypass outage',env={'GITHUB_RUN_ATTEMPT':'2'})
        self.assertEqual(self.bypasses(),[])

    def publish_after(self,change,tests_ok=False):
        """Publish a snapshot after `change` moved GitHub state during its run."""
        snapshot=self.capture_snapshot()
        change(self.transport)
        tests={'repository':'fixture/repo','head_sha':HEAD,'policy_sha':POLICY,'run_id':1,'ok':tests_ok,'exit_code':0 if tests_ok else 1,'summary':'trusted output'}
        env={'SNAPSHOT_JSON':json.dumps(snapshot),'TESTS_JSON':json.dumps(tests),'TEST_JOB_RESULT':'success' if tests_ok else 'failure'}
        with patch.dict(os.environ,env), patch.object(engine,'installation',return_value=self.transport), patch.object(engine,'verify_run'):
            engine.publish_stage(self.config)
        return snapshot

    def test_moved_config_tip_adds_no_needs_author_action(self):
        for gate in ('full','tests'):
            with self.subTest(gate=gate):
                self.setUp()
                if gate=='tests':self.tests_gate()
                self.publish_after(lambda t:t.tips.update(production='c'*40),tests_ok=gate=='full')
                deterministic=[c for c in self.transport.checks.values() if c['name']=='factory/deterministic']
                self.assertEqual([c['conclusion'] for c in deterministic],['failure'])
                self.assertIn('the config branch moved during this run; a fresh run is dispatched automatically',self.transport.comments[-1]['body'])
                self.assertNotIn('needs-author-action',self.transport.labels)
                self.assertFalse(any(c['body'].startswith('needs-author-action') for c in self.transport.comments))

    def deterministic(self):
        return [(c['conclusion'],c['output']['title']) for c in self.transport.checks.values() if c['name']=='factory/deterministic']

    def test_same_head_rerun_keeps_a_deterministic_bypass(self):
        for kind in ('tests','production'):
            with self.subTest(kind=kind):
                self.setUp()
                self.tests_gate() if kind=='tests' else self.promotion()
                self.publish(tests_ok=False)
                self.assertEqual(self.transport.labels,set() if kind=='production' else {'needs-author-action'})
                ident=self.bypass('/bypass known flaky runner')
                self.assertEqual(self.transport.labels,set())
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
                    self.publish(tests_ok=False)  # e.g. a title edit re-runs the same head
                self.assertEqual(self.deterministic(),[('failure','Deterministic checks'),('success','Bypassed by test-human')])
                self.assertIn('deterministic `failure` (not published: the `/bypass` by test-human stays for this head)',
                              self.transport.comments[-1]['body'])
                self.assertEqual(self.transport.labels,set())
                # An edited bypass comment no longer holds; the failure is published again.
                self.edit(ident)
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'3'}):
                    self.publish(tests_ok=False)
                self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))
                self.assertEqual(self.transport.labels,set() if kind=='production' else {'needs-author-action'})

    def test_a_bypass_does_not_carry_to_another_head_config_tip_or_a_full_gate(self):
        self.tests_gate()
        self.bypass('/bypass known flaky runner')
        moved='c'*40
        self.transport.pr['head']['sha']=moved
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish(tests_ok=False)
        self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))
        self.transport.pr['head']['sha']=HEAD
        self.transport.tips['production']=moved
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'3','GITHUB_SHA':moved}):
            self.publish(tests_ok=False)
        self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))
        # A full gate re-reviews every run; its bypass is not kept by a re-run.
        self.setUp()
        self.bypass('/bypass known flaky runner')
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish(tests_ok=False)
        self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))

    # Round 2: a bypass voided by a config move asks for a new /bypass (R2), a hidden bypass is published again (R3),
    # work-order/config PRs are classified like the production check does (R4, R5).

    def to_release(self):
        """A promotion of testing into release, a second production branch that is not the config branch."""
        self.promotion()
        self.config.update(branches.with_production(self.config,'release','no'))
        self.transport.tips['release']='d'*40
        self.transport.pr['base']={'ref':'release','sha':'d'*40}

    def test_a_bypass_under_an_earlier_config_tip_asks_for_a_new_bypass_not_the_author(self):
        for kind in ('tests','production'):
            with self.subTest(kind=kind):
                self.setUp()
                self.tests_gate() if kind=='tests' else self.to_release()
                self.bypass('/bypass known flaky runner')
                moved='9'*40  # a work-order PR merged into the config branch
                self.transport.tips['production']=moved
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'2','GITHUB_SHA':moved}):
                    self.publish(tests_ok=False)
                self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))
                self.assertIn('deterministic `failure` (the `/bypass` by test-human was for an earlier config tip; post a new `/bypass`)',
                              self.transport.comments[-1]['body'])
                self.assertEqual(self.transport.labels,set())
                self.assertFalse(any(c['body'].startswith('needs-author-action') for c in self.transport.comments))
        # Only a bypass for this head, PR and target counts, even under an earlier config tip.
        self.setUp()
        self.tests_gate()
        self.bypass('/bypass known flaky runner')
        self.transport.pr['head']['sha']='f'*40
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish(tests_ok=False)
        self.assertEqual(self.transport.labels,{'needs-author-action'})

    def test_an_earlier_tip_bypass_counts_only_for_this_pr_and_target(self):
        for field,value in ((1,'2'),(4,'release')):  # binding repo:pr:head:policy:base_ref:run:attempt
            with self.subTest(field=field):
                self.setUp()
                self.tests_gate()
                self.bypass('/bypass known flaky runner')
                for check in self.transport.checks.values():
                    if check['output'].get('title')=='Bypassed by test-human':
                        fields=check['external_id'].split(':');fields[field]=value;check['external_id']=':'.join(fields)
                moved='9'*40
                self.transport.tips['production']=moved
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'2','GITHUB_SHA':moved}):
                    self.publish(tests_ok=False)
                self.assertNotIn('earlier config tip',self.transport.comments[-1]['body'])
                self.assertEqual(self.transport.labels,{'needs-author-action'})

    def test_a_stale_rerun_never_republishes_a_kept_bypass(self):
        self.tests_gate()
        self.bypass('/bypass known flaky runner')
        with patch.object(bypass,'kept_run',side_effect=Blocked('GitHub GET: HTTP 502')), patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            self.publish(tests_ok=False)  # a failure now hides the bypass
        count=len([c for c in self.deterministic() if c[1]=='Bypassed by test-human'])
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'3'}):
            self.publish_after(lambda t:t.tips.update(production='c'*40))  # the config tip moved during the run
        self.assertEqual(len([c for c in self.deterministic() if c[1]=='Bypassed by test-human']),count)
        self.assertIn('stale policy',self.transport.comments[-1]['body'])

    def test_a_kept_bypass_is_published_again_when_a_newer_failure_hides_it(self):
        for kind in ('tests','production'):
            with self.subTest(kind=kind):
                self.setUp()
                self.tests_gate() if kind=='tests' else self.promotion()
                ident=self.bypass('/bypass known flaky runner')
                record={'title':'Bypassed by test-human','summary':'Reason: known flaky runner',
                        'text':json.dumps({'bypass':{'login':'test-human','id':1,'comment_id':ident,'reason':'known flaky runner'}})}
                # A GitHub error during the bypass lookup of a same-head re-run published a failure after the bypass.
                with patch.object(bypass,'kept_run',side_effect=Blocked('GitHub GET: HTTP 502')), patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
                    self.publish(tests_ok=False)
                self.assertEqual(self.deterministic()[-1],('failure','Deterministic checks'))
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'3'}):
                    snapshot,_=self.publish(tests_ok=False)
                newest=max((c for c in self.transport.checks.values() if c['name']=='factory/deterministic'),key=lambda c:c['id'])
                self.assertEqual((newest['conclusion'],newest['external_id'],newest['output']),('success',contracts.binding(snapshot),record))
                self.assertIn('stays for this head; it was published again as the newest run',self.transport.comments[-1]['body'])
                self.assertEqual(self.transport.labels,set())
                # Another PR on the same commit published a failure: the next re-run puts the bypass on top again.
                other=self.transport.request('POST','/repos/fixture/repo/check-runs',{'name':'factory/deterministic','head_sha':HEAD,
                    'status':'completed','conclusion':'failure','external_id':contracts.binding({**snapshot,'pr':2,'run_id':4}),
                    'output':{'title':engine.DETERMINISTIC_TITLE}})
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'5'}):
                    snapshot,_=self.publish(tests_ok=False)
                newest=max((c for c in self.transport.checks.values() if c['name']=='factory/deterministic'),key=lambda c:c['id'])
                self.assertGreater(newest['id'],other['id'])
                self.assertEqual((newest['conclusion'],newest['external_id'].split(':')[5],newest['output']),('success','5',record))
                # While the bypass is the newest run, a re-run publishes nothing.
                count=len(self.deterministic())
                with patch.dict(os.environ,{'GITHUB_RUN_ID':'6'}):
                    self.publish(tests_ok=False)
                self.assertEqual(len(self.deterministic()),count)
                self.assertNotIn('published again',self.transport.comments[-1]['body'])
                # A failed lookup of the newest run publishes the bypass again rather than risk leaving a failure on top.
                real,looked=bypass.head_runs,[]
                def flaky(*args):
                    looked.append(args)
                    if len(looked)==2:raise Blocked('GitHub GET: HTTP 502')
                    return real(*args)
                with patch.object(bypass,'head_runs',side_effect=flaky), patch.dict(os.environ,{'GITHUB_RUN_ID':'7'}):
                    self.publish(tests_ok=False)
                self.assertEqual(len(looked),2)
                self.assertEqual(self.deterministic()[count:],[('success','Bypassed by test-human')])
                self.assertIn('published again as the newest run',self.transport.comments[-1]['body'])

    def test_bypass_clears_the_author_handoff_of_a_validation_pr(self):
        for gate in ('full','tests'):
            with self.subTest(gate=gate):
                self.setUp()
                if gate=='tests':self.tests_gate()
                self.publish(tests_ok=False)
                self.assertEqual(self.transport.labels,{'needs-author-action'})
                self.bypass('/bypass known flaky runner')
                self.assertEqual(self.transport.labels,set())

    def work_orders(self):
        """A work-order/config PR into production: a feature branch changing only work orders and factory/config.json."""
        self.promotion()
        self.transport.pr['head']['ref']='ftrutschnig/workorders'
        self.transport.files=[{'filename':'docs/work/FACTORY-009.md','status':'added'},{'filename':'factory/config.json','status':'modified'}]

    def test_work_order_and_config_prs_get_no_ai_review(self):
        self.work_orders()
        snapshot,_=self.publish()
        self.assertEqual(snapshot['production_kind'],'work-order')
        body=self.transport.comments[-1]['body']
        self.assertIn('senior review not used for work-order and config PRs: maintainer approvals decide them',body)
        self.assertNotIn('`/review`',body)
        comment=self.transport.comment('/review')
        for files in (self.transport.files,[{'filename':'docs/work/NEW.md','status':'renamed','previous_filename':'docs/work/OLD.md'}]):
            self.transport.files=files;self.transport.pr['changed_files']=len(files)
            with self.subTest(files=files),self.assertRaisesRegex(Blocked,'^work-order and config PRs need no AI review: maintainer approvals decide them$'):
                self.review_request(comment)
        self.assertEqual(self.senior_checks(),[])
        # A promotion is reviewed like every promotion, even when its diff holds only work orders and config.
        self.transport.pr['head']['ref']='testing'
        self.transport.files=[{'filename':'docs/work/FACTORY-009.md','status':'modified'},{'filename':'factory/config.json','status':'modified'}]
        self.transport.pr['changed_files']=2
        with patch.dict(os.environ,{'GITHUB_RUN_ID':'2'}):
            snapshot,_=self.publish()
        self.assertEqual(snapshot['production_kind'],'promotion')
        self.assertIn('comments `/review`; `factory/production/production` needs it to pass',self.transport.comments[-1]['body'])
        self.review_request(comment)
        self.assertEqual(len(self.senior_checks()),1)
        # Any other PR into production keeps the review text of its target.
        self.setUp()
        self.promotion()
        self.transport.pr['head']['ref']='ftrutschnig/feature'
        snapshot,_=self.publish()
        self.assertEqual(snapshot['production_kind'],'other')
        self.assertIn('`factory/production/production` needs it to pass',self.transport.comments[-1]['body'])

    def test_production_prs_are_classified_once_for_the_pipeline_and_the_production_check(self):
        import promotion
        self.assertIs(promotion.production_kind,bypass.production_kind)
        model=branches.parse(self.config)
        def pr(ref,repo='fixture/repo'):return {'head':{'ref':ref,'repo':{'full_name':repo} if repo else None}}
        work=[{'filename':'docs/work/A.md'},{'filename':'factory/config.json'}]
        self.assertEqual(bypass.production_kind(model,'fixture/repo',pr('testing'),lambda:self.fail('a promotion never reads its files')),'promotion')
        cases=[(pr('ftrutschnig/x'),work,'work-order'),(pr('testing','someone/fork'),work,'work-order'),(pr('testing',None),work,'work-order'),
               (pr('production'),work,'work-order'),(pr('ftrutschnig/x'),[{'filename':'docs/work/B.md','previous_filename':'docs/work/A.md'}],'work-order'),
               (pr('ftrutschnig/x'),[{'filename':'docs/work/B.md','previous_filename':'src/app.py'}],'other'),
               (pr('ftrutschnig/x'),[*work,{'filename':'README.md'}],'other'),(pr('ftrutschnig/x'),[],'other'),
               (pr('testing','someone/fork'),[{'filename':'src/app.py'}],'other')]
        for value,files,kind in cases:
            with self.subTest(value=value,files=files):
                self.assertEqual(bypass.production_kind(model,'fixture/repo',value,lambda:files),kind)

    def test_a_promotion_whose_diff_holds_only_work_orders_can_be_bypassed(self):
        self.promotion()
        self.transport.files=[{'filename':'docs/work/FACTORY-009.md','status':'modified'},{'filename':'factory/config.json','status':'modified'}]
        self.bypass('/bypass runner outage')
        self.assertEqual([c['name'] for c in self.bypasses()],['factory/deterministic'])
        # A feature branch with the same diff is a work-order/config PR: maintainer approvals decide it.
        self.transport.checks.clear()
        self.transport.pr['head']['ref']='ftrutschnig/workorders'
        with self.assertRaisesRegex(Blocked,'cannot be bypassed; they need maintainer approvals'):
            self.bypass('/bypass runner outage')
        self.assertEqual(self.bypasses(),[])

    def test_production_comment_names_the_review_mode(self):
        self.promotion()
        self.config['branches']['production'][0]['review']='initiated'
        self.publish()
        self.assertIn('starts when a maintainer comments `/review` (advisory)',self.transport.comments[-1]['body'])
        self.assertNotIn('factory/production/',self.transport.comments[-1]['body'])

if __name__=='__main__':unittest.main()
