"""Fixed-origin GitHub API and narrowly scoped installation credentials."""
import base64
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import re
from contracts import Blocked, require

# The compare route needs "base...head"; every other ".." stays an unsafe path.
COMPARE_ROUTE = re.compile(r"/repos/[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*/compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}\?per_page=1")


def safe_route(path):
    return path.startswith("/") and not path.startswith("//") and (".." not in path or COMPARE_ROUTE.fullmatch(path) is not None)


class GitHub:
    def __init__(self, token=None):
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        require(bool(self.token), "GitHub credential missing")

    def request(self, method, path, data=None):
        require(safe_route(path), "unsafe API path")
        req = urllib.request.Request("https://api.github.com" + path,
            data=None if data is None else json.dumps(data).encode(), method=method,
            headers={"Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                raw = response.read(8_000_001)
            require(len(raw) <= 8_000_000, "GitHub response limit")
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise Blocked(f"GitHub {method} {path.split('?')[0]}: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise Blocked("GitHub network unavailable") from None

    def pages(self, path, field=None):
        values = []
        for page in range(1, 21):
            sep = "&" if "?" in path else "?"
            body = self.request("GET", f"{path}{sep}per_page=100&page={page}")
            items = body[field] if field else body
            values.extend(items)
            if len(items) < 100:
                return values
        raise Blocked("GitHub pagination limit; incomplete evidence")

    def text(self, repo, path, sha):
        from contracts import safe_path
        safe_path(path)
        data = self.request("GET", f"/repos/{repo}/contents/{urllib.parse.quote(path, safe='/')}?ref={sha}")
        require(isinstance(data, dict) and data.get("type") == "file" and data.get("encoding") == "base64", "unsupported source file")
        raw = base64.b64decode(data["content"], validate=False)
        require(b"\0" not in raw, "binary source cannot be completely reviewed")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise Blocked("non-UTF-8 source cannot be completely reviewed") from None


def installation(config, role):
    app_id = config[role + "_app_id"]
    key = os.environ.get("FACTORY_" + role.upper() + "_APP_PRIVATE_KEY")
    require(isinstance(app_id, int) and app_id > 0 and key, role + " App credentials missing")
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
    now = int(time.time())
    unsigned = enc(b'{"alg":"RS256","typ":"JWT"}') + b"." + enc(json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode())
    with tempfile.TemporaryDirectory() as tmp:
        keyfile = Path(tmp) / "key.pem"
        keyfile.write_text(key)
        keyfile.chmod(0o600)
        result = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(keyfile)], input=unsigned,
                                capture_output=True, check=False, timeout=10)
    require(result.returncode == 0, "App signing failed")
    client = GitHub((unsigned + b"." + enc(result.stdout)).decode())
    identity = client.request("GET", "/app")
    require(identity["id"] == app_id, "wrong App identity")
    repo = config["repository"]
    inst = client.request("GET", f"/repos/{repo}/installation")
    require(inst["app_id"] == app_id, "wrong installation")
    permissions = {"contents": "read", "checks": "write", "pull_requests": "write", "actions": "read"} if role == "publisher" else {"contents": "write", "pull_requests": "write"}
    token = client.request("POST", f"/app/installations/{inst['id']}/access_tokens",
                           {"repositories": [repo.split('/')[1]], "permissions": permissions})
    return GitHub(token["token"])


def verify_run(client, snapshot, config, required_jobs, run_id=None):
    """Check jobs of the snapshot run, or of the correction run that consumes its review."""
    repo = snapshot["repository"]
    run_id = snapshot["run_id"] if run_id is None else run_id
    require(os.environ.get("GITHUB_RUN_ATTEMPT") == str(snapshot["run_attempt"]) == "1", "job rerun must receive a new reservation")
    run = client.request("GET", f"/repos/{repo}/actions/runs/{run_id}")
    require(run["run_attempt"] == snapshot["run_attempt"], "wrong run attempt")
    require(run["repository"]["full_name"] == repo and run["event"] == "workflow_dispatch", "wrong run origin")
    require(run["head_sha"] == snapshot["policy_sha"] and run["head_branch"] == config["default_branch"], "wrong workflow revision")
    workflow = client.request("GET", f"/repos/{repo}/actions/workflows/{run['workflow_id']}")
    require(workflow["path"] == config["workflow"], "wrong workflow identity")
    jobs = client.pages(f"/repos/{repo}/actions/runs/{run_id}/jobs?filter=latest", "jobs")
    for name, allowed in required_jobs.items():
        matches = [j for j in jobs if j["name"] == name]
        require(len(matches) == 1 and matches[0]["status"] == "completed" and matches[0]["conclusion"] in allowed,
                "missing or inconsistent trusted job: " + name)
    return run
