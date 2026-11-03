#!/usr/bin/env python3
"""Inspect/reconcile this repository's factory controls through gh, without secrets.

Rulesets follow the branch model of factory/config.json: one per validation branch (checks of its
gate, maintainers may push), one per production branch (PR only, no bypass actors) and one lifecycle
ruleset for listed and reserved names. Both factory environments admit only the config branch.
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

import branches

REPOSITORY = "Zerosteps1/Aicepeak_V2.0.0"
ROOT = Path(__file__).resolve().parents[2]
API_VERSION = "2026-03-10"
WORKFLOWS = (".github/workflows/factory-dispatch.yml", ".github/workflows/factory-promotion.yml")


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
    if all(isinstance(maintainer, dict) for maintainer in maintainers):
        # Names, gates, review modes, routing, default and config branch; required checks follow from them.
        errors += branches.problems(config)
    if type(config.get("require_second_human_review", True)) is not bool:
        errors.append("require_second_human_review must be a boolean")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(config.get("environment", ""))):
        errors.append("environment must be an explicit simple name")
    if config.get("workflow") != ".github/workflows/factory.yml":
        errors.append("workflow must be .github/workflows/factory.yml")
    return errors


def spec_blockers(config, spec):
    errors = []
    names = spec.get("ruleset_names") or {}
    if spec.get("schema_version") != 2 or spec.get("repository") != REPOSITORY:
        errors.append("unsupported or mismatched github-settings.json")
    if (not isinstance(names, dict) or set(names) != {"validation", "production", "lifecycle"}
            or not all(isinstance(names[k], str) and names[k].count("{branch}") == 1 and names[k].index("{branch}") > 0
                       for k in ("validation", "production")) or not isinstance(names.get("lifecycle"), str)):
        errors.append("github-settings.json ruleset_names need validation and production templates with {branch} and a lifecycle name")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(spec.get("promotion_environment", ""))) or spec.get("promotion_environment") == config.get("environment"):
        errors.append("promotion_environment must be a simple name distinct from the control environment")
    if spec.get("promotion_environment_secrets") != ["FACTORY_PUBLISHER_APP_PRIVATE_KEY"]:
        errors.append("the promotion environment holds exactly the publisher key")
    if not set(spec.get("production_merge_methods") or ["merge"]) <= {"squash", "rebase"}:
        errors.append("production branches allow only squash or rebase merges")
    return errors


def ruleset_name(spec, level, branch=None):
    return spec["ruleset_names"]["lifecycle"] if level == "lifecycle" else spec["ruleset_names"][level].format(branch=branch)


def managed(spec, name):
    """Rulesets this tool owns: the branch-model names and the retired single-branch names."""
    names = spec["ruleset_names"]
    return (name == names["lifecycle"] or name in spec.get("retired_ruleset_names", [])
            or any(name.startswith(names[level].split("{branch}")[0]) for level in ("validation", "production")))


def environments(config, spec):
    """Environment name -> secrets it must hold. Both admit only the config branch."""
    return {config["environment"]: spec["environment_secrets"], spec["promotion_environment"]: spec["promotion_environment_secrets"]}


def desired_state(config, spec):
    errors = config_blockers(config)
    errors += spec_blockers(config, spec)
    if errors:
        raise Blocked("; ".join(errors))
    model = branches.parse(config)
    # Existing configurations keep their second-review requirement unless the
    # versioned policy explicitly selects the maintainer's own merge decision.
    second_review = config.get("require_second_human_review", True)
    maintainers = [{"actor_type": "User", "actor_id": m["id"], "bypass_mode": "always"} for m in config["maintainers"]]

    def ruleset(name, refs, bypass, rules):
        return {"name": name, "target": "branch", "enforcement": "active", "bypass_actors": bypass,
                "conditions": {"ref_name": {"include": ["refs/heads/" + ref for ref in refs], "exclude": []}},
                "rules": rules}

    def pull_request(**extra):
        return {"type": "pull_request", "parameters": {
            "dismiss_stale_reviews_on_push": True, "require_code_owner_review": second_review,
            "require_last_push_approval": second_review, "required_approving_review_count": int(second_review),
            "required_review_thread_resolution": True, **extra}}

    def checks(branch):
        names = model.required_checks(branch)
        # Each check is bound to the publisher App, so no other identity can satisfy it.
        return [{"type": "required_status_checks", "parameters": {
            "do_not_enforce_on_create": False, "strict_required_status_checks_policy": True,
            "required_status_checks": [{"context": name, "integration_id": config["publisher_app_id"]} for name in names]}}] if names else []

    # Validation: PR with the checks of its gate. Verified maintainers bypass ("always") so they may
    # push directly; nobody else may update the branch, and Apps and bots never bypass.
    rulesets = [ruleset(ruleset_name(spec, "validation", name), [name], copy.deepcopy(maintainers),
                        [{"type": "update", "parameters": {"update_allows_fetch_and_merge": False}}, pull_request(), *checks(name)])
                for name in model.validation]
    # Production: PR only, squash or rebase, no bypass actors, so nobody pushes directly.
    rulesets += [ruleset(ruleset_name(spec, "production", name), [name], [],
                         [pull_request(allowed_merge_methods=list(spec["production_merge_methods"])), *checks(name)])
                 for name in model.production]
    # Listed branches are never deleted or force-pushed; listed and reserved names are never created.
    rulesets.append(ruleset(ruleset_name(spec, "lifecycle"), [*model.names, *branches.RESERVED], [],
                            [{"type": "creation"}, {"type": "deletion"}, {"type": "non_fast_forward"}]))
    envs = environments(config, spec)
    return {"rulesets": rulesets,
            "environments": {name: {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}} for name in envs},
            "branch_policies": {name: [{"name": model.config_branch, "type": "branch"}] for name in envs},
            "actions": copy.deepcopy(spec["actions"]), "selected_actions": copy.deepcopy(spec["selected_actions"]),
            "workflow_permissions": copy.deepcopy(spec["workflow_permissions"])}


def wif_claim(config):
    """Claims the Anthropic federation rule must match: factory.yml on the config branch only."""
    ref = "refs/heads/" + config["config_branch"]
    return {"federation_rule_id": (config.get("anthropic_federation") or {}).get("federation_rule_id"),
            "repository": REPOSITORY, "ref": ref, "workflow_ref": f"{REPOSITORY}/{config['workflow']}@{ref}",
            "environment": config["environment"], "event_name": "workflow_dispatch"}


def owner_steps(config, report):
    """What only the repository owner can do, in order, for the current inspection."""
    claim, branch = wif_claim(config), config["config_branch"]
    steps = [f"Create branch {name} on GitHub before apply; the lifecycle ruleset forbids creating listed names."
             for name in report.get("missing_branches", [])]
    if report.get("changes"):
        steps.append("Review `settings.py diff`, then run `settings.py apply`; environment branch policies are set before any secret is added.")
    for environment, names in sorted(report.get("missing_environment_secrets", {}).items()):
        steps.append(f"After `settings.py inspect` shows {environment} limited to branch {branch}, add its secrets: {', '.join(names)}.")
    steps.append(f"Set the Anthropic federation rule {claim['federation_rule_id']} to ref={claim['ref']} and "
                 f"workflow_ref={claim['workflow_ref']}, then run "
                 f"`gh workflow run factory.yml --ref {branch} -f pr=0 -f wif_smoke=true`.")
    return steps


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
        if managed(spec, rule.get("name", "")):
            if rule.get("source_type") != "Repository" or rule.get("source", "").lower() != REPOSITORY.lower():
                blockers.append("managed ruleset name collides with an inherited ruleset")
                continue
            rulesets.append(api.request("GET", prefix + "/rulesets/" + str(rule["id"])))
    names = [r["name"] for r in rulesets]
    if len(names) != len(set(names)):
        blockers.append("duplicate managed ruleset names; resolve explicitly")
    # The lifecycle ruleset forbids creating listed names, so every listed branch must exist first.
    missing_branches = [name for name in branches.parse(config).names
                        if get_optional(api, prefix + "/branches/" + quote(name, safe="")) is None]
    blockers += [f"listed branch {name} does not exist; create it before apply" for name in missing_branches]
    existing = {env.get("name") for env in api.pages(prefix + "/environments", "environments")}
    current = {"rulesets": rulesets, "environments": {}, "branch_policies": {}}
    missing_secrets = {}
    for name, required in environments(config, spec).items():
        envpath = prefix + "/environments/" + quote(name, safe="")
        environment, policies, secret_names = None, [], []
        if name in existing:
            environment = api.request("GET", envpath)
            if (environment.get("deployment_branch_policy") or {}).get("custom_branch_policies"):
                policies = api.pages(envpath + "/deployment-branch-policies", "branch_policies")
            secret_names = [s["name"] for s in api.pages(envpath + "/secrets", "secrets")]
        current["environments"][name], current["branch_policies"][name] = environment, policies
        if set(required) - set(secret_names):
            missing_secrets[name] = sorted(set(required) - set(secret_names))
        if name == spec["promotion_environment"] and set(secret_names) - set(required):
            blockers.append(f"{name} must hold only the publisher key; remove: " + ", ".join(sorted(set(secret_names) - set(required))))
    repo_secrets = api.pages(prefix + "/actions/secrets", "secrets")
    sensitive_names = set(spec["environment_secrets"] + spec.get("optional_environment_secrets", []) + spec["promotion_environment_secrets"])
    if any(secret["name"] in sensitive_names for secret in repo_secrets):
        blockers.append("factory credentials exist as repository secrets; move them to the config-branch environments")
    current.update(actions=api.request("GET", prefix + "/actions/permissions"),
                   workflow_permissions=api.request("GET", prefix + "/actions/permissions/workflow"))
    current["selected_actions"] = (api.request("GET", prefix + "/actions/permissions/selected-actions")
                                   if current["actions"].get("allowed_actions") == "selected" else {})
    # Gate jobs run from the config branch; the dispatcher runs from the default branch (and pushed branches).
    for branch in dict.fromkeys((config["config_branch"], config["default_branch"])):
        for path in (".github/CODEOWNERS", config["workflow"], *WORKFLOWS):
            remote = get_optional(api, prefix + "/contents/" + path + "?ref=" + quote(branch, safe=""))
            if not remote or remote.get("type") != "file":
                blockers.append(f"{path} must be reviewed and present on {branch} before activation")
            elif path.endswith("CODEOWNERS"):
                try:
                    text = base64.b64decode(remote["content"]).decode()
                except (ValueError, KeyError, UnicodeError):
                    text = ""
                if text != codeowners(config):
                    blockers.append(f"CODEOWNERS on {branch} does not match verified human ownership")
    return {"repository": {"id": repository["id"], "full_name": repository["full_name"],
                           "default_branch": repository["default_branch"], "private": repository["private"]},
            "plan": plan, "apps": apps, "blockers": blockers, "desired": desired, "current": current,
            "missing_branches": missing_branches, "missing_environment_secrets": missing_secrets,
            "wif_claim": wif_claim(config)}


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
    for name, wanted in desired["environments"].items():
        envpath = prefix + "/environments/" + quote(name, safe="")
        if not same(current["environments"].get(name), wanted):
            change("PUT", envpath, wanted, "restrict credential environment " + name)
        # Remove broad policies before adding the exact branch. A transition can deny all, never permit extra refs.
        for policy in current["branch_policies"].get(name, []):
            if not any(same(policy, allowed) for allowed in desired["branch_policies"][name]):
                change("DELETE", envpath + "/deployment-branch-policies/" + str(policy["id"]), None, "remove extra environment branch/tag policy")
        for policy in desired["branch_policies"][name]:
            if not any(same(actual, policy) for actual in current["branch_policies"].get(name, [])):
                change("POST", envpath + "/deployment-branch-policies", policy, "allow the config branch only")
    for key, suffix in (("actions", ""), ("selected_actions", "/selected-actions"), ("workflow_permissions", "/workflow")):
        if not same(current[key], desired[key]):
            change("PUT", prefix + "/actions/permissions" + suffix, desired[key], "reconcile " + key)
    for rule in desired["rulesets"]:
        actual = next((r for r in current["rulesets"] if r["name"] == rule["name"]), None)
        if not same(actual, rule):
            change("PUT" if actual else "POST", prefix + "/rulesets" + ("/" + str(actual["id"]) if actual else ""), rule, "reconcile " + rule["name"])
    # Retired and unlisted-branch rulesets go only after their replacements exist.
    wanted = {rule["name"] for rule in desired["rulesets"]}
    for rule in current["rulesets"]:
        if rule["name"] not in wanted:
            change("DELETE", prefix + "/rulesets/" + str(rule["id"]), None, "remove retired or unlisted ruleset " + rule["name"])
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
    parser.add_argument("command", choices=("inspect", "diff", "apply", "codeowners", "wif"))
    parser.add_argument("--config", type=Path, default=ROOT / "factory/config.json")
    parser.add_argument("--spec", type=Path, default=ROOT / "factory/github-settings.json")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        spec = json.loads(args.spec.read_text())
        # Fail before network access when placeholders remain; no inferred identity fills.
        desired_state(config, spec)
        if args.command == "wif":
            print(json.dumps(wif_claim(config), indent=2))
            return 0
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
        report["owner_steps"] = owner_steps(config, report)
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
