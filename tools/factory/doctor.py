#!/usr/bin/env python3
"""Read-only prerequisite report; never a live factory acceptance certificate."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
IMAGE = "aicepeak-factory-clients:codex-0.164.0-claude-2.1.311"
REPOSITORY = "Zerosteps1/Aicepeak_V2.0.0"


def probe(command, *, root, env=None):
    """Discard external output: it may contain credentials or untrusted text."""
    try:
        return subprocess.run(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=15, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def regular_file(root, name):
    path = root / name
    return (path.is_file() and not path.is_symlink()
            and all(not parent.is_symlink() for parent in path.parents if parent != root)
            and path.resolve().is_relative_to(root))


def repository_identity(root):
    """Inspect exact git root/origin without ever displaying credential-bearing URLs."""
    try:
        command=['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false']
        top=subprocess.run([*command,'rev-parse','--show-toplevel'],cwd=root,text=True,capture_output=True,timeout=10)
        origin=subprocess.run([*command,'remote','get-url','origin'],cwd=root,text=True,capture_output=True,timeout=10)
        allowed={f'git@github.com:{REPOSITORY}.git',f'https://github.com/{REPOSITORY}.git',f'https://github.com/{REPOSITORY}'}
        return top.returncode==origin.returncode==0 and Path(top.stdout.strip()).resolve()==root and origin.stdout.strip() in allowed
    except (OSError,subprocess.SubprocessError):return False


def codex_version():
    """The CLI version string is not sensitive; it decides whether the reviewer contract holds."""
    try:
        result = subprocess.run(["codex", "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=15)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def keychain_item(service, root):
    """Presence only: `security` without -w never prints the stored value."""
    return sys.platform == "darwin" and bool(shutil.which("security")) and probe(
        ["security", "find-generic-password", "-s", service], root=root)


def positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value > 0 and (not isinstance(value, float) or math.isfinite(value)))


def inspect(root, runner):
    checks = []

    def add(name, passed, detail, continuation):
        checks.append({"check": name, "status": "passed" if passed else "blocked",
                       "detail": detail, "continuation": "" if passed else continuation})

    add("python", sys.version_info >= (3, 11), "Python >= 3.11 required.", "Install Python 3.11 or newer.")
    files = ("AGENTS.md", "factory/config.json", "factory/policy.md", "factory/Dockerfile",
             "factory/github-settings.json", "factory/tools.lock.json", "factory/review.schema.json",
             ".github/workflows/factory.yml", ".github/CODEOWNERS", "tools/factory/clients.py",
             "tools/factory/engine.py", "tools/factory/local_review.py", "tools/factory/verify.py", "tools/factory/settings.py")
    missing = [name for name in files if not regular_file(root, name)]
    add("checkout", not missing, "Missing or unsafe files: " + ", ".join(missing) if missing else "Factory files present.",
        "Check out the complete reviewed factory revision.")
    try:
        path = root / "factory/config.json"
        if not regular_file(root, "factory/config.json") or path.stat().st_size > 100000:
            raise ValueError
        config = json.loads(path.read_text())
        if not isinstance(config, dict):
            raise ValueError
    except (OSError, ValueError):
        config = {}
    add("repository_config", config.get("repository") == REPOSITORY and config.get("default_branch") == "main",
        "Target repository and default branch must match the reviewed setup.", "Check factory/config.json; never guess an identity.")
    add("reviewer_config", config.get("review_model") == "gpt-6-astra" and config.get("review_effort") == "high",
        "Required: gpt-6-astra with effort high; configuration does not prove model access.", "Restore the review contract.")
    # Run only this trusted checkout's adapter checker, never code from --root.
    adapters = regular_file(ROOT, "tools/factory/clients.py") and probe(
        [sys.executable, "-B", str(ROOT / "tools/factory/clients.py"), "check", "--root", str(root)], root=root)
    add("native_adapters", adapters, "Canonical skills and native adapters checked for drift.",
        "python3 tools/factory/clients.py check --root .; after an authorized source change run sync, then check again.")
    for tool in ("git", "gh", "docker", "actionlint", "gitleaks"):
        add("tool_" + tool, bool(shutil.which(tool)), "Required tool: " + tool,
            "Install the tool; use factory/tools.lock.json for the check tools.")
    git_ok = bool(shutil.which("git")) and probe(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "rev-parse", "--verify", "HEAD"], root=root)
    add("git_head", git_ok, "Local commit present; remote branch not checked.", "Check out the reviewed factory commit.")
    add("git_identity",repository_identity(root),"Git root and origin must belong exactly to the target repository.",
        "Start in the right checkout; compare origin with git@github.com:Zerosteps1/Aicepeak_V2.0.0.git.")
    github_ok = bool(shutil.which("gh")) and probe(["gh", "auth", "status", "--hostname", "github.com"], root=root)
    add("github_auth", github_ok, "GitHub CLI authentication checked; administration and App rights stay open.",
        "As an authorized human run gh auth login --hostname github.com, then settings.py inspect.")
    # Match launcher isolation: no personal Docker config/context. These calls
    # inspect the daemon/image only; no build, pull, container or model is started.
    docker_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DOCKER_CONFIG": os.devnull}
    if os.environ.get("FACTORY_DOCKER_HOST"):
        docker_env["DOCKER_HOST"] = os.environ["FACTORY_DOCKER_HOST"]
    daemon = bool(shutil.which("docker")) and probe(["docker", "info", "--format", "{{.ServerVersion}}"], root=root, env=docker_env)
    add("docker_daemon", daemon, "Docker endpoint checked without personal Docker configuration.",
        "Start Docker or grant access; set FACTORY_DOCKER_HOST explicitly if needed.")
    image = daemon and probe(["docker", "image", "inspect", IMAGE], root=root, env=docker_env)
    add("client_image", image, "Client image present locally; execution not yet checked." if image else "Client image missing or Docker access blocked; not proven.",
        "docker build -f factory/Dockerfile -t " + IMAGE + " factory; then clients.py smoke --root .")
    # The isolated launcher needs the provider key of its runner; the reviewer needs none (ADR-0005).
    for name in ("OPENAI_API_KEY" if runner == "codex" else "ANTHROPIC_API_KEY", "CONTEXT7_API_KEY"):
        add("environment_" + name, bool(os.environ.get(name)), "Presence in the launcher environment only: " + name,
            "Provide " + name + " through the execution environment's secret facility; never write it to the repository.")
    version = codex_version()
    add("reviewer_codex", version == "codex-cli 0.164.0", "Senior reviewer host needs codex-cli 0.164.0; found: " + (version or "none"),
        "Install the pinned Codex CLI; a different version needs a reviewed tool-surface check first.")
    for check, name, service in (("reviewer_access_token", "CODEX_ACCESS_TOKEN", "aicepeak-factory-codex-access-token"),
                                 ("reviewer_publisher_key", "FACTORY_PUBLISHER_APP_PRIVATE_KEY", "aicepeak-factory-publisher-key")):
        add(check, bool(os.environ.get(name)) or keychain_item(service, root), f"Presence only: {name} or keychain item {service}.",
            f"Store it in the login keychain item {service} (see factory/clients.md); never in a file or the repository.")
    models = config.get("author_models") or {}
    prices = config.get("author_pricing_usd_per_million") or {}
    price = prices.get(runner) if isinstance(prices, dict) else None
    model = models.get(runner) if isinstance(models, dict) else None
    priced = isinstance(price, dict) and all(positive_number(price.get(key)) for key in ("input", "output"))
    add("author_" + runner, isinstance(model, str) and bool(model.strip()) and priced,
        "Exact author model and positive input/output prices required.",
        "Check model access and current vendor prices; record them in factory/config.json through a reviewed change.")
    app_ids = [config.get(role + "_app_id") for role in ("publisher", "writer")]
    apps = all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in app_ids) and app_ids[0] != app_ids[1]
    add("app_ids", apps, "Two different real App IDs required; installations are not verified here.",
        "Register and install two Apps with the exact permission split; record the IDs; run settings.py inspect/diff.")
    northstar = config.get("northstar_path")
    approved = (isinstance(northstar, str) and bool(northstar) and not Path(northstar).is_absolute()
                and ".." not in Path(northstar).parts and regular_file(root, northstar)
                and config.get("northstar_approved") is True)
    product_checks = config.get("product_checks_ready") is True
    return {"status": "blocked" if any(c["status"] == "blocked" for c in checks) else "live_verification_required",
            "read_only": True, "runner": runner,
            "factory": {"local_prerequisites": checks,
                        "live_status": "unverified",
                        "required_evidence": ["settings.py inspect/diff: identities, Apps, rulesets and environment",
                                              "clients.py smoke: pinned CLIs; launch/run: real model, Context7 and OpenAI Docs access",
                                              "local_review.py --smoke: gpt-6-astra high under the ChatGPT Business access token",
                                              "real smoke PR with review, correction, new review and human approval"]},
            "product": {"status": "locally_configured_unverified" if approved and product_checks else "blocked",
                        "northstar_configured_and_approved": approved, "product_checks_configured": product_checks,
                        "continuation": "Store and approve the canonical north star in the repository; approve checks and a versioned product task before implementation.",
                        "blocks_factory_setup": False},
            "note": "No secret values, model calls, container starts or changes. gh auth status may contact GitHub read-only. This report is not an acceptance."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--runner", choices=("codex", "claude"), default="codex")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError
        result = inspect(root, args.runner)
    except (OSError, ValueError, TypeError):
        result = {"status": "blocked", "read_only": True, "reason": "Repository or configuration unreadable or invalid; check path and JSON."}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Local presence can never certify active GitHub enforcement or model access.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
