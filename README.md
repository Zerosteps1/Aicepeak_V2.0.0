# Aicepeak

Produktquelle: [AICEPEAK_NORDSTERN.md](AICEPEAK_NORDSTERN.md). Der Inhalt bleibt unverändert; `northstar_approved: false` und `product_checks_ready: false` sperren Produktentwicklung bis zur ausdrücklichen Freigabe und passenden Produktprüfungen.

Die Softwarefabrik ist auf `main` installiert; die GitHub-Schutzregeln und benötigten Environment-Secrets sind geprüft aktiv. **Der Review-Fix-Durchlauf ist seit 29.10.2026 live abgenommen (PR #20); die Geräte-, Konkurrenz- und Identitäts-Gegenproben stehen noch aus.** Maßgeblich sind [Policy](factory/policy.md), [Konfiguration](factory/config.json) und [echte Prüfnachweise](factory/evidence.md). Keine alten Projekte, privaten Chats, Workbrain-Inhalte oder persönlichen Agenten-Memories als Projektquelle.

## Gemeinsamer Einstieg für Gabriel und Felix

Gabriel nutzt `Zerosteps1`; Felix nutzt `truFelix-Zentru` und `ftrutschnig`. Beide Felix-Konten sind verifiziert und gleichberechtigt konfiguriert. Jeder verwendet seine eigene GitHub-Anmeldung und einen eigenen zeitlich begrenzten ChatGPT-Business-Codex-Token. Eine Freigabe über das zweite eigene Konto ist keine unabhängige menschliche Freigabe.

Ein sauberer Control-Checkout bleibt auf `main`; Codearbeit erfolgt in einer getrennten Arbeitskopie. Kein `git pull` oder Branchwechsel über fremde uncommittete Änderungen hinweg.

```sh
git clone https://github.com/Zerosteps1/Aicepeak_V2.0.0.git Aicepeak-factory
cd Aicepeak-factory
git switch main
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py check --root .
```

Benötigt: Python >=3.11, Git, gh mit persönlicher Anmeldung, Docker für isolierte Autoren/Tests, Codex CLI exakt 0.164.0 für den lokalen Reviewer. Prüfer-Versionen und Hashes: [tools.lock.json](factory/tools.lock.json). Der Doctor prüft Voraussetzungen; auch ein positiver Befund ist keine Live-Abnahme. Persönliche globale Konfiguration wird nicht verändert.

Auf jedem Reviewer-Gerät einmal den eigenen Token interaktiv im Schlüsselbund hinterlegen:

```sh
security add-generic-password -a "$USER" -s aicepeak-factory-codex-access-token -w
python3 tools/factory/local_review.py --smoke
```

Der Publisher-App-Schlüssel wird getrennt und nur auf vertrauenswürdigen Maintainer-Geräten benötigt: Schlüsselbund-Dienst `aicepeak-factory-publisher-key`, Inhalt base64-kodierter PEM; alternativ `FACTORY_PUBLISHER_APP_PRIVATE_KEY` im vertrauenswürdigen Prozess. Den Writer-Schlüssel nicht an den Reviewer verteilen. Keine Tokens oder PEM-Inhalte in Chat, Git, PR-Text oder Modell-Shell. Details und Token-Grenzen: [Clients](factory/clients.md#senior-reviewer-maintainer-local).

## Arbeiten und PR-Feedback

Autor-Container und native Skills:

```sh
export FACTORY_DOCKER_HOST="$(docker context inspect --format '{{.Endpoints.docker.Host}}')"
docker build -f factory/Dockerfile -t aicepeak-factory-clients:codex-0.164.0-claude-2.1.311 factory
python3 tools/factory/clients.py smoke --root .
python3 tools/factory/clients.py launch --root . --runner claude
```

Bei `docker-credential-desktop: executable file not found` den `Contents/Resources/bin`-Ordner der tatsächlichen Docker-App temporär in PATH aufnehmen; auf Gabriels Mac heißt sie `Docker 2.app`. Keine Credential-Store-Einstellungen löschen. Der Launcher übernimmt bewusst keine persönliche Docker-Konfiguration; `FACTORY_DOCKER_HOST` bezeichnet den eigenen lokalen Docker-Endpunkt.

Die Factory nutzt `factory-start`, `factory-change`, `factory-review`, `factory-fix-review`. Kanonischer Inhalt liegt in `.agents/skills`; die Claude-Adapter werden daraus erzeugt und auf Drift geprüft. Der Container startet mit leerem persönlichen Kontext, expliziten MCPs und schreibgeschützten Regeln. Ein gewöhnlicher Host-Start ist nicht technisch gleichwertig isoliert. Insbesondere `codex` direkt im Repository kann die internen Broker-MCP-Adressen nicht erreichen.

Der lokale Claude-Autor benötigt einen Console-API-Zugang im Broker; die GitHub-Korrektur authentifiziert sich über die bereits live geprüfte Workload Identity Federation. Der **Codex-Reviewer** verwendet Business und benötigt keinen `OPENAI_API_KEY`. Der optionale isolierte **Codex-Autor** hat bisher nur einen API-Key-Pfad; Business-Auth mit sicheren Broker-Limits ist noch nicht nachgewiesen. Deshalb bleibt er für automatische Korrekturen gesperrt. Kein stiller Wechsel des Autor-Clients. Siehe [offene Grenzen](factory/evidence.md).

Aus dem sauberen Control-Checkout, mit separatem sauberen Kandidaten-Branch:

```sh
python3 tools/factory/session.py preflight --candidate /pfad/zum/kandidaten --task docs/work/AUFTRAG.md
python3 tools/factory/session.py submit --candidate /pfad/zum/kandidaten --task docs/work/AUFTRAG.md --runner claude --title 'Konkrete Änderung' --body-file /pfad/zur/pr-beschreibung.md
python3 tools/factory/session.py watch --pr 123
python3 tools/factory/session.py response --pr 123 --question 'Welche Voraussetzung fehlt für diesen Test?' --post
```

Pfade und PR-Nummer ersetzen. `preflight` ist eine quellbasierte Beratung und behauptet keine ausgeführten Tests. `submit` prüft den Stand erneut, erstellt zunächst einen Draft und markiert ihn nur nach vollständigem `pass` und erneuter Head-/Base-Prüfung als bereit. Bei einem Standwechsel bleibt er Draft; ausdrücklich erlaubte unvollständige Vorprüfungen ebenfalls. `watch` läuft auf dem jeweiligen eingeschalteten Gerät, nicht heimlich in GitHub. Es verarbeitet neue authentifizierte Reviewaufträge und erhält die konfigurierte automatische Korrektur. Ohne laufenden lokalen Watcher startet GitHub keinen Prozess auf einem Laptop; manueller Einstieg ist `local_review.py --pr 123`.

Normale Kommentare, Inline-Kommentare und Reviews bestätigter Maintainer lösen über die GitHub-Dispatcher eine erneute Prüfung aus. Geändertes Feedback macht den alten Kontext ungültig. Der Reviewer beantwortet Fragen und trennt Defekte von Erweiterungswünschen; berechtigte Findings gehen an denselben Autor-Runner. Sachliche Einwände und fehlende Voraussetzungen werden sichtbar an Menschen übergeben. Threads werden nicht automatisch geschlossen. `response` verändert keinen Code und keinen Gate-Status; ohne `--post` bleibt die Antwort lokal. Es gibt keinen vorgetäuschten automatischen `/ai response`-Slash-Befehl.

**Alle wartenden PRs prüfen.** Auf einem eingerichteten Maintainer-Gerät, aus dem sauberen Control-Checkout auf aktuellem `main`; mit Ctrl-C beenden:

```sh
while true; do
  for pr in $(gh pr list --repo Zerosteps1/Aicepeak_V2.0.0 --label awaiting-senior-review --json number --jq '.[].number'); do
    python3 tools/factory/session.py watch --pr "$pr" --once
  done
  sleep 60
done
```

Nach jedem Merge auf `main` den Control-Checkout aktualisieren (`git pull --ff-only`) und offene PRs per „Update branch“ auf den neuen Stand bringen; erst dann prüft die Fabrik sie erneut.

## Review und Korrektur

PR → vertrauenswürdiger Snapshot → secretfreie deterministische Tests → Reviewauftrag → exklusiver GitHub-Claim → frische werkzeuglose Astra/high-Sitzung auf einem Maintainer-Gerät → serialisierte GitHub-Veröffentlichung → gegebenenfalls isolierter Claude-Autor → geprüfter Writer-Push → neue Tests und neues Review → menschliche Freigabe/Merge.

Zwei Geräte dürfen denselben Auftrag beobachten; nur eines erhält die Zuständigkeit und startet das Modell. Das andere überschreibt kein Ergebnis. Nur die vorgesehene Publisher-App veröffentlicht die Pflichtchecks. Ergebnis und Freigabe sind an PR, Head, Base, Policy und echte GitHub-Läufe gebunden. Persönliche Business-Tokens bleiben lokal. Der Reviewer bekommt keine Shell-/Schreibwerkzeuge.

Maximal zwei Korrekturrunden und sechs beanspruchte Reviews je PR; Fehler, Abbruch und Dry-run erstatten keinen Reviewplatz. Fehlgeschlagene Veröffentlichungen geben genaue Wiederaufnahme-IDs aus. Eine aufgegebene Zuständigkeit wird nicht automatisch gestohlen: nach Prüfung bewusst einen neuen Lauf starten, der alte Ergebnisse und Korrekturfreigaben widerruft:

```sh
gh workflow run factory.yml --repo Zerosteps1/Aicepeak_V2.0.0 --ref main -f pr=123 -f retry=true
```

Es gibt keine automatische Merge-Berechtigung. Beide App-gebundenen Checks laufen bei jedem PR; mit zwei grünen Checks entscheidet Gabriel oder Felix selbst über den Merge, eine zweite menschliche Freigabe ist nicht vorgeschrieben. CODEOWNERS hält die Zuständigkeit fest. Gabriel und Felix können einen hängenden PR bewusst per Bypass mergen (nur über den PR, von GitHub protokolliert, Grund als PR-Kommentar); Agents und Bots haben keinen Bypass. Der vollständige Soll-/Ist-Abgleich vom 28.10.2026 meldete keine Abweichungen; [Nachweis](factory/evidence.md#live-aktivierung-am-28102026).

**Status auf einen Blick.** `awaiting-senior-review`: deterministische Prüfungen bestanden, das verbindliche Astra-Review ist noch nicht gelaufen; ein Maintainer startet es mit `session.py watch --pr <Nummer>`. `needs-author-action`: Tests oder Review blockieren, der Autor ist am Zug. Ohne diese Labels und mit zwei grünen Pflichtchecks entscheidet ein Mensch über den Merge. Drafts haben rote Pflichtchecks, aber kein `needs-author-action`. Offene Reviews: `gh pr list --repo Zerosteps1/Aicepeak_V2.0.0 --label awaiting-senior-review`. Die Labels zeigen den letzten Pipeline-Lauf; verbindlich bleiben die Pflichtchecks.

## Stand der Aktivierung und verbleibende Abnahme

1. Menschlicher Bootstrap und Linux-Reparatur sind mit PR #9 und #11 übernommen. Die einmalig genehmigte Ausnahme für #11 ist geschlossen; beide Pflichtchecks sind wieder aktiv. Keine dauerhafte Bootstrap-Ausnahme übernehmen.
2. Environment `factory-control`: ausschließlich Branch `main`; Publisher-/Writer-Schlüssel und `CONTEXT7_API_KEY` vorhanden. Die beiden Rulesets entsprechen der versionierten Vorgabe. `settings.py inspect`/`diff` dient dem erneuten Abgleich; `apply` ist nur bei einem tatsächlich geprüften Unterschied nötig. Kein OpenAI-API-Key für den Reviewer.
3. Host-/Containergrenze und Gabriels Astra-Anmeldung wurden getestet; die authentifizierte Claude-Skill-Erkennung, native MCP-Aufrufe und Felix' eigener Reviewer-Smoke sind gesonderte offene Nachweise. Die Syntax-/Unit-Prüfung ersetzt sie nicht.
4. [Smoke-PR](docs/work/FACTORY-SMOKE.md): sauberer Gegenfall, semantischer Defekt, Reviewer-Finding, Writer-Korrektur, echter Folgetrigger, neues Review und menschliches Feedback sind mit PR #20 live bestanden ([Nachweis](factory/evidence.md#status-on-2026-10-29-live-review-fix-acceptance-passed)). Offen: Felix' eigenes Reviewer-Gerät, zwei Geräte für denselben Claim, neuer Head während eines Reviews, fremde App mit gleichem Checknamen. Erst danach gilt die vollständige Betriebsabnahme.

```sh
python3 tools/factory/verify.py --root .
python3 tools/factory/clients.py smoke --root .
python3 tools/factory/local_review.py --smoke
```

## Wegweiser

| Bereich | Verbindlicher Inhalt |
|---|---|
| `AICEPEAK_NORDSTERN.md` | Kanonisches Produktziel; keine inhaltliche Kopie |
| `AGENTS.md`, `factory/` | Regeln, Konfiguration, Reviewvertrag, Betrieb und Nachweise |
| `.agents/`, `.claude/`, `.codex/` | Gemeinsame Skills und native Adapter |
| `docs/work/` | Autorisierte Aufgaben mit überprüfbarer Abnahme |
| `.github/` | Dispatcher, getrennte Workflow-Rechte, CODEOWNERS und Templates |
| `tools/factory/` | Kleine ausführbare Werkzeuge und Regressionen |

Werkzeuge und Kosten: vorhandene Python-Standardbibliothek, gh, Docker und die zwei vorhandenen Clients genügen. Keine zusätzliche KI-Review-Plattform oder Memory-Datenbank. Business-Reviews teilen das persönliche Codex-Kontingent; Claude-WIF-Läufe bleiben API-Verbrauch, der nur soweit vorhanden durch Team-Guthaben gedeckt wird. Actions-Verbrauch und vorhandene Tarife separat beobachten; keine Zusicherung kostenloser Nutzung.
