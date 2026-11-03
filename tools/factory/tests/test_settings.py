import contextlib
import copy
import base64
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
PREFIX = "/repos/" + settings.REPOSITORY


def config(**changes):
    value = {"repository": settings.REPOSITORY, "default_branch": "testing", "config_branch": "production",
             "branches": {"schema_version": 1,
                          "validation": [{"name": "testing", "gate": "full", "kinds": ["factory", "product", "smoke"]}],
                          "production": [{"name": "production", "review": "maintainer-manual"}]},
             "maintainers": [{"login": "test-human", "id": 101}],
             "publisher_app_id": 201, "writer_app_id": 202, "environment": "factory-control",
             "workflow": ".github/workflows/factory.yml",
             "anthropic_federation": {"federation_rule_id": "fdrl_fixture"}}
    value.update(changes)
    return value


def multi():
    """Three validation gates, two production review modes and a config branch that is not the first one."""
    return config(config_branch="release", branches={"schema_version": 1, "validation": [
        {"name": "testing", "gate": "full", "kinds": ["factory", "product"]},
        {"name": "quick", "gate": "tests", "kinds": ["smoke"]},
        {"name": "scratch", "gate": "none", "kinds": []}],
        "production": [{"name": "production", "review": "initiated"},
                       {"name": "release", "review": "maintainer-manual"}]})


def rules(ruleset, kind):
    return [rule for rule in ruleset["rules"] if rule["type"] == kind]


def by_name(desired, name):
    return next(rule for rule in desired["rulesets"] if rule["name"] == name)


def report(value=None):
    value = value or config()
    desired = settings.desired_state(value, SPEC)
    current = copy.deepcopy(desired)
    for index, rule in enumerate(current["rulesets"], 1):
        rule.update(id=index, created_at="ignored metadata")
    for index, policies in enumerate(current["branch_policies"].values(), 8):
        policies[0]["id"] = index
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


def app_apis():
    apis = {}
    for role, appid in (("publisher", 201), ("writer", 202)):
        permissions = copy.deepcopy(SPEC[role + "_permissions"])
        apis[role] = FakeAPI({"/app": {"id": appid, "slug": role, "permissions": permissions},
                              f"/repos/{settings.REPOSITORY}/installation": {"id": 300 + appid, "app_id": appid,
                                  "account": {"id": 77}, "permissions": permissions, "suspended_at": None}})
    return apis


def live(value=None, private=False):
    """A repository whose live state already matches the desired state of `value`."""
    value = value or config()
    state = report(value)
    owners = {"type": "file", "content": base64.b64encode(settings.codeowners(value).encode()).decode()}
    responses = {PREFIX: {"id": 77, "full_name": settings.REPOSITORY, "default_branch": value["default_branch"], "private": private,
                          "owner": {"id": 77, "type": "User"}, "permissions": {"admin": True}},
                 "/user": {"id": 77, "plan": {"name": "pro"}},
                 "/users/test-human": {"id": 101, "login": "test-human", "type": "User"},
                 PREFIX + "/collaborators/test-human/permission": {"permission": "write"},
                 PREFIX + "/actions/permissions": SPEC["actions"],
                 PREFIX + "/actions/permissions/workflow": SPEC["workflow_permissions"],
                 PREFIX + "/actions/permissions/selected-actions": SPEC["selected_actions"],
                 PREFIX + "/rulesets?includes_parents=true": [
                     {"id": rule["id"], "name": rule["name"], "source_type": "Repository", "source": settings.REPOSITORY}
                     for rule in state["current"]["rulesets"]],
                 PREFIX + "/environments": [{"name": name} for name in state["current"]["environments"]]}
    for rule in state["current"]["rulesets"]:
        responses[PREFIX + "/rulesets/" + str(rule["id"])] = rule
    for name in settings.branches.parse(value).names:
        responses[PREFIX + "/branches/" + name] = {"name": name}
    for name, environment in state["current"]["environments"].items():
        path = PREFIX + "/environments/" + name
        responses[path] = environment
        responses[path + "/deployment-branch-policies"] = state["current"]["branch_policies"][name]
        responses[path + "/secrets"] = [{"name": secret} for secret in settings.environments(value, SPEC)[name]]
    for branch in (value["config_branch"], value["default_branch"]):
        for path in (".github/CODEOWNERS", value["workflow"], *settings.WORKFLOWS):
            responses[PREFIX + "/contents/" + path + "?ref=" + branch] = owners if path.endswith("CODEOWNERS") else {"type": "file"}
    return FakeAPI(responses)


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

    def test_rejects_other_repository_bool_id_same_app_and_broken_branch_model(self):
        for change in ({"repository": "someone/else"}, {"publisher_app_id": True},
                       {"writer_app_id": 201}, {"default_branch": "testing?ref=other"},
                       {"default_branch": "production"}, {"config_branch": "testing"},
                       {"maintainers": [{"login": "[bot]", "id": 3}]}, {"maintainers": ["test-human"]},
                       {"branches": {"schema_version": 1, "validation": [], "production": []}}):
            with self.subTest(change=change), self.assertRaises(settings.Blocked):
                settings.desired_state(config(**change), SPEC)

    def test_spec_must_describe_the_branch_model_and_a_publisher_only_promotion_environment(self):
        for change in ({"schema_version": 1}, {"promotion_environment_secrets": SPEC["environment_secrets"]},
                       {"promotion_environment": "factory-control"}, {"production_merge_methods": ["merge", "squash"]},
                       {"production_merge_methods": []},
                       {"ruleset_names": {**SPEC["ruleset_names"], "validation": "Factory validation"}},
                       {"ruleset_names": {**SPEC["ruleset_names"], "production": "{branch}"}}):
            with self.subTest(change=change), self.assertRaises(settings.Blocked):
                settings.desired_state(config(), {**SPEC, **change})

    def test_default_model_rulesets(self):
        desired = settings.desired_state(config(), SPEC)
        self.assertEqual([rule["name"] for rule in desired["rulesets"]],
                         ["Factory validation: testing", "Factory production: production", "Factory branch lifecycle"])
        validation = by_name(desired, "Factory validation: testing")
        self.assertEqual(validation["conditions"]["ref_name"]["include"], ["refs/heads/testing"])
        # Maintainers may push directly; nobody else may update a validation branch.
        self.assertEqual(validation["bypass_actors"], [{"actor_type": "User", "actor_id": 101, "bypass_mode": "always"}])
        self.assertEqual(rules(validation, "update")[0]["parameters"], {"update_allows_fetch_and_merge": False})
        checks = rules(validation, "required_status_checks")[0]["parameters"]
        self.assertTrue(checks["strict_required_status_checks_policy"])
        self.assertEqual(checks["required_status_checks"], [{"context": "factory/deterministic", "integration_id": 201},
                                                            {"context": "factory/senior-review", "integration_id": 201}])
        pr = rules(validation, "pull_request")[0]["parameters"]
        self.assertEqual(pr["required_approving_review_count"], 1)
        self.assertTrue(pr["require_code_owner_review"] and pr["dismiss_stale_reviews_on_push"])
        self.assertNotIn("allowed_merge_methods", pr)
        production = by_name(desired, "Factory production: production")
        self.assertEqual(production["bypass_actors"], [])
        self.assertEqual(rules(production, "update"), [])
        self.assertEqual(rules(production, "pull_request")[0]["parameters"]["allowed_merge_methods"], ["squash", "rebase"])
        # GitHub matches required checks per commit: the production check itself demands the AI review of this PR.
        self.assertEqual([c["context"] for c in rules(production, "required_status_checks")[0]["parameters"]["required_status_checks"]],
                         ["factory/deterministic", "factory/production/production"])
        self.assertTrue(rules(production, "required_status_checks")[0]["parameters"]["strict_required_status_checks_policy"])
        lifecycle = by_name(desired, "Factory branch lifecycle")
        self.assertEqual(lifecycle["bypass_actors"], [])
        self.assertEqual([r["type"] for r in lifecycle["rules"]], ["creation", "deletion", "non_fast_forward"])
        self.assertEqual(lifecycle["conditions"]["ref_name"]["include"],
                         ["refs/heads/testing", "refs/heads/production"] + ["refs/heads/" + n for n in settings.branches.RESERVED])
        self.assertEqual(desired["environments"], {name: {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
                                                   for name in ("factory-control", "factory-promotion")})
        self.assertEqual(desired["branch_policies"], {"factory-control": [{"name": "production", "type": "branch"}],
                                                      "factory-promotion": [{"name": "production", "type": "branch"}]})
        self.assertTrue(all(actor["actor_type"] == "User" for rule in desired["rulesets"] for actor in rule["bypass_actors"]))
        # Branch rulesets only: maintainers keep creating and deleting the merge-lock tags.
        self.assertEqual({rule["target"] for rule in desired["rulesets"]}, {"branch"})
        self.assertFalse(any("tags" in ref for rule in desired["rulesets"] for ref in rule["conditions"]["ref_name"]["include"]))

    def test_multi_branch_model_rulesets_follow_gates_and_review_modes(self):
        desired = settings.desired_state(multi(), SPEC)
        def required(name):
            found = rules(by_name(desired, name), "required_status_checks")
            return [c["context"] for c in found[0]["parameters"]["required_status_checks"]] if found else []
        self.assertEqual(len(desired["rulesets"]), 6)
        self.assertEqual(required("Factory validation: testing"), ["factory/deterministic", "factory/senior-review"])
        self.assertEqual(required("Factory validation: quick"), ["factory/deterministic"])
        self.assertEqual(required("Factory validation: scratch"), [])
        self.assertTrue(rules(by_name(desired, "Factory validation: scratch"), "pull_request"))
        self.assertEqual(required("Factory production: production"), ["factory/deterministic", "factory/production/production"])
        # A maintainer-manual review is part of the production check, never a check of its own.
        self.assertEqual(required("Factory production: release"), ["factory/deterministic", "factory/production/release"])
        for name in ("production", "release"):
            self.assertEqual(by_name(desired, "Factory production: " + name)["bypass_actors"], [])
        self.assertEqual(set(by_name(desired, "Factory branch lifecycle")["conditions"]["ref_name"]["include"]),
                         {"refs/heads/" + n for n in ("testing", "quick", "scratch", "production", "release", *settings.branches.RESERVED)})
        self.assertEqual({p[0]["name"] for p in desired["branch_policies"].values()}, {"release"})

    def test_single_maintainer_merge_setting_and_type_checks(self):
        actual = json.loads((ROOT / 'factory/config.json').read_text())
        self.assertIs(actual.get('require_second_human_review'), False)
        for candidate in ({**config(), 'require_second_human_review': False}, actual):
            with self.subTest(repository_config=candidate is actual):
                for rule in settings.desired_state(candidate, SPEC)['rulesets'][:-1]:
                    pr = rules(rule, 'pull_request')[0]['parameters']
                    self.assertEqual(pr['required_approving_review_count'], 0)
                    self.assertFalse(pr['require_code_owner_review'] or pr['require_last_push_approval'])
                    self.assertTrue(pr['required_review_thread_resolution'])
        for key in ('require_second_human_review',):
            for value in (None, 0, 1, 'false', 'true', []):
                with self.subTest(key=key, value=value), self.assertRaises(settings.Blocked):
                    settings.desired_state({**config(), key: value}, SPEC)

    def test_wif_claim_names_the_config_branch(self):
        self.assertEqual(settings.wif_claim(config()), {
            "federation_rule_id": "fdrl_fixture", "repository": settings.REPOSITORY, "ref": "refs/heads/production",
            "workflow_ref": settings.REPOSITORY + "/.github/workflows/factory.yml@refs/heads/production",
            "environment": "factory-control", "event_name": "workflow_dispatch"})
        self.assertEqual(settings.wif_claim(multi())["workflow_ref"], settings.REPOSITORY + "/.github/workflows/factory.yml@refs/heads/release")
        output = io.StringIO()
        with patch.object(settings, 'GitHub', side_effect=AssertionError('offline')), contextlib.redirect_stdout(output):
            self.assertEqual(settings.main(['wif']), 0)
        actual = json.loads((ROOT / 'factory/config.json').read_text())
        self.assertEqual(json.loads(output.getvalue())['ref'], 'refs/heads/' + actual['config_branch'])

    def test_owner_steps(self):
        state = {"missing_branches": ["quick"], "changes": [{}],
                 "missing_environment_secrets": {"factory-promotion": ["FACTORY_PUBLISHER_APP_PRIVATE_KEY"]}}
        self.assertEqual(settings.owner_steps(config(), state), [
            "Create branch quick on GitHub before apply; the lifecycle ruleset forbids creating listed names.",
            "Review `settings.py diff`, then run `settings.py apply`; environment branch policies are set before any secret is added.",
            "After `settings.py inspect` shows factory-promotion limited to branch production, add its secrets: FACTORY_PUBLISHER_APP_PRIVATE_KEY.",
            "Set the Anthropic federation rule fdrl_fixture to ref=refs/heads/production and workflow_ref="
            + settings.REPOSITORY + "/.github/workflows/factory.yml@refs/heads/production, then run "
            "`gh workflow run factory.yml --ref production -f pr=0 -f wif_smoke=true`."])
        self.assertEqual(len(settings.owner_steps(config(), {})), 1)

    def test_equal_state_is_idempotent_despite_response_metadata_and_order(self):
        for value in (config(), multi()):
            with self.subTest(branches=len(value["branches"]["validation"])):
                state = report(value)
                state["current"]["rulesets"][0]["rules"].reverse()
                state["current"]["rulesets"].reverse()
                state["current"]["actions"]["selected_actions_url"] = "ignored"
                api = FakeAPI()
                self.assertEqual(settings.diff(state, value), [])
                self.assertEqual(settings.apply(state, value, api), [])
                self.assertEqual(api.calls, [])

    def test_github_omitted_disabled_update_exception_is_idempotent(self):
        state = report()
        update = rules(state['current']['rulesets'][0], 'update')[0]
        del update['parameters']  # Actual GitHub response for the disabled exception.
        self.assertEqual(settings.diff(state, config()), [])
        update['parameters'] = {'update_allows_fetch_and_merge': True}
        self.assertEqual(len(settings.diff(state, config())), 1)
        update['parameters'] = {}
        self.assertEqual(len(settings.diff(state, config())), 1)
        state['current']['rulesets'][0]['rules'] = []
        self.assertEqual(len(settings.diff(state, config())), 1)

    def test_detects_production_bypass_actor_and_removed_app_binding(self):
        state = report()
        production = state["current"]["rulesets"][1]
        production["bypass_actors"] = [{"actor_type": "User", "actor_id": 101, "bypass_mode": "always"}]
        checks = rules(production, "required_status_checks")[0]
        del checks["parameters"]["required_status_checks"][0]["integration_id"]
        changes = settings.diff(state, config())
        self.assertEqual([(c["method"], c["endpoint"]) for c in changes], [("PUT", PREFIX + "/rulesets/2")])
        self.assertEqual(changes[0]["body"]["bypass_actors"], [])
        state = report()
        rules(state["current"]["rulesets"][1], "pull_request")[0]["parameters"]["allowed_merge_methods"] = ["merge", "squash", "rebase"]
        self.assertEqual(len(settings.diff(state, config())), 1)

    def test_retired_and_unlisted_rulesets_are_removed_after_their_replacements(self):
        state = report()
        state["current"]["rulesets"] = [
            {"id": 31, "name": "Factory mandatory review and checks", "rules": []},
            {"id": 32, "name": "Factory human PR merges only", "rules": []},
            {"id": 33, "name": "Factory validation: retired-branch", "rules": []}]
        changes = settings.diff(state, config())
        self.assertEqual([c["method"] for c in changes], ["POST", "POST", "POST", "DELETE", "DELETE", "DELETE"])
        self.assertEqual([c["endpoint"] for c in changes[3:]], [PREFIX + "/rulesets/" + str(n) for n in (31, 32, 33)])
        self.assertTrue(settings.managed(SPEC, "Factory production: anything"))
        self.assertFalse(settings.managed(SPEC, "Someone else's ruleset"))

    def test_environment_tag_with_branch_name_is_not_a_branch(self):
        state = report()
        state["current"]["branch_policies"]["factory-promotion"] = [{"id": 9, "type": "tag", "name": "production"},
                                                                    {"id": 10, "type": "branch", "name": "*"}]
        changes = settings.diff(state, config())
        self.assertEqual([c["method"] for c in changes], ["DELETE", "DELETE", "POST"])
        self.assertTrue(all("/environments/factory-promotion/" in c["endpoint"] for c in changes))
        self.assertEqual(changes[-1]["body"], {"name": "production", "type": "branch"})

    def test_missing_promotion_environment_is_created_config_branch_only(self):
        state = report()
        state["current"]["environments"]["factory-promotion"] = None
        state["current"]["branch_policies"]["factory-promotion"] = []
        changes = settings.diff(state, config())
        self.assertEqual([(c["method"], c["endpoint"]) for c in changes], [
            ("PUT", PREFIX + "/environments/factory-promotion"),
            ("POST", PREFIX + "/environments/factory-promotion/deployment-branch-policies")])
        self.assertEqual(changes[1]["body"], {"name": "production", "type": "branch"})

    def test_bot_identity_or_read_only_owner_is_rejected(self):
        repo = {"id": 77, "full_name": settings.REPOSITORY, "default_branch": "testing"}
        for profile, permission in (({"id": 101, "login": "test-human", "type": "Bot"}, "admin"),
                                    ({"id": 101, "login": "test-human", "type": "User"}, "read")):
            api = FakeAPI({"/users/test-human": profile,
                           f"/repos/{settings.REPOSITORY}/collaborators/test-human/permission": {"permission": permission}})
            self.assertTrue(settings.verify_identities(config(), api, repo))

    def test_app_proof_rejects_publisher_contents_write_and_wrong_installation(self):
        repo = {"owner": {"id": 77}}
        apis = app_apis()
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

    def test_configured_repository_inspects_ready_for_default_and_multi_branch_models(self):
        for value in (config(), multi()):
            with self.subTest(config_branch=value["config_branch"]):
                api = live(value)
                state = settings.inspect(value, SPEC, api, app_apis())
                self.assertEqual(state["blockers"], [])
                self.assertEqual(state["missing_environment_secrets"], {})
                self.assertEqual(settings.diff(state, value), [])
                self.assertEqual(state["wif_claim"]["ref"], "refs/heads/" + value["config_branch"])
                read = {endpoint for _, endpoint, _ in api.calls}
                for branch in {value["config_branch"], value["default_branch"]}:
                    self.assertIn(PREFIX + "/contents/.github/workflows/factory-promotion.yml?ref=" + branch, read)
                self.assertTrue(all(method == "GET" for method, _, _ in api.calls))

    def test_missing_branch_extra_promotion_secret_and_missing_files_block(self):
        api = live()
        del api.responses[PREFIX + "/branches/production"]
        api.responses[PREFIX + "/environments/factory-promotion/secrets"] = [
            {"name": "FACTORY_WRITER_APP_PRIVATE_KEY"}]
        del api.responses[PREFIX + "/contents/.github/workflows/factory-promotion.yml?ref=production"]
        state = settings.inspect(config(), SPEC, api, app_apis())
        self.assertEqual(state["missing_branches"], ["production"])
        self.assertEqual(state["missing_environment_secrets"], {"factory-promotion": ["FACTORY_PUBLISHER_APP_PRIVATE_KEY"]})
        self.assertIn("factory-promotion must hold only the publisher key; remove: FACTORY_WRITER_APP_PRIVATE_KEY", state["blockers"])
        self.assertIn("listed branch production does not exist; create it before apply", state["blockers"])
        self.assertIn(".github/workflows/factory-promotion.yml must be reviewed and present on production before activation", state["blockers"])
        with self.assertRaises(settings.Blocked):
            settings.apply(state, config(), api)

    def test_repository_secret_and_foreign_codeowners_block(self):
        api = live()
        api.responses[PREFIX + "/actions/secrets"] = [{"name": "FACTORY_PUBLISHER_APP_PRIVATE_KEY"}]
        api.responses[PREFIX + "/contents/.github/CODEOWNERS?ref=testing"] = {
            "type": "file", "content": base64.b64encode(b"* @someone-else\n").decode()}
        blockers = settings.inspect(config(), SPEC, api, app_apis())["blockers"]
        self.assertIn("factory credentials exist as repository secrets; move them to the config-branch environments", blockers)
        self.assertIn("CODEOWNERS on testing does not match verified human ownership", blockers)

    def test_unknown_private_plan_blocks_real_inspection_apply_path(self):
        api = live(private=True)
        api.responses["/user"] = {"id": 77, "plan": {"name": "free"}}
        state = settings.inspect(config(), SPEC, api, {})
        self.assertTrue(any("Pro plan" in reason for reason in state["blockers"]))
        with self.assertRaises(settings.Blocked):
            settings.apply(state, config(), api)
        self.assertTrue(all(method == "GET" for method, _, _ in api.calls))


if __name__ == "__main__":
    unittest.main()
