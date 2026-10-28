import copy
import base64
import importlib.util
import io
import json
import os
import sys
from pathlib import Path
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT = Path(os.environ.get('FACTORY_CANDIDATE', Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(ROOT / 'tools/factory'))
import settings
SPEC = json.loads((ROOT / "factory/github-settings.json").read_text())
_loader = importlib.util.spec_from_file_location("factory_dispatcher", ROOT / ".github/scripts/dispatch_factory.py")
dispatcher = importlib.util.module_from_spec(_loader)
_loader.loader.exec_module(dispatcher)


def config():
    return {"repository": settings.REPOSITORY, "default_branch": "main",
            "maintainers": [{"login": "test-human", "id": 101}],
            "publisher_app_id": 201, "writer_app_id": 202,
            "required_checks": settings.CHECKS, "environment": "factory-control",
            "workflow": ".github/workflows/factory.yml"}


def report():
    desired = settings.desired_state(config(), SPEC)
    current = copy.deepcopy(desired)
    for index, rule in enumerate(current["rulesets"], 1):
        rule.update(id=index, created_at="ignored metadata")
    current["branch_policies"][0]["id"] = 8
    return {"desired": desired, "current": current, "blockers": []}


class FakeAPI:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request(self, method, endpoint, body=None):
        self.calls.append((method, endpoint, body))
        return copy.deepcopy(self.responses.get(endpoint))

    def pages(self, endpoint, field=None):
        return copy.deepcopy(self.responses.get(endpoint, []))


class SettingsTests(unittest.TestCase):
    def test_app_jwt_uses_bearer_without_cli_arguments_or_subprocess_environment(self):
        def transport(request, timeout):
            self.assertEqual(request.full_url, 'https://api.github.com/app')
            self.assertEqual(request.get_method(), 'GET')
            self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-app-jwt')
            self.assertIsNone(request.data)
            return io.BytesIO(b'{"id":201}')
        with patch.dict(os.environ, {'FACTORY_PUBLISHER_APP_JWT': 'fixture-app-jwt'}), \
                patch('subprocess.run', side_effect=AssertionError('JWT must not be passed to gh')), \
                patch('urllib.request.OpenerDirector.open', side_effect=transport):
            result = settings.GitHub('FACTORY_PUBLISHER_APP_JWT').request('GET', '/app')
        self.assertEqual(result, {'id': 201})

    def test_app_inspection_refuses_mutations_and_unrelated_endpoints(self):
        with patch.dict(os.environ, {'FACTORY_PUBLISHER_APP_JWT': 'fixture-app-jwt'}), \
                patch('subprocess.run', side_effect=AssertionError('no CLI')), \
                patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no network')):
            client = settings.GitHub('FACTORY_PUBLISHER_APP_JWT')
            for method, path, body in [('POST', '/app', {}), ('GET', '/user', None),
                                       ('GET', '/repos/other/repo/installation', None)]:
                with self.subTest(method=method, path=path), self.assertRaises(settings.Blocked):
                    client.request(method, path, body)

    def test_app_http_error_closes_response_and_hides_credential_bearing_details(self):
        error = urllib.error.HTTPError('https://api.github.com/app', 401,
                                       'fixture-app-jwt', {}, io.BytesIO(b'fixture-app-jwt'))
        with patch.dict(os.environ, {'FACTORY_PUBLISHER_APP_JWT': 'fixture-app-jwt'}), \
                patch('subprocess.run', side_effect=AssertionError('no CLI')), \
                patch('urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(settings.APIError) as caught:
                settings.GitHub('FACTORY_PUBLISHER_APP_JWT').request('GET', '/app')
        self.assertEqual(caught.exception.status, 401)
        self.assertTrue(error.closed)
        self.assertNotIn('fixture-app-jwt', str(caught.exception))

    def test_app_redirect_cannot_forward_authorization(self):
        request = urllib.request.Request('https://api.github.com/app',
                                         headers={'Authorization': 'Bearer fixture-app-jwt'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            settings.NoAppRedirect().redirect_request(request, None, 302, 'redirect', {}, 'https://attacker.invalid/')
        caught.exception.close()

    def test_placeholders_refuse_network_and_activation(self):
        blank = json.loads((ROOT / "factory/config.json").read_text())
        blank.update(default_branch=None, maintainers=[], publisher_app_id=None, writer_app_id=None)
        with self.assertRaises(settings.Blocked):
            settings.desired_state(blank, SPEC)
        api = FakeAPI()
        blocked = report()
        blocked["blockers"] = ["unknown plan", "missing App identity"]
        with self.assertRaises(settings.Blocked):
            settings.apply(blocked, config(), api)
        self.assertEqual(api.calls, [])

    def test_rejects_other_repository_bool_id_and_same_app(self):
        for change in ({"repository": "someone/else"}, {"publisher_app_id": True},
                       {"writer_app_id": 201}, {"default_branch": "main?ref=other"},
                       {"maintainers": [{"login": "[bot]", "id": 3}]}):
            candidate = config()
            candidate.update(change)
            with self.subTest(change=change), self.assertRaises(settings.Blocked):
                settings.desired_state(candidate, SPEC)

    def test_quality_cannot_be_bypassed_and_update_is_human_pr_only(self):
        quality, human = settings.desired_state(config(), SPEC)["rulesets"]
        self.assertEqual(quality["bypass_actors"], [])
        self.assertEqual(human["bypass_actors"], [{"actor_type": "User", "actor_id": 101, "bypass_mode": "pull_request"}])
        checks = next(r for r in quality["rules"] if r["type"] == "required_status_checks")["parameters"]
        self.assertTrue(checks["strict_required_status_checks_policy"])
        self.assertEqual({r["integration_id"] for r in checks["required_status_checks"]}, {201})
        pr = next(r for r in quality["rules"] if r["type"] == "pull_request")["parameters"]
        self.assertEqual(pr["required_approving_review_count"], 1)
        self.assertTrue(pr["require_code_owner_review"])
        self.assertTrue(pr["dismiss_stale_reviews_on_push"])

    def test_equal_state_is_idempotent_despite_response_metadata_and_order(self):
        state = report()
        state["current"]["rulesets"][0]["rules"].reverse()
        state["current"]["actions"]["selected_actions_url"] = "ignored"
        api = FakeAPI()
        self.assertEqual(settings.diff(state, config()), [])
        self.assertEqual(settings.apply(state, config(), api), [])
        self.assertEqual(api.calls, [])

    def test_detects_added_bypass_and_removed_app_binding(self):
        state = report()
        state["current"]["rulesets"][0]["bypass_actors"] = [{"actor_type": "Integration", "actor_id": 202, "bypass_mode": "always"}]
        checks = next(r for r in state["current"]["rulesets"][0]["rules"] if r["type"] == "required_status_checks")
        del checks["parameters"]["required_status_checks"][0]["integration_id"]
        changes = settings.diff(state, config())
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["method"], "PUT")
        self.assertEqual(changes[0]["body"]["bypass_actors"], [])

    def test_environment_tag_with_main_name_is_not_a_branch(self):
        state = report()
        state["current"]["branch_policies"] = [{"id": 9, "type": "tag", "name": "main"}, {"id": 10, "type": "branch", "name": "*"}]
        changes = settings.diff(state, config())
        self.assertEqual([c["method"] for c in changes], ["DELETE", "DELETE", "POST"])
        self.assertEqual(changes[-1]["body"], {"name": "main", "type": "branch"})

    def test_bot_identity_or_read_only_owner_is_rejected(self):
        repo = {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "main"}
        for profile, permission in (({"id": 101, "login": "test-human", "type": "Bot"}, "admin"),
                                    ({"id": 101, "login": "test-human", "type": "User"}, "read")):
            api = FakeAPI({"/users/test-human": profile,
                           f"/repos/{settings.REPOSITORY}/collaborators/test-human/permission": {"permission": permission}})
            self.assertTrue(settings.verify_identities(config(), api, repo))

    def test_app_proof_rejects_publisher_contents_write_and_wrong_installation(self):
        repo = {"owner": {"id": 77}}
        apis = {}
        for role, appid in (("publisher", 201), ("writer", 202)):
            permissions = copy.deepcopy(SPEC[role + "_permissions"])
            apis[role] = FakeAPI({"/app": {"id": appid, "slug": role, "permissions": permissions},
                f"/repos/{settings.REPOSITORY}/installation": {"id": 300 + appid, "app_id": appid,
                    "account": {"id": 77}, "permissions": permissions, "suspended_at": None}})
        self.assertEqual(settings.verify_apps(config(), SPEC, repo, apis)[0], [])
        apis["publisher"].responses["/app"]["permissions"]["contents"] = "write"
        self.assertTrue(settings.verify_apps(config(), SPEC, repo, apis)[0])
        apis["writer"].responses[f"/repos/{settings.REPOSITORY}/installation"]["app_id"] = 999
        self.assertEqual(len(settings.verify_apps(config(), SPEC, repo, apis)[0]), 2)

    def test_missing_jwt_does_not_call_gh(self):
        with patch.dict(settings.os.environ, {}, clear=True), patch("subprocess.run") as run:
            with self.assertRaises(settings.Blocked):
                settings.GitHub("FACTORY_PUBLISHER_APP_JWT").request("GET", "/app")
            run.assert_not_called()

    def test_api_error_does_not_echo_stderr_or_secret(self):
        response = type("Response", (), {"returncode": 1, "stdout": "", "stderr": "ghp_SECRET HTTP 403"})()
        with patch("subprocess.run", return_value=response):
            with self.assertRaises(settings.APIError) as error:
                settings.GitHub().request("GET", "/user")
            self.assertNotIn("SECRET", str(error.exception))
            self.assertEqual(error.exception.status, 403)

    def test_unknown_private_plan_blocks_real_inspection_apply_path(self):
        prefix = "/repos/" + settings.REPOSITORY
        api = FakeAPI({prefix: {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "main", "private": True,
                               "owner": {"id": 77, "type": "User"}, "permissions": {"admin": True}},
                       "/user": {"id": 77, "plan": {"name": "free"}},
                       "/users/test-human": {"id": 101, "login": "test-human", "type": "User"},
                       prefix + "/collaborators/test-human/permission": {"permission": "write"},
                       prefix + "/actions/permissions": SPEC["actions"],
                       prefix + "/actions/permissions/workflow": SPEC["workflow_permissions"],
                       prefix + "/actions/permissions/selected-actions": SPEC["selected_actions"],
                       prefix + "/contents/.github/CODEOWNERS?ref=main": {"type": "file", "content": base64.b64encode(settings.codeowners(config()).encode()).decode()},
                       prefix + "/contents/.github/workflows/factory.yml?ref=main": {"type": "file"}})
        state = settings.inspect(config(), SPEC, api, {})
        self.assertTrue(any("Pro plan" in reason for reason in state["blockers"]))
        with self.assertRaises(settings.Blocked):
            settings.apply(state, config(), api)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))


class DispatcherTests(unittest.TestCase):
    def run_dispatcher(self, kind, event, responses, ref="refs/heads/main"):
        calls = []
        def request(method, endpoint, body=None):
            calls.append((method, endpoint, body))
            if method == "POST":
                return None
            if endpoint.endswith('/comments?per_page=100&page=1') and endpoint not in responses:
                return []
            if endpoint not in responses:
                raise AssertionError(endpoint)
            return responses[endpoint]
        environment = {"FACTORY_EVENT": kind, "FACTORY_REF": ref, "GITHUB_EVENT_PATH": "/unused/event.json"}
        with patch.dict(dispatcher.os.environ, environment, clear=True), \
             patch.object(dispatcher.Path, "read_text", side_effect=[json.dumps(config()), json.dumps(event)]), \
             patch.object(dispatcher, "api", side_effect=request):
            dispatcher.main()
        return calls

    def test_bot_comment_cannot_start_feedback_loop(self):
        event = {"issue": {"pull_request": {}, "number": 4}, "sender": {"type": "Bot", "id": 201, "login": "factory[bot]"}}
        calls = self.run_dispatcher("issue_comment", event, {dispatcher.PREFIX: {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "main"}})
        self.assertFalse(any(call[0] == "POST" for call in calls))

    def test_human_comment_is_api_verified_and_only_identifiers_forwarded(self):
        human = {"type": "User", "id": 101, "login": "test-human"}
        event = {"issue": {"pull_request": {"url": "present"}, "number": 4}, "sender": human, "comment": {"id": 55}}
        responses = {dispatcher.PREFIX: {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "main"},
                     dispatcher.PREFIX + "/issues/comments/55": {"id": 55, "user": human, "body": "NEVER FORWARD BODY", "issue_url": "https://api.github.com" + dispatcher.PREFIX + "/issues/4"},
                     dispatcher.PREFIX + "/pulls/4": {"state": "open", "base": {"ref": "main", "repo": {"id": 77}}}}
        calls = self.run_dispatcher("issue_comment", event, responses)
        post = next(call for call in calls if call[0] == "POST")
        self.assertEqual(post[2], {"ref": "main", "inputs": {"pr": "4", "feedback_kind": "issue_comment", "feedback_id": "55"}})
        self.assertNotIn("NEVER FORWARD BODY", json.dumps(calls))

    def test_only_obsolete_authenticated_runs_are_cancelled(self):
        prefix=dispatcher.PREFIX
        comment={'performed_via_github_app':{'id':201},'body':'<!-- factory-ledger:v1 -->\n{"check_id":8}'}
        check={'app':{'id':201},'status':'in_progress','external_id':f'{settings.REPOSITORY}:4:{"a"*40}:{"b"*40}:9:1'}
        responses={prefix+'/issues/4/comments?per_page=100&page=1':[comment,comment],
                   prefix+'/check-runs/8':check,
                   prefix+'/actions/runs/9':{'status':'in_progress','event':'workflow_dispatch','head_sha':'b'*40,'repository':{'full_name':settings.REPOSITORY},'workflow_id':6},
                   prefix+'/actions/workflows/6':{'path':'.github/workflows/factory.yml'}}
        calls=[]
        def request(method,path,data=None):
            calls.append((method,path));return responses.get(path)
        with patch.object(dispatcher,'api',side_effect=request):
            dispatcher.cancel_obsolete(config(),4,{'head':{'sha':'a'*40},'base':{'sha':'b'*40}})
            self.assertFalse(any(m=='POST' for m,p in calls))  # Title-only edit.
            dispatcher.cancel_obsolete(config(),4,{'head':{'sha':'c'*40},'base':{'sha':'b'*40}})
        self.assertEqual([(m,p) for m,p in calls if m=='POST'],[('POST',prefix+'/actions/runs/9/cancel')])

    def test_wrong_default_ref_and_forged_comment_author_fail(self):
        with self.assertRaises(RuntimeError):
            self.run_dispatcher("workflow_dispatch", {}, {}, ref="refs/heads/attacker")
        human = {"type": "User", "id": 101, "login": "test-human"}
        event = {"issue": {"pull_request": {"url": "present"}, "number": 4}, "sender": human, "comment": {"id": 55}}
        responses = {dispatcher.PREFIX: {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "main"},
                     dispatcher.PREFIX + "/issues/comments/55": {"id": 55, "user": {"id": 999, "type": "User", "login": "other"}}}
        with self.assertRaises(RuntimeError):
            self.run_dispatcher("issue_comment", event, responses)


if __name__ == "__main__":
    unittest.main()
