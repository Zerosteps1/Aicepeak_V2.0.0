#!/usr/bin/env python3
"""Metadata-only dispatcher. Never checks out or executes a pull request."""
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import quote

TARGET = "Zerosteps1/Aicepeak_V2.0.0"
PREFIX = "/repos/" + TARGET


def api(method, endpoint, body=None):
    command = ["gh", "api", "--hostname", "github.com", "--method", method,
               "-H", "X-GitHub-Api-Version: 2026-03-10", endpoint]
    if body is not None:
        command += ["--input", "-"]
    result = subprocess.run(command, input=json.dumps(body) if body is not None else None,
                            capture_output=True, text=True, timeout=45, check=False)
    if result.returncode:
        # Never include API content, tokens, or untrusted comment text in errors.
        raise RuntimeError("GitHub metadata request failed: " + method + " " + endpoint)
    return json.loads(result.stdout) if result.stdout.strip() else None


def number(value):
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,17}", str(value)):
        raise RuntimeError("Invalid numeric GitHub identifier")
    return int(value)


def authorized(user, config):
    return user.get("type") == "User" and any(
        m.get("id") == user.get("id") and m.get("login", "").lower() == user.get("login", "").lower()
        for m in config.get("maintainers", []) if isinstance(m, dict))


def valid_pr(pr, config, repository_id):
    return (pr.get("state") == "open" and pr.get("base", {}).get("ref") == config["default_branch"]
            and pr.get("base", {}).get("repo", {}).get("id") == repository_id)


def cancel_obsolete(config, pr_number, pr):
    """Cancel only authenticated runs for older heads/policies, never a title edit."""
    app=config.get('publisher_app_id')
    if not isinstance(app,int) or app<=0:return
    handled=set()
    for page in range(1,21):
        comments=api('GET',f'{PREFIX}/issues/{pr_number}/comments?per_page=100&page={page}')
        for comment in comments:
            if (comment.get('performed_via_github_app') or {}).get('id')!=app:continue
            body=comment.get('body') or ''
            if not body.startswith('<!-- factory-ledger:v1 -->\n'):continue
            pointer=json.loads(body.split('\n',1)[1])
            check=api('GET',f"{PREFIX}/check-runs/{number(pointer['check_id'])}")
            if check.get('app',{}).get('id')!=app or check.get('status')=='completed':continue
            binding=(check.get('external_id') or '').split(':')
            if len(binding)!=6 or binding[:2]!=[TARGET,str(pr_number)]:raise RuntimeError('Invalid authenticated run binding')
            if binding[2]==pr['head']['sha'] and binding[3]==pr['base']['sha']:continue
            run_id=number(binding[4])
            if run_id in handled:continue
            handled.add(run_id)
            run=api('GET',f'{PREFIX}/actions/runs/{run_id}')
            if run.get('status')=='completed':continue
            workflow=api('GET',f"{PREFIX}/actions/workflows/{number(run['workflow_id'])}")
            if (run.get('event')!='workflow_dispatch' or run.get('head_sha')!=binding[3]
                    or run.get('repository',{}).get('full_name')!=TARGET
                    or workflow.get('path')!='.github/workflows/factory.yml'):
                raise RuntimeError('Refuse to cancel an unverified workflow')
            try:api('POST',f'{PREFIX}/actions/runs/{run_id}/cancel')
            except RuntimeError:
                if api('GET',f'{PREFIX}/actions/runs/{run_id}').get('status')!='completed':raise
        if len(comments)<100:return
    raise RuntimeError('Incomplete cancellation ledger')


def main():
    config = json.loads(Path("factory/config.json").read_text())
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    kind = os.environ["FACTORY_EVENT"]
    if config.get("repository") != TARGET or not config.get("default_branch") or not config.get("maintainers"):
        raise RuntimeError("Factory configuration is blocked: verified default branch and maintainers required")
    if os.environ.get("FACTORY_REF") != "refs/heads/" + config["default_branch"]:
        raise RuntimeError("Dispatcher must execute on the configured default branch")
    repository = api("GET", PREFIX)
    if repository.get("full_name", "").lower() != TARGET.lower() or repository.get("default_branch") != config["default_branch"]:
        raise RuntimeError("Repository/default branch identity changed")
    jobs = []
    if kind == "pull_request_target":
        jobs.append((number(event["pull_request"]["number"]), "none", "0"))
    elif kind == "issue_comment":
        if not event.get("issue", {}).get("pull_request") or not authorized(event.get("sender", {}), config):
            print("Ignored non-PR or unconfigured/bot feedback")
            return
        comment = api("GET", PREFIX + "/issues/comments/" + str(number(event["comment"]["id"])))
        pr = number(event["issue"]["number"])
        if not authorized(comment.get("user", {}), config) or comment.get("user", {}).get("id") != event["sender"]["id"] or comment.get("issue_url") != "https://api.github.com" + PREFIX + "/issues/" + str(pr):
            raise RuntimeError("Issue-comment identity or PR association failed")
        jobs.append((pr, "issue_comment", str(number(comment["id"]))))
    elif kind == "workflow_run":
        run = api("GET", PREFIX + "/actions/runs/" + str(number(event["workflow_run"]["id"])))
        if not authorized(run.get("actor", {}), config):
            print("Ignored unconfigured/bot feedback run")
            return
        workflow = api("GET", PREFIX + "/actions/workflows/" + str(number(run["workflow_id"])))
        if workflow.get("path") != ".github/workflows/factory-feedback.yml" or run.get("repository", {}).get("id") != repository["id"]:
            raise RuntimeError("Unexpected feedback ingress workflow")
        match = re.fullmatch(r"factory-feedback:([1-9][0-9]*):(pull_request_review|pull_request_review_comment):([1-9][0-9]*)", run.get("display_title", ""))
        if not match or run.get("event") != match[2]:
            raise RuntimeError("Malformed feedback ingress identifiers")
        pr, identifier = number(match[1]), number(match[3])
        feedback_kind = "review" if match[2] == "pull_request_review" else "review_comment"
        endpoint = (f"{PREFIX}/pulls/{pr}/reviews/{identifier}" if feedback_kind == "review"
                    else f"{PREFIX}/pulls/comments/{identifier}")
        feedback = api("GET", endpoint)
        if not authorized(feedback.get("user", {}), config) or feedback.get("user", {}).get("id") != run["actor"]["id"]:
            raise RuntimeError("Feedback author does not match configured human run actor")
        if feedback.get("pull_request_url") != "https://api.github.com" + PREFIX + "/pulls/" + str(pr):
            raise RuntimeError("Feedback belongs to a different pull request")
        jobs.append((pr, feedback_kind, str(identifier)))
    elif kind == "push":
        if event.get("ref") != "refs/heads/" + config["default_branch"]:
            return
        for page in range(1, 101):
            prs = api("GET", PREFIX + "/pulls?state=open&base=" + quote(config["default_branch"], safe="") + f"&per_page=100&page={page}")
            jobs.extend((number(pr["number"]), "none", "0") for pr in prs)
            if len(prs) < 100:
                break
        else:
            raise RuntimeError("PR pagination limit reached")
    else:
        raise RuntimeError("Unsupported dispatcher event")
    for pr_number, feedback_kind, feedback_id in jobs:
        pr = api("GET", PREFIX + "/pulls/" + str(pr_number))
        if not valid_pr(pr, config, repository["id"]):
            print("Ignored closed PR or different target branch")
            continue
        cancel_obsolete(config,pr_number,pr)
        api("POST", PREFIX + "/actions/workflows/factory.yml/dispatches", {
            "ref": config["default_branch"], "inputs": {"pr": str(pr_number),
            "feedback_kind": feedback_kind, "feedback_id": feedback_id}})
        print(f"Dispatched PR {pr_number} ({feedback_kind})")


if __name__ == "__main__":
    main()
