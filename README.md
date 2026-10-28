# Aicepeak Softwarefabrik

Gemeinsame Factory für Codex und Claude Code in `Zerosteps1/Aicepeak_V2.0.0`: isolierte Autoren, deterministische Prüfungen, unabhängiges Senior-Review und menschlicher Merge. Zentraler Reviewer ist ausschließlich **`gpt-6-astra`, Effort `high`**. Seine Konfiguration ist vorhanden; API-Zugang und realer Betrieb sind noch nicht nachgewiesen.

**Stand 27.10.2026:** lokal vorbereitet, noch nicht aktiviert. Das öffentliche Zielrepository wurde ohne Branches vorgefunden. GitHub-Authentifizierung, zwei installierte Apps, Secrets, erreichbares Docker und echte Smoke-Läufe fehlen. Ein freigegebener Nordstern fehlt ebenfalls: Produktentwicklung ist blockiert, Factory-Einrichtung bleibt zulässig. Keine Produktarchitektur wird vorweggenommen.

## Einstieg im frischen Checkout

Nach menschlichem Bootstrap-Merge den geprüften Stand auschecken. Benötigt werden Python ≥ 3.11, Git, GitHub CLI und Docker; Prüfwerkzeuge sind in `factory/tools.lock.json` versioniert.

```sh
git clone git@github.com:Zerosteps1/Aicepeak_V2.0.0.git
cd Aicepeak_V2.0.0
python3 tools/factory/doctor.py --root . --runner codex
python3 tools/factory/clients.py check --root .
docker build -f factory/Dockerfile \
  -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
python3 tools/factory/verify.py --root .
```

Der Doctor prüft lesend lokale Voraussetzungen und GitHub-CLI-Authentifizierung. Er zeigt nur Secret-Präsenz, niemals Werte. Exitcode 2 bedeutet offene Voraussetzungen oder ausstehende Live-Abnahme; lokale Präsenz ist kein Betriebsnachweis. `smoke` prüft Containergrenzen, einen ungemounteten Testinhalt, CLI-Versionen und native Discovery; authentifizierte Modell- und MCP-Ausführung ist eine gesonderte Live-Abnahme. `verify.py` benötigt `actionlint` und `gitleaks` im PATH; `--structure-only` ersetzt die vollständige Prüfung nicht. Im Image sind beide enthalten. Auf Linux installiert `python3 factory/install_tools.py --lock factory/tools.lock.json --destination /tmp/aicepeak-factory-tools` die geprüften Binaries; dieses Verzeichnis anschließend in den PATH aufnehmen. Andere Hosts benötigen passende offizielle Binaries derselben Versionen.

Provider- und Context7-Schlüssel ausschließlich über die Secret-Funktion der Launcher-Umgebung bereitstellen: für Codex `OPENAI_API_KEY` und `CONTEXT7_API_KEY`; für Claude zusätzlich `ANTHROPIC_API_KEY`. Claude ist auf `claude-sonnet-5-5` mit dokumentierten Preisannahmen konfiguriert; tatsächlicher API-Zugang bleibt zu prüfen. Bei einem abweichenden Docker-Endpunkt `FACTORY_DOCKER_HOST` setzen.

```sh
python3 tools/factory/engine.py model-smoke
python3 tools/factory/clients.py launch --root . --runner codex
# Für Claude: --runner claude
```

**Nicht mit einem bloßen `codex`-Aufruf starten.** `FACTORY_PROXY_TOKEN` entsteht automatisch im isolierten Launcher; es ist kein einzutragender persönlicher Schlüssel. Die MCPs benötigen den gleichzeitig gestarteten Broker. Details und Fehlerursachen stehen in [Clients](factory/clients.md).

Im frischen Client mit `factory-start` beginnen und den versionierten Auftrag nennen. `factory-change` implementiert, `factory-review` prüft lokal, `factory-fix-review` bearbeitet Rückmeldungen. Das Startprogramm liefert einen Patch und verändert den ursprünglichen Checkout nicht. Weitere Details: [Clients](factory/clients.md), [Beitragen](CONTRIBUTING.md), [Policy](factory/policy.md).

## Einmalige Aktivierung durch den Repository-Verantwortlichen

1. Als Gabriel (`Zerosteps1`, ID `115100163`) GitHub authentifizieren und Administration nachweisen. Felix erst nach Verifikation seines tatsächlichen Kontos und seiner Berechtigung hinzufügen. [GitHub-Zugang](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens).
2. Zwei [GitHub Apps registrieren](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) und ausschließlich im Zielrepository installieren. Der genaue Rechtesplit steht in `factory/github-settings.json`: Publisher publiziert Checks/Feedback, Writer schreibt Korrekturbranches. Reale IDs eintragen; keine App erhält Bypass. `python3 tools/factory/settings.py codeowners` verifiziert die menschlichen Identitäten und erzeugt CODEOWNERS. Beide Änderungen vor Veröffentlichung committen. [Einrichtung und API-Prüfung](factory/github.md).
3. Bei weiterhin leerem Remote erstellt der **Mensch** einmalig einen leeren `main`-Commit. Danach die lokale Factory-Historie in einem separaten Veröffentlichungsbranch anbinden; `factory/setup` bleibt erhalten. Diese Bootstrap-Ausnahme benötigt menschliche Prüfung, da die Factory noch nicht auf `main` existiert:

````sh
# Mensch, einmalig in einem neuen leeren Verzeichnis:
git init --initial-branch=main
git remote add origin git@github.com:Zerosteps1/Aicepeak_V2.0.0.git
git commit --allow-empty -m "Initialize repository for reviewed factory bootstrap"
git push -u origin main

# Danach im lokalen Factory-Checkout mit sauberem, fertig committetem Stand:
git fetch origin main
git switch -c factory/bootstrap-publish factory/setup
git merge --allow-unrelated-histories --no-edit origin/main
git push -u origin factory/bootstrap-publish
gh pr create --base main --head factory/bootstrap-publish --title "Set up repository factory" --body-file - <<'PR_BODY'
This bootstrap adds the repository-only factory, two isolated author clients,
trusted tests, Astra-high review, authenticated human feedback and bounded fixes.
See factory/evidence.md for executed checks and outstanding live activation.
Work order: docs/work/FACTORY-001.md. Human merge required; no product code.

```factory-handoff
{"runner":"codex","task":"docs/work/FACTORY-001.md","owner":"Zerosteps1"}
```
PR_BODY
````

4. Mensch prüft und merged den Bootstrap-PR; kein Agent pusht auf `main` oder merged. Für die anschließenden Settings-Prüfungen zusätzlich kurzlebige `FACTORY_PUBLISHER_APP_JWT` und `FACTORY_WRITER_APP_JWT` bereitstellen.
5. `settings.py inspect`, dann `settings.py diff` prüfen und `settings.py apply` bewusst ausführen. Das installiert zwei aktive Rulesets: Pflichtchecks ohne Bypass sowie Default-Branch-Updates nur durch menschliche PR-Merges. CODEOWNER-Freigabe und auf die Publisher-App gebundene Checks bleiben erforderlich. Das Credential-Environment `factory-control` darf ausschließlich den Default-Branch zulassen.
6. Environment-Secrets einrichten: `OPENAI_API_KEY`, `FACTORY_PUBLISHER_APP_PRIVATE_KEY`, `FACTORY_WRITER_APP_PRIVATE_KEY`; für automatische Autoren zusätzlich `CONTEXT7_API_KEY`, bei Claude `ANTHROPIC_API_KEY`. Keine dieser Credentials als Repository-Secret oder Datei ablegen. [OpenAI-Schlüssel](https://platform.openai.com/api-keys), [Context7-Zugang](https://context7.com/docs/resources/all-clients). `inspect` erneut ausführen; leeres Diff und vorhandene Secret-Namen beweisen noch keinen funktionierenden Lauf.
7. Image/Client-Smoke, authentifizierten Modell-/MCP-Lauf und [Smoke-PR](docs/work/FACTORY-SMOKE.md) ausführen. Run-/Check-IDs, Head-/Base-SHAs, echte Korrektur und erneutes Review dokumentieren. Erst dann Betrieb freigeben. Ein von Gabriel selbst erstellter PR benötigt einen anderen berechtigten menschlichen Reviewer; Schutzregeln dafür nicht lockern.

## Orientierung

| Pfad | Inhalt |
|---|---|
| `AGENTS.md`, `factory/policy.md`, `factory/config.json` | Verbindliche Grenzen, Modell, Budgets und Identitäten |
| `.agents/skills/`, `.agents/roles.json` | Gemeinsame Quellen der vier Skills und Rollen |
| `.codex/`, `.claude/`, `CLAUDE.md`, `.mcp.json` | Daraus erzeugte native Client-Adapter |
| `.github/workflows/`, `tools/factory/` | Dispatcher, Prüfungen, Review, begrenzte Korrektur und Settings |
| `factory/review.schema.json`, `factory/github-settings.json` | Reviewvertrag und gewünschte GitHub-Durchsetzung |
| `docs/work/` | Versionierte Aufträge und Akzeptanzkriterien |

Nur dieses Repository, der freigegebene Auftrag und öffentliche Herstellerdokumentation sind Quellen. Frühere Projekte, Workbrain, private Chats, Notizen und persönliche Agentenkonfiguration sind ausgeschlossen.
