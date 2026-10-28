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


def positive_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value > 0 and (not isinstance(value, float) or math.isfinite(value)))


def inspect(root, runner):
    checks = []

    def add(name, passed, detail, continuation):
        checks.append({"check": name, "status": "passed" if passed else "blocked",
                       "detail": detail, "continuation": "" if passed else continuation})

    add("python", sys.version_info >= (3, 11), "Python >= 3.11 benötigt.", "Python 3.11 oder neuer installieren.")
    files = ("AGENTS.md", "factory/config.json", "factory/policy.md", "factory/Dockerfile",
             "factory/github-settings.json", "factory/tools.lock.json", "factory/review.schema.json",
             ".github/workflows/factory.yml", ".github/CODEOWNERS", "tools/factory/clients.py",
             "tools/factory/engine.py", "tools/factory/verify.py", "tools/factory/settings.py")
    missing = [name for name in files if not regular_file(root, name)]
    add("checkout", not missing, "Fehlende/unsichere Dateien: " + ", ".join(missing) if missing else "Factory-Dateien vorhanden.",
        "Vollständigen geprüften Factory-Stand auschecken.")
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
        "Zielrepository und Default-Branch müssen dem geprüften Setup entsprechen.", "factory/config.json prüfen; keine Identität erraten.")
    add("reviewer_config", config.get("review_model") == "gpt-6-astra" and config.get("review_effort") == "high",
        "Erforderlich: gpt-6-astra mit high; Konfiguration beweist keinen API-Zugang.", "Reviewvertrag wiederherstellen.")
    # Run only this trusted checkout's adapter checker, never code from --root.
    adapters = regular_file(ROOT, "tools/factory/clients.py") and probe(
        [sys.executable, "-B", str(ROOT / "tools/factory/clients.py"), "check", "--root", str(root)], root=root)
    add("native_adapters", adapters, "Kanonische Skills und native Adapter auf Drift geprüft.",
        "python3 tools/factory/clients.py check --root .; bei autorisierter Quellenänderung sync, danach erneut prüfen.")
    for tool in ("git", "gh", "docker", "actionlint", "gitleaks"):
        add("tool_" + tool, bool(shutil.which(tool)), "Benötigtes Werkzeug: " + tool,
            "Werkzeug installieren; für Prüfwerkzeuge factory/tools.lock.json verwenden.")
    git_ok = bool(shutil.which("git")) and probe(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "rev-parse", "--verify", "HEAD"], root=root)
    add("git_head", git_ok, "Lokaler Commit vorhanden; Remote-Branch nicht geprüft.", "Geprüften Factory-Commit auschecken.")
    add("git_identity",repository_identity(root),"Git-Root und Origin müssen exakt zum Zielrepository gehören.",
        "Im richtigen Checkout starten; Origin gegen git@github.com:Zerosteps1/Aicepeak_V2.0.0.git prüfen.")
    github_ok = bool(shutil.which("gh")) and probe(["gh", "auth", "status", "--hostname", "github.com"], root=root)
    add("github_auth", github_ok, "GitHub-CLI-Authentifizierung geprüft; Administration/App-Rechte separat offen.",
        "Als berechtigter Mensch gh auth login --hostname github.com ausführen, danach settings.py inspect.")
    # Match launcher isolation: no personal Docker config/context. These calls
    # inspect the daemon/image only; no build, pull, container or model is started.
    docker_env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "DOCKER_CONFIG": os.devnull}
    if os.environ.get("FACTORY_DOCKER_HOST"):
        docker_env["DOCKER_HOST"] = os.environ["FACTORY_DOCKER_HOST"]
    daemon = bool(shutil.which("docker")) and probe(["docker", "info", "--format", "{{.ServerVersion}}"], root=root, env=docker_env)
    add("docker_daemon", daemon, "Docker-Endpunkt ohne persönliche Docker-Konfiguration geprüft.",
        "Docker starten/Zugriff herstellen; bei Bedarf FACTORY_DOCKER_HOST explizit setzen.")
    image = daemon and probe(["docker", "image", "inspect", IMAGE], root=root, env=docker_env)
    add("client_image", image, "Client-Image lokal vorhanden; Ausführung noch nicht geprüft." if image else "Client-Image fehlt oder Dockerzugriff ist blockiert; nicht nachgewiesen.",
        "docker build -f factory/Dockerfile -t " + IMAGE + " factory; danach clients.py smoke --root .")
    for name in ("OPENAI_API_KEY", "CONTEXT7_API_KEY", *(("ANTHROPIC_API_KEY",) if runner == "claude" else ())):
        add("environment_" + name, bool(os.environ.get(name)), "Nur Präsenz im Launcher-Environment geprüft: " + name,
            name + " über die Secret-Funktion der Ausführungsumgebung bereitstellen; nie ins Repository schreiben.")
    models = config.get("author_models") or {}
    prices = config.get("author_pricing_usd_per_million") or {}
    price = prices.get(runner) if isinstance(prices, dict) else None
    model = models.get(runner) if isinstance(models, dict) else None
    priced = isinstance(price, dict) and all(positive_number(price.get(key)) for key in ("input", "output"))
    add("author_" + runner, isinstance(model, str) and bool(model.strip()) and priced,
        "Exaktes Autormodell und positive Input-/Outputpreise erforderlich.",
        "Modellzugang und aktuelle Herstellerpreise prüfen und autorisiert in factory/config.json festhalten.")
    app_ids = [config.get(role + "_app_id") for role in ("publisher", "writer")]
    apps = all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in app_ids) and app_ids[0] != app_ids[1]
    add("app_ids", apps, "Zwei unterschiedliche reale App-IDs erforderlich; Installationen hier nicht verifiziert.",
        "Zwei Apps mit dem exakten Rechtesplit registrieren/installieren; IDs eintragen; settings.py inspect/diff ausführen.")
    northstar = config.get("northstar_path")
    approved = (isinstance(northstar, str) and bool(northstar) and not Path(northstar).is_absolute()
                and ".." not in Path(northstar).parts and regular_file(root, northstar)
                and config.get("northstar_approved") is True)
    product_checks = config.get("product_checks_ready") is True
    return {"status": "blocked" if any(c["status"] == "blocked" for c in checks) else "live_verification_required",
            "read_only": True, "runner": runner,
            "factory": {"local_prerequisites": checks,
                        "live_status": "unverified",
                        "required_evidence": ["settings.py inspect/diff: Identitäten, Apps, Rulesets und Environment",
                                              "clients.py smoke: gepinnte CLIs; launch/run: echter Modell-, Context7- und OpenAI-Docs-Zugang",
                                              "engine.py model-smoke: gpt-6-astra high",
                                              "realer Smoke-PR mit Review, Korrektur, erneutem Review und menschlicher Freigabe"]},
            "product": {"status": "locally_configured_unverified" if approved and product_checks else "blocked",
                        "northstar_configured_and_approved": approved, "product_checks_configured": product_checks,
                        "continuation": "Kanonischen Nordstern bewusst im Repository ablegen/freigeben, Prüfungen und versionierten Produktauftrag vor Umsetzung genehmigen.",
                        "blocks_factory_setup": False},
            "note": "Keine Schlüsselwerte, Modellaufrufe, Containerstarts oder Änderungen. gh auth status kann GitHub lesend kontaktieren. Dieser Report ersetzt keine Abnahme."}


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
        result = {"status": "blocked", "read_only": True, "reason": "Repository oder Konfiguration nicht lesbar/ungültig; Pfad und JSON prüfen."}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # Local presence can never certify active GitHub enforcement or model access.
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
