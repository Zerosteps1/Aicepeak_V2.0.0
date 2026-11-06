#!/usr/bin/env python3
"""Metadata-only dispatcher. Never checks out or executes a pull request.

Routes each event by the PR's target branch with the configuration of the config branch tip and
dispatches config-branch workflows only; those re-verify every input before they act."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/factory"))
import branches  # noqa: E402  (stdlib-only branch model shared with the trusted pipeline)

TARGET = "Zerosteps1/Aicepeak_V2.0.0"
PREFIX = "/repos/" + TARGET
PIPELINE, PROMOTION = "factory.yml", "factory-promotion.yml"


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


def valid_pr(pr, repository_id):
    return pr.get("state") == "open" and pr.get("base", {}).get("repo", {}).get("id") == repository_id


def trusted_config():
    """Configuration of the config branch tip. The checkout only names the config branch; a finished change of
    the config branch is followed once (branches.follow), and the configuration used names its own branch."""
    local = json.loads(Path("factory/config.json").read_text())
    name = local.get("config_branch")
    if local.get("repository") != TARGET or not isinstance(name, str) or not branches.NAME.fullmatch(name):
        raise RuntimeError("Factory configuration is blocked: repository and config branch required")
    tips = {}

    def read(branch):
        if not isinstance(branch, str) or not branches.NAME.fullmatch(branch):
            raise RuntimeError("Invalid config branch name")
        tip = (api("GET", f"{PREFIX}/git/ref/heads/{branch}") or {}).get("object", {}).get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", str(tip)):
            raise RuntimeError("Invalid config branch tip")
        data = api("GET", f"{PREFIX}/contents/factory/config.json?ref={tip}") or {}
        if data.get("type") != "file" or data.get("encoding") != "base64":
            raise RuntimeError("Config branch configuration unavailable")
        tips[branch] = tip
        return json.loads(base64.b64decode(data["content"]))

    name, config = branches.follow(read, name)
    if config.get("config_branch") != name:
        raise RuntimeError("The config branch configuration names a different config branch; refusing to dispatch")
    if config.get("repository") != TARGET or not config.get("maintainers"):
        raise RuntimeError("Factory configuration is blocked: verified repository and maintainers required")
    # The policy is the tip whose configuration routes this event.
    return config, branches.parse(config), tips[name]


def command(body):
    """Maintainer command word at the very start of a comment: review, bypass or None."""
    match = re.match(r"/(review|bypass)(?=\s|$)", body or "")
    return match[1] if match else None


def issue_command(config, event):
    """(issue, word, comment ID) for a maintainer's new /review or /accept on a maintainer's issue, else None.

    Work-order issues (tools/factory/issues.py): the trusted factory.yml jobs re-verify everything again."""
    if not config.get("issue_review_model"):
        # The config branch's factory.yml has no issue jobs before issue work orders are enabled there.
        print("Ignored issue comment: issue work orders are not enabled on the config branch")
        return None
    issue_number = number(event["issue"]["number"])
    comment = api("GET", PREFIX + "/issues/comments/" + str(number(event["comment"]["id"])))
    if (not authorized(comment.get("user", {}), config) or comment.get("user", {}).get("id") != event["sender"]["id"]
            or comment.get("issue_url") != "https://api.github.com" + PREFIX + "/issues/" + str(issue_number)):
        raise RuntimeError("Issue-comment identity or issue association failed")
    match = re.match(r"/(review|accept)(?=\s|$)", comment.get("body") or "")
    if not match:
        print("Ignored ordinary issue comment")
        return None
    if event.get("action") != "created":
        print("Ignored edited command comment; post a new comment")
        return None
    if os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise RuntimeError("a re-run never repeats a command; post a new comment")
    issue = api("GET", PREFIX + "/issues/" + str(issue_number))
    if issue.get("pull_request") or not authorized(issue.get("user", {}), config):
        print("Ignored command: only issues opened by configured maintainers are work orders")
        return None
    return issue_number, match[1], number(comment["id"])


def route(m, base, pr_number, kind, ident="0", head=""):
    """(workflow, inputs) dispatches for one event on a PR into `base`; [] when the factory ignores it.
    kind: update, production_push, review_request, bypass, issue_comment, review, dismissal or review_comment.
    `head` is the PR head the dispatcher read: a command binds to it, and the trusted stage refuses any other."""
    n, production, gated = str(pr_number), m.level(base) == "production", m.gated(base)
    pipeline = (PIPELINE, {"pr": n, "feedback_kind": "none", "feedback_id": "0"})
    check = (PROMOTION, {"pr": n})
    if kind == "update":
        return [pipeline] if gated else [pipeline, check] if production else []
    if kind == "production_push":
        return [check] if production else []
    if kind == "dismissal":
        # A dismissed approval changes what the production check counts; on a full gate it changes the feedback a
        # pending review is bound to, so the plain pipeline update re-reads it (nobody's feedback is forwarded).
        return [check] if production else [pipeline] if m.gate(base) == "full" else []
    if kind == "review_request" and production:
        return [(PIPELINE, {"pr": n, "review_request": ident, "head": head})] if m.review(base) != "no" else []
    if kind == "bypass" and (gated or production):
        jobs = [(PIPELINE, {"pr": n, "bypass": ident, "head": head})]
        return jobs + [(PROMOTION, {"pr": n, "bypass": ident, "head": head})] if production else jobs
    if kind in ("review_request", "bypass"):
        kind = "issue_comment"  # A command where it does not apply is an ordinary comment.
    if m.gate(base) == "full":
        return [(PIPELINE, {"pr": n, "feedback_kind": kind, "feedback_id": ident})]
    # Approving reviews decide work-order/config PRs into production.
    return [check] if production and kind != "issue_comment" else []


def cancel_obsolete(config, pr_number, pr, policy):
    """Cancel only authenticated runs for older heads, config tips or targets, never a title edit."""
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
            if len(binding)==6:continue  # Legacy bindings never count; their runs fail as stale.
            if len(binding)!=7 or binding[:2]!=[TARGET,str(pr_number)]:raise RuntimeError('Invalid authenticated run binding')
            if binding[2]==pr['head']['sha'] and binding[3]==policy and binding[4]==pr['base']['ref']:continue
            run_id=number(binding[5])
            if run_id in handled:continue
            handled.add(run_id)
            run=api('GET',f'{PREFIX}/actions/runs/{run_id}')
            if run.get('status')=='completed':continue
            workflow=api('GET',f"{PREFIX}/actions/workflows/{number(run['workflow_id'])}")
            if (run.get('event')!='workflow_dispatch' or run.get('head_sha')!=binding[3]
                    or run.get('repository',{}).get('full_name')!=TARGET
                    or workflow.get('path')!='.github/workflows/factory.yml'):
                raise RuntimeError('Refuse to cancel an unverified workflow')
            # A run on another branch (a former config branch) cannot act for the current config: never cancelled.
            if run.get('head_branch')!=config['config_branch']:continue
            try:api('POST',f'{PREFIX}/actions/runs/{run_id}/cancel')
            except RuntimeError:
                if api('GET',f'{PREFIX}/actions/runs/{run_id}').get('status')!='completed':raise
        if len(comments)<100:return
    raise RuntimeError('Incomplete cancellation ledger')


def main():
    config, model, policy = trusted_config()
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    kind = os.environ["FACTORY_EVENT"]
    ref = os.environ.get("FACTORY_REF")
    # Pushes run the pushed branch's copy of this workflow; every other event the default branch's.
    expected = event.get("ref") if kind == "push" else "refs/heads/" + config["default_branch"]
    if not expected or ref != expected:
        raise RuntimeError("Dispatcher must execute on the configured default branch or the pushed branch")
    repository = api("GET", PREFIX)
    if repository.get("full_name", "").lower() != TARGET.lower() or repository.get("default_branch") != config["default_branch"]:
        raise RuntimeError("Repository/default branch identity changed")
    jobs = []  # (PR number, event kind for route(), identifier)
    pushed = None
    if kind == "pull_request_target":
        jobs.append((number(event["pull_request"]["number"]), "update", "0"))
    elif kind == "issue_comment":
        if not authorized(event.get("sender", {}), config):
            print("Ignored unconfigured/bot feedback")
            return
        if not event.get("issue", {}).get("pull_request"):
            found = issue_command(config, event)
            if found:
                issue_number, word, comment_id = found
                api("POST", f"{PREFIX}/actions/workflows/{PIPELINE}/dispatches", {"ref": config["config_branch"], "inputs": {
                    "issue": str(issue_number), "issue_command": word, "comment": str(comment_id)}})
                print(f"Dispatched {PIPELINE} for issue {issue_number} (/{word})")
            return
        comment = api("GET", PREFIX + "/issues/comments/" + str(number(event["comment"]["id"])))
        pr = number(event["issue"]["number"])
        if not authorized(comment.get("user", {}), config) or comment.get("user", {}).get("id") != event["sender"]["id"] or comment.get("issue_url") != "https://api.github.com" + PREFIX + "/issues/" + str(pr):
            raise RuntimeError("Issue-comment identity or PR association failed")
        word = command(comment.get("body"))
        if word and event.get("action") != "created":
            # A command applies to the head current when it is posted; editing it later never repeats it.
            print("Ignored edited command comment; post a new comment")
            return
        if word and os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
            # A re-run replays the original event, but reads the PR head as it is now.
            raise RuntimeError("a re-run never repeats a command; post a new comment")
        jobs.append((pr, {"review": "review_request", "bypass": "bypass"}.get(word, "issue_comment"), str(number(comment["id"]))))
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
        if feedback.get("pull_request_url") != "https://api.github.com" + PREFIX + "/pulls/" + str(pr):
            raise RuntimeError("Feedback belongs to a different pull request")
        if feedback_kind == "review" and feedback.get("state") == "DISMISSED":
            # The dismissing maintainer (the run actor, checked above) acts, not the review's author.
            feedback_kind = "dismissal"
        elif not authorized(feedback.get("user", {}), config) or feedback.get("user", {}).get("id") != run["actor"]["id"]:
            raise RuntimeError("Feedback author does not match configured human run actor")
        jobs.append((pr, feedback_kind, str(identifier)))
    elif kind == "push":
        branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ""
        if not (model.gated(branch) or model.level(branch) == "production"):
            print("Ignored push to a branch the factory does not gate")
            return
        if event.get("deleted"):
            print("Ignored branch deletion")
            return
        sha = event.get("after", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("Invalid pushed commit identifier")
        pushed = (branch, sha)
        targets = [(branch, "update" if model.gated(branch) else "production_push")]
        if branch == model.config_branch:
            # Every check binds the config tip: re-run the PRs into the other gated and production branches too.
            targets += [(name, "update") for name in model.names
                        if name != branch and (model.gated(name) or model.level(name) == "production")]
        seen = set()
        for target, route_kind in targets:
            for page in range(1, 101):
                prs = api("GET", PREFIX + "/pulls?state=open&base=" + quote(target, safe="") + f"&per_page=100&page={page}")
                for found in prs:
                    if number(found["number"]) not in seen:
                        seen.add(number(found["number"]))
                        jobs.append((number(found["number"]), route_kind, "0"))
                if len(prs) < 100:
                    break
            else:
                raise RuntimeError("PR pagination limit reached")
    else:
        raise RuntimeError("Unsupported dispatcher event")
    for pr_number, route_kind, identifier in jobs:
        pr = api("GET", PREFIX + "/pulls/" + str(pr_number))
        if not valid_pr(pr, repository["id"]):
            print(f"Ignored PR {pr_number}: closed or from a different repository")
            continue
        base, head = pr["base"].get("ref"), pr.get("head", {}).get("sha", "")
        if route_kind in ("review_request", "bypass") and not re.fullmatch(r"[0-9a-f]{40}", str(head)):
            raise RuntimeError("Invalid PR head identifier")
        dispatches = route(model, base, pr_number, route_kind, identifier, head)
        if not dispatches:
            print(f"Ignored PR {pr_number}: the factory does not act on this event for its target branch")
            continue
        if route_kind == "update" and pushed is not None and base == pushed[0] and pr["base"].get("sha") != pushed[1]:
            # The pipeline only gates PRs on the current target tip. Its "Update branch" push starts
            # the fresh run, so dispatching now would only produce a failed run. PRs re-run because
            # the config tip moved keep their base and are never skipped here.
            print(f"Skipped PR {pr_number}: base is not the pushed {base}; update the branch")
            continue
        if any(workflow == PIPELINE for workflow, _ in dispatches):
            cancel_obsolete(config, pr_number, pr, policy)
        for workflow, inputs in dispatches:
            api("POST", f"{PREFIX}/actions/workflows/{workflow}/dispatches",
                {"ref": config["config_branch"], "inputs": inputs})
            print(f"Dispatched {workflow} for PR {pr_number} ({route_kind})")


if __name__ == "__main__":
    main()
