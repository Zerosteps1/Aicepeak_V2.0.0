# Prüfstand und noch offene Aktivierung

## Nachtrag 28.10.2026: Anmeldung und App-Registrierung

Der lokale Codex-Smoke mit GPT-6 Astra / high wurde von Gabriel erfolgreich in
seinem Terminal ausgeführt. Der Anthropic-Federation-Smoke einschließlich einer
echten Claude-Antwort wurde anschließend in GitHub Actions direkt geprüft.
Läufe, Revisionen, Verbrauch und Grenzen stehen im
[Diagnosenachweis](../docs/work/FACTORY-WIF-SMOKE.md#nachweisstand-am-28102026).

Publisher `5510081` und Writer `5510093` sind gemäß Gabriels Zuordnung konfiguriert.
Beide bereitgestellten PEM-Dateien bestanden lokal `openssl rsa -check -noout`.
Dies allein prüft die Schlüsseldateien, nicht deren App-Zuordnung oder GitHub-Rechte.
Gabriel führte anschließend den lesenden Inspector mit kurzlebigen App-JWTs in
seinem Terminal aus und übermittelte die JSON-Ausgabe. Beide Apps, die exakten
Rechte und die Installationen im Zielrepository wurden bestätigt: Publisher
`176168187`, Writer `176168111`; keine App-/Identitätsblocker.
Der Agent hat die Ausgabe geprüft, die API-Abfrage aber nicht selbst ausgeführt:
aus seiner Shell scheitert der direkte GitHub-Netzwerkzugriff; der Connector
unterstützt die benötigten Administrationsendpunkte nicht.

Die erste Ausgabe zeigte eine Aktivierungslücke: `factory-control` hatte
`deployment_branch_policy: null`, keine Branch-Regeln und noch keine App-Secrets.
Gabriel setzte die Environment-Grenze und führte den Inspector erneut aus:
`protected_branches: false`, `custom_branch_policies: true`, exakt eine Regel
`name: main`, `type: branch` (Regel-ID `64660737`). Diese zweite Ausgabe bestätigt
die Branch-Grenze vor dem Speichern der Secrets. Factory-Rulesets und App-Secrets
waren weiterhin nicht vorhanden. Das gemeldete fehlende `OPENAI_API_KEY` gehört zum alten
Main-Workflow; für den vorgesehenen lokalen Business-Reviewer wird kein solcher
Schlüssel verlangt. Die Umstellung ist erst mit dem geprüften Merge von PR #5
beziehungsweise dessen korrigiertem Stand wirksam.

Beim unabhängigen Review wurde der App-JWT-Transport korrigiert: `gh` verwendet
für `GH_TOKEN` das Schema `token`, App-JWTs verlangen `Bearer`. `settings.py`
nutzt für diese beiden GET-Abfragen jetzt explizites Bearer-HTTPS ohne
Weiterleitungen; die menschliche Administration bleibt bei gh. Vier neue
Regressionen prüfen Header/Transport, erlaubte Endpunkte, Fehlerausgabe und
Weiterleitungsschutz. Vor der Korrektur schlugen sie fehl, danach bestanden
alle 19 Settings-Tests und die vollständige Suite mit 80 Tests. Die anschließende
authentifizierte App-Prüfung stammt aus Gabriels Terminal, wie oben ausgewiesen.

PRs #4, #5 und #6 waren bei dieser Prüfung weiterhin offene Entwürfe. Der
erfolgreiche lokale Reviewer-Smoke bedeutet deshalb noch keine Umstellung des
Main-Workflows. Keine App-Secrets hochgeladen, keine Rulesets aktiviert und
keine Review-Fix-Schleife als abgenommen erklärt. Die folgenden Angaben vom
27.10. bleiben historische Nachweise des ursprünglichen Bootstrap-Stands.

## Historischer Bootstrap-Stand

Stand: 27.10.2026. **Factory lokal implementiert; noch nicht einsatzbereit.** Dieser Nachweis trennt ausgeführte Prüfungen von ausstehenden Live-Szenarien. Kein Merge und keine administrativen Remote-Änderungen wurden vorgenommen.

## Ziel und Voraussetzungen

Öffentliche GitHub-API tatsächlich gelesen: `Zerosteps1/Aicepeak_V2.0.0`, Repository-ID `1436114884`, öffentlich, konfigurierter Default `main`; Branch-Liste leer, Contents-Endpunkt 404. Erneute Branch-Abfrage am Abschluss weiterhin leer. Owner `Zerosteps1`, User-ID `115100163`, durch Nutzer als Gabriel bestätigt. Felix noch nicht benannt. Die SSH-Origin lautet `git@github.com:Zerosteps1/Aicepeak_V2.0.0.git`.

Das Zielrepository enthält noch keinen Nordstern; `northstar_path:null` ist der ausdrückliche Blocker, kein Ersatzdokument. Keine alten Projekte, Vorarbeiten oder persönliche Wissenssammlungen wurden für die Factory übernommen. Ein außerhalb des Zielrepositorys vorhandenes Dokument wurde nicht als Repo-Quelle importiert.

`gh`/GitHub-Connector lieferten keine gültige Anmeldung; SSH/Git-Netzwerkzugriff war in dieser Umgebung nicht möglich. Öffentliche HTTPS-Abfragen über den zugelassenen curl-Aufruf funktionierten. Plan-, Actions-, Environment- und Administrationsrechte sind daher nicht authentifiziert verifiziert. Das Repository ist öffentlich; eine private Nutzung benötigt erneute Tarif-/Featureprüfung. **Keine Rulesets sind durch diese Einrichtung bereits aktiviert.**

Lokal geprüft: Git 2.50.1, gh 2.87.0, Codex 0.164.0, Claude Code 2.1.311, Python 3.15.2, Node 25.8.1, npm 11.11.0, Docker 29.1.3, Gitleaks 8.30.1. Actionlint 1.7.12 wurde aus dem offiziellen Release geladen und mit dessen SHA256 geprüft. Docker-Daemon nicht erreichbar. CLI-Hilfe und native Konfigurationsquellen sind in [Clients](clients.md) belegt. Die Factory benötigt nur Python-Standardbibliothek plus festgelegte Prüf-/Clientwerkzeuge; dies legt keinen Produktstack fest.

## Ausgeführte lokale Prüfungen

- Python-Syntax, JSON/TOML, native Adapterdrift, interne Dokumentationslinks, vollständige Action-SHAs und kontrollierte Smoke-Rechnung.
- Actionlint über alle Workflowdateien. Einzige Kompatibilitätsbehandlung: die durch GitHub dokumentierte, von Actionlint 1.7.12 noch nicht verstandene Zeile `cache-mode: none` wird zuerst exakt geprüft und nur für dessen Parser entfernt. Alle übrigen Felder werden vollständig geprüft. Kein allgemeines Wegfiltern von Linterfehlern.
- Gitleaks mit vertrauenswürdiger Regeldatei, leerer Ignore-Datei und deaktivierten Inline-Ausnahmen. Eine eng begrenzte UND-Ausnahme betrifft ausschließlich den öffentlichen internen Broker-URL-Literal in `clients.py`, keinen Credentialwert.
- Unit-/Regressionstests prüfen Reviewvertrag, SHA-/App-/Run-Bindung, drei Runden, monotones Budget trotz Force-Push, doppelte Verarbeitung, Draft→ready, fehlenden Modellschlüssel, neue menschliche Rückmeldung, Pfad-/Rename-Grenzen, tatsächlichen Git-Rename, atomare Ref-Aktualisierung, Settings-Diff/Idempotenz und Broker-/Worker-Grenzen. GitHub/Provider-Transporte werden simuliert; das ist kein Live-Nachweis.
- Negativprobe: eine absichtlich gebrochene Candidate-Validierung bleibt trotz `unittest.py`/`sitecustomize.py` im Candidate durch die isoliert gestartete vertrauenswürdige Suite rot. Bestehende Basistests laden ausdrücklich Candidate-Code; fehlende Tests zählen nicht als Erfolg.
- Positives Gegenbeispiel: vollständiger korrekter Reviewvertrag ohne künstliche Findings wird angenommen. Ein echter kostenpflichtiger Astra-Lauf dieses Gegenbeispiels steht aus.
- Der Doctor wurde gegen den tatsächlichen lokalen Stand ausgeführt und meldet offene Voraussetzungen. Zusätzliche Diagnoseproben prüfen unter anderem, dass auch ein scheinbar vollständiger lokaler Stand keine Live-Freigabe erzeugt und Secretwerte nicht ausgegeben werden.
- Der npm-Lockfile wurde gegen tatsächliche öffentliche Paketmetadaten einschließlich Integrity-Werten erstellt und mit frischem temporärem Home ohne persönliche npm-Konfiguration offline geprüft.

Reproduzierbar: `python3 -I -m unittest discover -s tools/factory/tests -v` und `python3 tools/factory/verify.py --root .`. Wenn Actionlint nicht im PATH liegt: `--actionlint /absoluter/pfad/actionlint`. Abschließender lokaler Lauf: **67 Tests erfolgreich**, vollständiger Verifier Exit 0, `git diff --check` Exit 0. Doctor Exit 2 (offene Voraussetzungen), Modell-Smoke Exit 1 (fehlender API-Schlüssel), Container-Smoke Exit 2 (Docker-Zugriff verweigert). Diese Datei behauptet keine nicht ausgeführten Live-Tests.

## Dokumentations- und Modellzugang

Der OpenAI-Docs-MCP `https://developers.openai.com/mcp` wurde direkt mit `initialize`, `tools/list`, `search_openai_docs` und `fetch_openai_doc` abgefragt; Server `openai-docs-mcp` 1.0.0. Context7 `resolve-library-id` und `query-docs` wurden über den vorhandenen Connector benutzt. Generische technische Fragen, keine privaten Diffs oder Anforderungen. **Dies beweist nicht** die Erreichbarkeit aus den späteren isolierten Clients; deren MCP-Smoke steht aus.

Zentral konfiguriert: `gpt-6-astra`, `reasoning.effort=high`, kein Fallback. Der tatsächliche Befehl `python3 tools/factory/engine.py model-smoke` blockierte vor dem Netzwerkaufruf wegen fehlendem `OPENAI_API_KEY`. Weder eine erfolgreiche Modellantwort noch API-Berechtigung wird behauptet. Vor Aktivierung muss derselbe Befehl mit dem vorgesehenen Zugang Modell, Antwort-ID und Erfolg melden.

## Unabhängige Prüfung und bearbeitete Befunde

Ein unabhängiger Subagent wurde tatsächlich mit GPT-6 Astra / high eingesetzt. Das ist ein lokaler Reviewnachweis und kein Beweis für den noch nicht eingerichteten zentralen API-Zugang.

Erste Prüfung: Budgetverlust bei Force-Push, fehlende Prüfung der Rename-Quelle, Rename als Kopie beim Writer, sowie blockierter Draft→ready-Übergang. Behoben durch PR-weites authentifiziertes Ledger, Prüfung beider Pfade, vollständige Delete/Add-Erfassung und Draft-Bindung; gezielte Regressionen vorhanden.

Zweite Prüfung: Testentdeckung durch Candidate-Imports, Basistests ohne Candidate-Ziel, ungezählte GitHub-Job-Reruns, Abbruch bei unverändertem Kontext, fehlende atomare Expected-Head-Prüfung und irreführender Dispatcher-Retry. Behoben durch isolierten Teststart, explizites Candidate-Ziel, Run-Attempt-Bindung und frischen kostenpflichtigen Retry, serialisierte Läufe mit gezieltem Abbruch veralteter Runs, GraphQL `updateRefs.beforeOid` und genau einen menschlichen Retry-Einstieg. Autorberichte und Antworten auf menschliche Fragen werden als überprüfbare PR-Rückmeldung erhalten. Die abschließende unabhängige Nachprüfung bestätigte alle Korrekturen ohne verbleibenden belegten Blocker; sie führte 65 Tests selbst erfolgreich aus. Danach ergänzten zwei lokale Diagnose-Regressionen die Gesamtsuite auf 67.

## Live-Abnahme nach menschlichem Bootstrap

| Szenario | Lokal vorhanden / geprüft | Noch notwendiger Live-Beleg |
|---|---|---|
| Frischer Checkout, gleiche Regeln/Skills | Adaptergenerierung und Driftprüfung | Native Discovery und tatsächliche Skill-Ausführung beider Clients |
| Isolierter Kontext | Worker-/Proxy-Grenzen und Symlink-Negativtests | Container-Smoke: fremder harmloser Hostinhalt nicht lesbar; keine fremden Home-Mounts |
| Zulässiger PR | Dispatcher-/Vertragstests | Zwei App-Checks plus Astra-high starten tatsächlich |
| Defekt und Fix | [Smoke-Auftrag](../docs/work/FACTORY-SMOKE.md), reale Git-Patchprobe | Echter Autor-Fix, App-Push, neuer Prüflauf, sauberes Gegenbeispiel |
| Menschliches Feedback | Identität/PR-Zuordnung, Neulesen, geänderter Kontext | Kommentar, Inline-Kommentar und Review jeweils mit verständlicher Rückmeldung |
| Alter Head/Basis/Run | Negativtests und frische Bindungsprüfung | Veralteter echter Check kann nicht mergen; alter Run wird abgebrochen |
| Fehlende Credentials/Schema/API | Lokale fail-closed Tests | Bewusst fehlerhafter API-Lauf bleibt rot |
| Kontrolle im PR geändert | Basispolicy/Orchestrierung und schreibgeschützte Autoradapter | Reale PR-Regeländerung beeinflusst nicht ihre eigene Prüfung |
| Secret-/Identitätsgrenze | getrennte Jobs, Broker, App-Scope-Prüfung | Tests ohne Secrets; Agent kann weder `main` aktualisieren noch mergen |
| Fremder gleichnamiger Check | erwartete App-ID im Ruleset, Vertragsnegativtest | Fremde Check-App erfüllt Pflichtcheck nicht |
| Budget/Parallelität | Force-Push/Rerun/Duplicate/CAS-Regressionen | Drei Runden und konkurrierende echte Aktualisierung führen korrekt zur Übergabe |
| MCPs | getrennte direkte Dokumentationsabfragen | Beide nativen Clients erreichen nur erlaubte Server; generische Abfragen erfolgreich |

Erst nach diesen Belegen darf der Status „einsatzbereit“ gesetzt werden. Erfolgreiche GitHub-Run-/Check-IDs und geprüfte SHAs im Smoke-PR dokumentieren und die dauerhafte Abnahme anschließend per PR hier ergänzen.

## Werkzeug- und Kostenentscheidung

Bestehende Codex-/Claude-CLI, GitHub Actions/API, zwei eng berechtigte Apps, Python und kleine freie Prüfwerkzeuge genügen. Kein zusätzliches KI-Review-Abo, keine Agentenplattform, keine Produktinfrastruktur gekauft. Docker dient ausschließlich der Prozessgrenze der Factory. Context7 und OpenAI Docs liefern öffentliche technische Dokumentation; kein Projekt-Memory und keine externe Indexierung.

Anfängliche Grenzen: höchstens 3 automatische Korrekturen, 5 USD reservierte Kosten je Autor-Lauf und 25 USD je PR; 900 Sekunden Ausführungsgrenze. Die Reservation ist konservativ, fehlgeschlagene/abgebrochene Läufe geben sie nicht automatisch frei. Providerabrechnung, laufende angefangene Requests und GitHub-Actions-Verbrauch bleiben zusätzlich zu beobachten. Die Preise stehen versioniert in `factory/config.json`, Quellen in [Clients](clients.md) und [GitHub-Betrieb](github.md). Öffentliches Repository bedeutet nicht kostenfreie Modellaufrufe. Für private Repositories keine pauschale Annahme kostenloser Code-Security-/Secret-Protection-Produkte.
