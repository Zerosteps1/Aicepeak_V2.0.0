#!/usr/bin/env python3
"""Inspect/reconcile this repository's factory controls through gh, without secrets.

No remote mutation occurs unless the explicit `apply` subcommand is invoked.
App proof uses short-lived App JWTs supplied in environment variables, never files.
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request
from urllib.parse import quote

REPOSITORY = "Zerosteps1/Aicepeak_V2.0.0"
ROOT = Path(__file__).resolve().parents[2]
CHECKS = ["factory/deterministic", "factory/senior-review"]
# During the shadow phase the senior review is published but advisory (ADR-0005).
SHADOW_CHECKS = CHECKS[:1]
API_VERSION = "2026-03-10"


class Blocked(RuntimeError):
    pass


class APIError(Blocked):
    def __init__(self, method, endpoint, status=None):
        self.status = status
        super().__init__(f"GitHub API {method} {endpoint} failed (HTTP {status or 'unknown'}); verify access and plan support")


class NoAppRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'App redirect refused', headers, fp)


class GitHub:
    def __init__(self, token_env=None):
        self.token_env = token_env

    def request(self, method, endpoint, body=None):
        if not endpoint.startswith("/") or endpoint.startswith("//"):
            raise Blocked("Only relative api.github.com endpoints are accepted")
        if self.token_env:
            return self.app_request(method, endpoint, body)
        command = ["gh", "api", "--hostname", "github.com", "--method", method,
                   "-H", "Accept: application/vnd.github+json", "-H", f"X-GitHub-Api-Version: {API_VERSION}", endpoint]
        environment = os.environ.copy()
        for name in ('FACTORY_PUBLISHER_APP_JWT', 'FACTORY_WRITER_APP_JWT'):
            environment.pop(name, None)
        if body is not None:
            command += ["--input", "-"]
        result = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                                text=True, capture_output=True, env=environment, timeout=60, check=False)
        if result.returncode:
            match = re.search(r"HTTP (\d{3})", result.stderr)
            raise APIError(method, endpoint, int(match[1]) if match else None)
        return json.loads(result.stdout) if result.stdout.strip() else None

    def app_request(self, method, endpoint, body):
        """App JWTs require Bearer; gh's GH_TOKEN transport uses the token scheme."""
        token = os.environ.get(self.token_env)
        if not token:
            raise Blocked(f"Missing {self.token_env}; cannot verify App identity and installation")
        if method != 'GET' or body is not None or endpoint not in (
                '/app', f'/repos/{REPOSITORY}/installation'):
            raise Blocked('App inspection permits only identity and target-installation GETs')
        request = urllib.request.Request('https://api.github.com' + endpoint, headers={
            'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': API_VERSION})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoAppRedirect())
        try:
            with opener.open(request, timeout=60) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise Blocked('App response exceeds inspection limit')
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise Blocked('App inspection expected a JSON object')
            return result
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            raise APIError(method, endpoint, status) from None
        except (OSError, ValueError):
            raise APIError(method, endpoint) from None

    def pages(self, endpoint, field=None):
        values = []
        for page in range(1, 101):
            separator = "&" if "?" in endpoint else "?"
            response = self.request("GET", f"{endpoint}{separator}per_page=100&page={page}")
            chunk = response[field] if field else response
            if not isinstance(chunk, list):
                raise Blocked(f"Unexpected list response for {endpoint}")
            values.extend(chunk)
            if len(chunk) < 100:
                return values
        raise Blocked(f"Pagination limit reached for {endpoint}; refusing an incomplete inspection")


def positive_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def config_blockers(config):
    errors = []
    if config.get("repository") != REPOSITORY:
        errors.append("repository must be the exact authorized target " + REPOSITORY)
    branch = config.get("default_branch")
    if not isinstance(branch, str) or not branch or re.search(r"[\s~^:?*\[\\]", branch) or ".." in branch or "@{" in branch or branch.startswith(('-', '/')) or branch.endswith(('/', '.', '.lock')):
        errors.append("default_branch is missing or invalid; verify it from repository metadata")
    maintainers = config.get("maintainers")
    if not isinstance(maintainers, list) or not maintainers:
        errors.append("maintainers must contain verified human login/id objects")
        maintainers = []
    seen = set()
    for maintainer in maintainers:
        if not isinstance(maintainer, dict) or not positive_id(maintainer.get("id")) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", str(maintainer.get("login", ""))):
            errors.append("each maintainer needs a real numeric id and GitHub login")
            continue
        key = maintainer["login"].lower()
        if key in seen:
            errors.append("duplicate maintainer login")
        seen.add(key)
    for key in ("publisher_app_id", "writer_app_id"):
        if not positive_id(config.get(key)):
            errors.append(f"{key} is missing or invalid")
    if positive_id(config.get("publisher_app_id")) and config.get("publisher_app_id") == config.get("writer_app_id"):
        errors.append("publisher and writer must be different GitHub Apps")
    if config.get("required_checks") not in (SHADOW_CHECKS, CHECKS):
        errors.append("required_checks must be the deterministic check (shadow phase) or both factory App checks")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(config.get("environment", ""))):
        errors.append("environment must be an explicit simple name")
    if config.get("workflow") != ".github/workflows/factory.yml":
        errors.append("workflow must be .github/workflows/factory.yml")
    return errors


def desired_state(config, spec):
    errors = config_blockers(config)
    if spec.get("schema_version") != 1 or spec.get("repository") != REPOSITORY or spec.get("required_checks") != config.get("required_checks"):
        errors.append("unsupported or mismatched github-settings.json")
    if errors:
        raise Blocked("; ".join(errors))
    conditions = {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    quality = {
        "name": spec["quality_ruleset_name"], "target": "branch", "enforcement": "active", "bypass_actors": [],
        "conditions": conditions,
        "rules": [
            {"type": "deletion"}, {"type": "non_fast_forward"},
            {"type": "pull_request", "parameters": {
                "dismiss_stale_reviews_on_push": True, "require_code_owner_review": True,
                "require_last_push_approval": True, "required_approving_review_count": 1,
                "required_review_thread_resolution": True}},
            {"type": "required_status_checks", "parameters": {
                "do_not_enforce_on_create": False, "strict_required_status_checks_policy": True,
                "required_status_checks": [{"context": name, "integration_id": config["publisher_app_id"]} for name in config["required_checks"]]}}
        ]}
    human = {
        "name": spec["human_ruleset_name"], "target": "branch", "enforcement": "active",
        "conditions": conditions,
        "bypass_actors": [{"actor_type": "User", "actor_id": m["id"], "bypass_mode": "pull_request"} for m in config["maintainers"]],
        "rules": [{"type": "update", "parameters": {"update_allows_fetch_and_merge": False}}]}
    return {"rulesets": [quality, human], "environment": {
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}},
        "branch_policies": [{"name": config["default_branch"], "type": "branch"}],
        "actions": copy.deepcopy(spec["actions"]), "selected_actions": copy.deepcopy(spec["selected_actions"]),
        "workflow_permissions": copy.deepcopy(spec["workflow_permissions"])}


def codeowners(config):
    owners = " ".join("@" + item["login"] for item in config["maintainers"])
    return "# Human ownership; generated after GitHub identity verification.\n* " + owners + "\n"


def get_optional(api, endpoint):
    try:
        return api.request("GET", endpoint)
    except APIError as exc:
        if exc.status == 404:
            return None
        raise


def verify_identities(config, api, repository):
    blockers = []
    for maintainer in config["maintainers"]:
        user = api.request("GET", "/users/" + quote(maintainer["login"], safe=""))
        if user.get("type") != "User" or user.get("id") != maintainer["id"] or user.get("login", "").lower() != maintainer["login"].lower():
            blockers.append("maintainer identity is not the configured human: " + maintainer["login"])
            continue
        permission = api.request("GET", f"/repos/{REPOSITORY}/collaborators/{quote(maintainer['login'], safe='')}/permission")
        if permission.get("permission") not in ("admin", "write", "maintain"):
            blockers.append("maintainer needs repository write access: " + maintainer["login"])
    if repository.get("full_name", "").lower() != REPOSITORY.lower() or not positive_id(repository.get("id")):
        blockers.append("API repository identity mismatch")
    if repository.get("default_branch") != config["default_branch"]:
        blockers.append("configured default_branch differs from live repository")
    return blockers


def verify_apps(config, spec, repository, app_apis):
    blockers = []
    evidence = {}
    for role in ("publisher", "writer"):
        try:
            api = app_apis[role]
            app = api.request("GET", "/app")
            installation = api.request("GET", f"/repos/{REPOSITORY}/installation")
            if app.get("id") != config[role + "_app_id"] or installation.get("app_id") != app.get("id"):
                raise Blocked(role + " App ID mismatch")
            if installation.get("account", {}).get("id") != repository.get("owner", {}).get("id") or installation.get("suspended_at"):
                raise Blocked(role + " App installation is missing, suspended, or belongs to another account")
            expected = spec[role + "_permissions"]
            for source in (app, installation):
                actual = {k: v for k, v in source.get("permissions", {}).items() if v not in ("none", None)}
                if actual != expected:
                    raise Blocked(role + " App permission split differs from desired exact permissions")
            if not positive_id(installation.get("id")) or not app.get("slug"):
                raise Blocked(role + " App identity response is incomplete")
            evidence[role] = {"app_id": app["id"], "slug": app["slug"], "installation_id": installation["id"]}
        except (Blocked, KeyError) as exc:
            blockers.append(str(exc) if isinstance(exc, Blocked) else role + " App proof unavailable")
    return blockers, evidence


def inspect(config, spec, api, app_apis):
    desired = desired_state(config, spec)
    prefix = f"/repos/{REPOSITORY}"
    repository = api.request("GET", prefix)
    blockers = verify_identities(config, api, repository)
    if not repository.get("permissions", {}).get("admin"):
        blockers.append("authenticated gh identity needs repository Administration access")
    owner = repository.get("owner", {})
    user = api.request("GET", "/user")
    plan = user.get("plan", {}).get("name") if user.get("id") == owner.get("id") else None
    if owner.get("type") != "User":
        blockers.append("this configuration expects a personal repository; organization policy needs explicit review")
    if repository.get("private") and str(plan).lower() != "pro":
        blockers.append("private personal repository requires verified owner GitHub Pro plan; plan is missing/unsupported")
    apps_blocked, apps = verify_apps(config, spec, repository, app_apis)
    blockers.extend(apps_blocked)
    # Successful list calls plus verified Pro establish feature support; 403 is never treated as empty state.
    rules = api.pages(prefix + "/rulesets?includes_parents=true")
    rulesets = []
    for rule in rules:
        if rule.get("name") in (spec["quality_ruleset_name"], spec["human_ruleset_name"]):
            if rule.get("source_type") != "Repository" or rule.get("source", "").lower() != REPOSITORY.lower():
                blockers.append("managed ruleset name collides with an inherited ruleset")
                continue
            rulesets.append(api.request("GET", prefix + "/rulesets/" + str(rule["id"])))
    names = [r["name"] for r in rulesets]
    if len(names) != len(set(names)):
        blockers.append("duplicate managed ruleset names; resolve explicitly")
    environments = api.pages(prefix + "/environments", "environments")
    envname = quote(config["environment"], safe="")
    environment = None
    policies = []
    secret_names = []
    if any(env.get("name") == config["environment"] for env in environments):
        environment = api.request("GET", prefix + "/environments/" + envname)
        if (environment.get("deployment_branch_policy") or {}).get("custom_branch_policies"):
            policies = api.pages(prefix + "/environments/" + envname + "/deployment-branch-policies", "branch_policies")
        secret_names = [s["name"] for s in api.pages(prefix + "/environments/" + envname + "/secrets", "secrets")]
    repo_secrets = api.pages(prefix + "/actions/secrets", "secrets")
    sensitive_names = set(spec["environment_secrets"] + spec.get("optional_environment_secrets", []))
    if any(secret["name"] in sensitive_names for secret in repo_secrets):
        blockers.append("factory credentials exist as repository secrets; move them to the default-branch environment")
    current = {"rulesets": rulesets, "environment": environment, "branch_policies": policies,
               "actions": api.request("GET", prefix + "/actions/permissions"),
               "workflow_permissions": api.request("GET", prefix + "/actions/permissions/workflow")}
    current["selected_actions"] = (api.request("GET", prefix + "/actions/permissions/selected-actions")
                                   if current["actions"].get("allowed_actions") == "selected" else {})
    for path in (".github/CODEOWNERS", config["workflow"]):
        remote = get_optional(api, prefix + "/contents/" + path + "?ref=" + quote(config["default_branch"], safe=""))
        if not remote or remote.get("type") != "file":
            blockers.append(path + " must be reviewed and present on the default branch before activation")
        elif path.endswith("CODEOWNERS"):
            try:
                text = base64.b64decode(remote["content"]).decode()
            except (ValueError, KeyError, UnicodeError):
                text = ""
            if text != codeowners(config):
                blockers.append("default-branch CODEOWNERS does not match verified human ownership")
    return {"repository": {"id": repository["id"], "full_name": repository["full_name"],
                           "default_branch": repository["default_branch"], "private": repository["private"]},
            "plan": plan, "apps": apps, "blockers": blockers, "desired": desired, "current": current,
            "missing_environment_secrets": sorted(set(spec["environment_secrets"]) - set(secret_names))}


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
    return value


def project(actual, expected):
    """Drop response metadata, but preserve extra security-relevant rule/actor entries."""
    if isinstance(expected, dict):
        actual = actual if isinstance(actual, dict) else {}
        # GitHub omits this whole optional parameter object when its sole
        # exception is disabled. Absence of the update rule still remains drift.
        if (actual.get('type') == expected.get('type') == 'update'
                and 'parameters' not in actual
                and expected.get('parameters') == {'update_allows_fetch_and_merge': False}):
            actual = {**actual, 'parameters': {'update_allows_fetch_and_merge': False}}
        return {key: project(actual.get(key), val) for key, val in expected.items()}
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return actual
        if expected and isinstance(expected[0], dict):
            projected = []
            for item in actual:
                template = next((entry for entry in expected if entry.get("type") == item.get("type")), expected[0])
                projected.append(project(item, template))
            return projected
        return actual
    return actual


def same(actual, expected):
    return canonical(project(actual, expected)) == canonical(expected)


def diff(report, config):
    current, desired = report["current"], report["desired"]
    prefix = f"/repos/{REPOSITORY}"
    changes = []
    def change(method, endpoint, body, reason):
        changes.append({"method": method, "endpoint": endpoint, "body": body, "reason": reason})
    envpath = prefix + "/environments/" + quote(config["environment"], safe="")
    if not same(current["environment"], desired["environment"]):
        change("PUT", envpath, desired["environment"], "restrict credential environment")
    # Remove broad policies before adding the exact branch. A transition can deny all, never permit extra refs.
    for policy in current["branch_policies"]:
        if not any(same(policy, wanted) for wanted in desired["branch_policies"]):
            change("DELETE", envpath + "/deployment-branch-policies/" + str(policy["id"]), None, "remove extra environment branch/tag policy")
    for policy in desired["branch_policies"]:
        if not any(same(actual, policy) for actual in current["branch_policies"]):
            change("POST", envpath + "/deployment-branch-policies", policy, "allow default branch only")
    for key, suffix in (("actions", ""), ("selected_actions", "/selected-actions"), ("workflow_permissions", "/workflow")):
        if not same(current[key], desired[key]):
            change("PUT", prefix + "/actions/permissions" + suffix, desired[key], "reconcile " + key)
    for rule in desired["rulesets"]:
        actual = next((r for r in current["rulesets"] if r["name"] == rule["name"]), None)
        if not same(actual, rule):
            change("PUT" if actual else "POST", prefix + "/rulesets" + ("/" + str(actual["id"]) if actual else ""), rule, "reconcile " + rule["name"])
    return changes


def apply(report, config, api):
    if report["blockers"]:
        raise Blocked("Activation refused: " + "; ".join(report["blockers"]))
    changes = diff(report, config)
    for change in changes:
        api.request(change["method"], change["endpoint"], change["body"])
    return changes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inspect", "diff", "apply", "codeowners"))
    parser.add_argument("--config", type=Path, default=ROOT / "factory/config.json")
    parser.add_argument("--spec", type=Path, default=ROOT / "factory/github-settings.json")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        spec = json.loads(args.spec.read_text())
        # Fail before network access when placeholders remain; no inferred identity fills.
        desired_state(config, spec)
        api = GitHub()
        if args.command == "codeowners":
            repository = api.request("GET", f"/repos/{REPOSITORY}")
            errors = verify_identities(config, api, repository)
            if errors:
                raise Blocked("; ".join(errors))
            destination = ROOT / ".github/CODEOWNERS"
            destination.write_text(codeowners(config))
            print(json.dumps({"written": str(destination), "remote_changes": False}))
            return 0
        app_apis = {role: GitHub("FACTORY_" + role.upper() + "_APP_JWT") for role in ("publisher", "writer")}
        report = inspect(config, spec, api, app_apis)
        changes = diff(report, config)
        if args.command == "apply":
            apply(report, config, api)
            report = inspect(config, spec, api, app_apis)
            drift = diff(report, config)
            if drift or report["blockers"]:
                raise Blocked("Post-apply verification failed; inspect live state before retrying")
            report["applied_count"] = len(changes)
        report["changes"] = changes if args.command != "apply" else []
        report["configuration_ready"] = not report["blockers"] and not report["missing_environment_secrets"] and not report["changes"]
        if args.command == "diff":
            report.pop("current")
            report.pop("desired")
        print(json.dumps(report, indent=2))
        return 2 if report["blockers"] else 0
    except (Blocked, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"blocked": True, "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
