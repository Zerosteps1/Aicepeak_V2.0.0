"""Small, closed review protocol and deterministic decisions. No provider calls."""
import hashlib
import json
import re
from pathlib import PurePosixPath


class Blocked(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Blocked(message)


def safe_path(value):
    require(isinstance(value, str) and 0 < len(value) < 500, "invalid path")
    require(not any(ord(c) < 32 for c in value) and "\\" not in value, "unsafe path")
    p = PurePosixPath(value)
    require(not p.is_absolute() and all(x not in ("", ".", "..", ".git") for x in value.split("/")), "path traversal")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(value, schema, location="review"):
    """Validate only the deliberately small JSON-Schema subset used by this protocol."""
    allowed = {"$schema", "title", "description", "type", "properties", "required", "additionalProperties", "items", "enum", "const", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems", "pattern"}
    require(not set(schema) - allowed, "unsupported schema keyword")
    typ = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool, "number": (int, float)}
    require(typ in types and isinstance(value, types[typ]), f"{location}: invalid type")
    if typ in ("integer", "number"):
        require(not isinstance(value, bool), f"{location}: boolean is not number")
    if "const" in schema:
        require(value == schema["const"], f"{location}: incorrect constant")
    if "enum" in schema:
        require(value in schema["enum"], f"{location}: invalid choice")
    if typ == "object":
        props = schema.get("properties", {})
        require(set(schema.get("required", [])) <= value.keys(), f"{location}: missing keys")
        require(schema.get("additionalProperties") is False and not value.keys() - props.keys(), f"{location}: extra keys")
        for key in value:
            validate(value[key], props[key], location + "." + key)
    if typ == "array":
        require(schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 10000), f"{location}: array length")
        for item in value:
            validate(item, schema["items"], location + "[]")
    if typ == "string":
        require(schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 100000), f"{location}: string length")
        if "pattern" in schema:
            require(re.fullmatch(schema["pattern"], value) is not None, f"{location}: pattern")
    if typ in ("integer", "number"):
        require(schema.get("minimum", -float("inf")) <= value <= schema.get("maximum", float("inf")), f"{location}: numeric bounds")


def validate_review(review, schema, snapshot):
    validate(review, schema)
    for key in ("repository", "pr", "head_sha", "base_sha", "policy_sha", "run_id", "run_attempt"):
        require(review[key] == snapshot[key], "review binding mismatch: " + key)
    require(review["model"] == "gpt-6-astra" and review["effort"] == "high", "wrong reviewer")
    require(set(review["scope"]) == set(snapshot["files"]), "incomplete diff scope")
    require(len(review["scope"]) == len(set(review["scope"])), "duplicate scope")
    require(len({f["id"] for f in review["findings"]}) == len(review["findings"]), "duplicate finding ID")
    for finding in review["findings"]:
        safe_path(finding["file"])
        require(finding["file"] in snapshot["files"], "finding outside reviewed diff")
    blocking = any(f["priority"] in ("P0", "P1") for f in review["findings"])
    if review["outcome"] == "pass":
        require(review["complete"] and not review["limitations"] and not blocking, "invalid pass")
    if review["outcome"] == "changes_requested":
        require(blocking, "changes_requested without blocking finding")
    require(review["complete"] or review["outcome"] == "blocked", "incomplete review must block")
    return review["outcome"]


def assert_current(snapshot, pr, default_sha):
    require(pr["state"] == "open" and not pr["draft"], "PR closed or draft")
    require(pr["head"]["sha"] == snapshot["head_sha"], "stale head")
    require(pr["base"]["sha"] == snapshot["base_sha"] == default_sha == snapshot["policy_sha"], "stale base/policy")
    require(pr["head"]["repo"]["full_name"] == snapshot["repository"], "fork remediation forbidden")


def handoff(body, config):
    matches = re.findall(r"```factory-handoff\s*\n(.*?)\n```", body or "", re.S)
    require(len(matches) == 1, "exactly one factory-handoff JSON block required")
    try:
        obj = json.loads(matches[0])
    except (TypeError, ValueError) as exc:
        raise Blocked("invalid handoff JSON") from exc
    require(set(obj) == {"runner", "task", "owner"}, "handoff fields")
    require(obj["runner"] in config["runners"], "runner not allowlisted")
    require(re.fullmatch(r"docs/work/[A-Za-z0-9_-]+\.md", obj["task"]) is not None, "invalid task reference")
    require(obj["owner"] in [m["login"] for m in config["maintainers"]], "unverified responsible maintainer")
    return obj


def is_control(path, config):
    safe_path(path)
    if path == "factory-smoke.json":
        return False
    return path == config.get("northstar_path") or any(path == p or (p.endswith("/") and path.startswith(p)) for p in config["protected_paths"])


def allowed_patch(paths, task, config):
    require(0 < len(paths) <= config["limits"]["max_changed_files"], "patch file limit")
    for path in paths:
        safe_path(path)
        require(not is_control(path, config), "automatic correction cannot change factory control: " + path)
        require(any(path == p or (p.endswith("/") and path.startswith(p)) for p in task["allowed_paths"]), "patch outside work order")


def authentic_check(check, snapshot, config):
    require(check["app"]["id"] == config["publisher_app_id"], "wrong reviewer publisher App")
    require(check["name"] == "factory/senior-review", "wrong check name")
    require(check["head_sha"] == snapshot["head_sha"], "wrong check SHA")
    require(check["status"] == "completed", "review not finished")
    expected = f"{snapshot['repository']}:{snapshot['pr']}:{snapshot['head_sha']}:{snapshot['policy_sha']}:{snapshot['run_id']}:{snapshot['run_attempt']}"
    require(check["external_id"] == expected, "unauthenticated review binding")
    require(check["details_url"] == f"https://github.com/{snapshot['repository']}/actions/runs/{snapshot['run_id']}", "wrong reviewer run")


def gates(review_outcome, tests_ok, current, draft=False):
    return {"factory/deterministic": "success" if tests_ok and current and not draft else "failure",
            "factory/senior-review": "success" if review_outcome == "pass" and current and not draft else "failure"}
