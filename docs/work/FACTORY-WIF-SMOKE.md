# Federation separat prüfen

Status: manueller Diagnoseweg für den autorisierten Factory-Setup-Auftrag
[FACTORY-001](FACTORY-001.md); kein Nachweis einer einsatzbereiten Factory.
Die Änderung benötigt menschliche Prüfung und Merge. Sie aktiviert keine
Autor-Korrektur und ändert keine Required Checks.

## Zweck und Abnahme

Die vier IDs in [config.json](../../factory/config.json) sind öffentliche
Konfiguration. Ein `author_federation: passed` im Doctor beweist keinen Login.
Der Diagnoseweg in [factory.yml](../../.github/workflows/factory.yml) prüft:

1. GitHub gibt für genau diesen Workflow auf `main` eine OIDC-Identität aus.
2. Anthropic akzeptiert diese Identität und stellt einen kurzlebigen Token aus.
3. Das konfigurierte Claude-Autormodell beantwortet eine minimale Anfrage.

Ergebnis `passed` erfordert alle drei Schritte. HTTP-Fehler, ungültige Antworten,
unpassende Claims, fehlende Berechtigungen oder Modellfehler führen zu Exit 1.
Die Abnahme umfasst weder den Claude-Code-Runner noch Docker, Publisher/Writer,
Codex, Review-Gates oder den Korrekturablauf. Der Test erzeugt einen kleinen
API-Verbrauch im gewählten Anthropic-Workspace; Federation legt keine Abrechnung
über ein Team-Abo fest. Es gibt keinen Modellwechsel bei Fehlern.

## Voraussetzungen

- Diese Änderung wurde von einem Menschen nach `main` gemergt.
- Das Environment `factory-control` erlaubt ausschließlich `main`; eventuell
  konfigurierte menschliche Freigaben bleiben wirksam.
- Die Federation-Regel verwendet für diesen **direkten** Workflow den Claim
  `workflow_ref`, nicht `job_workflow_ref`. Letzterer gehört zu wiederverwendbaren
  Workflows. Erwarteter Wert:
  `Zerosteps1/Aicepeak_V2.0.0/.github/workflows/factory.yml@refs/heads/main`.
- Weitere Bedingungen bleiben eng: Repository-ID `1436114884`, Owner-ID
  `115100163`, `ref=refs/heads/main`, `environment=factory-control`,
  `event_name=workflow_dispatch`, Audience `https://api.anthropic.com`.
- Das am 27.10.2026 angelegte Repository verwendet GitHubs Subject-Format mit
  unveränderlichen IDs. Das exakte Subject Pattern für das Environment lautet:
  `repo:Zerosteps1@115100163/Aicepeak_V2.0.0@1436114884:environment:factory-control`.
  Kein Wildcard-Subject. In der Claude Console haben angepasste **Advanced match
  options** Vorrang vor den geführten Feldern; Änderungen erst im Schritt
  **Target** speichern. Eine spätere Umbenennung oder Übertragung verlangt eine
  erneute Prüfung dieser Bindung.
- Der Service Account ist Mitglied des konfigurierten Workspace; Regel-Scope
  `workspace:inference` genügt. Kein Admin-Scope, API-Key oder GitHub-App-Key nötig.

Ein separater Workflow namens `anthropic-wif-test` erfüllt die Workflow-Bedingung
nicht. Für den Test keine Pull-Request-Branches freischalten.

## Ausführen

Mit eigenem GitHub-Login und Actions-Schreibrecht, nach dem menschlichen Merge:

```sh
gh workflow run factory.yml --repo Zerosteps1/Aicepeak_V2.0.0 \
  --ref main -f pr=0 -f wif_smoke=true
gh run list --repo Zerosteps1/Aicepeak_V2.0.0 --workflow factory.yml --limit 5
```

Den passenden Lauf auswählen und dessen ID verwenden:

```sh
gh run watch RUN_ID --repo Zerosteps1/Aicepeak_V2.0.0 --exit-status
gh run view RUN_ID --repo Zerosteps1/Aicepeak_V2.0.0 --log
```

Alternativ: Actions → Factory trusted pipeline → Run workflow → Branch `main`,
`pr=0`, `wif_smoke=true`. Nur **Anthropic federation smoke** läuft. Die normalen
PR-Jobs überspringen diesen Diagnosemodus und veröffentlichen keine Gates.

Die Ausgabe enthält ausschließlich Status, Stufennamen, angefordertes Modell,
Scope, Ablaufdauer und Tokenanzahlen. Tokens bleiben im Speicher des Prozesses;
keine Tokens oder Rohantworten in Logs, Artefakten oder `$GITHUB_ENV`.
Ein `token_exchange: HTTP 400/401/403` lässt sich anhand des Zeitpunkts in der
Claude Console unter **Authentication history** untersuchen. Modell-/Quotafehler
erscheinen als `claude_message`; ein erfolgreicher Austausch allein genügt nicht.

## Lokale Prüfung und Quellen

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -I -m unittest discover \
  -s tools/factory/tests -p test_wif_smoke.py -v
```

Die Tests ersetzen nur HTTP, prüfen den echten Ablauf einschließlich negativer
Fälle und geben keinen Live-Nachweis. Der lokale direkte Skriptstart blockiert
ohne den passenden Actions-Kontext. Die JWT-Claims werden lokal nur verglichen;
die kryptografische Prüfung erfolgt bei Anthropic.

Schnittstellen geprüft am 28.10.2026:
[Anthropic WIF-Referenz](https://platform.claude.com/docs/en/manage-claude/wif-reference),
[GitHub OIDC-Claims](https://docs.github.com/en/actions/reference/security/oidc).
Python-Standardbibliothek; vorhandene Action-SHA weiterverwendet; keine neue
Abhängigkeit und kein Produktstack.

## Nachweisstand am 28.10.2026

- Lokal: `verify.py` bestanden, einschließlich 76 Tests (davon neun neue
  Diagnoseprüfungen), actionlint 1.7.12, Gitleaks und Adapter-/Referenzprüfung.
- Unabhängiges Review mit GPT-6 Astra / high: keine blockierenden Befunde.
  Den Hinweis zum Schließen von HTTP-Fehlerantworten umgesetzt und erneut
  geprüft; alle neun Diagnosetests ohne Warnungen bestanden.
- Live-Federation nach menschlichem Merge von PR #7: erster Lauf
  [40683607565](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40683607565)
  scheiterte mit HTTP 401. Gabriel meldete aus Authentication history den Grund
  `match_subject_prefix`; die Screenshots zeigten das frühere Subject-Format ohne
  IDs. Nach Anpassung der Console-Regel bestand Lauf
  [40684684126](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40684684126)
  auf Main-Commit `70bb59f722f9f0c260f2524e21c93a1290891b47`. Job-Logs direkt
  geprüft: `github_oidc`, `token_exchange`, `claude_message` bestanden;
  angefordertes Modell `claude-sonnet-5-5`, Scope `workspace:developer`,
  Token-Lebensdauer 598 Sekunden, 18 Input- und 4 Output-Tokens.
  Alle normalen PR-/Review-/Korrekturjobs wurden im Diagnosemodus übersprungen.
  Kein Docker-/Autor-Integrationstest und kein Nachweis sämtlicher Schutzregeln.
- Davon getrennt: Gabriel führte den Codex-Smoke aus PR #5, Revision
  `009c010aafc9881d3e29e00b65100092fe9a7cc2`, in seinem macOS-Terminal aus und
  meldete `status=passed`, `model=gpt-6-astra`, `effort=high`,
  `auth=CODEX_ACCESS_TOKEN`, einen Turn und 7.330 Input-/15 Output-Tokens.
  Der Schlüsselbund-Dienst `aicepeak-factory-codex-access-token` wurde dort
  gefunden. Der ausführende Prüfagent konnte denselben Eintrag nicht finden;
  die Erfolgsmeldung stammt aus Gabriels Terminal. Das bestätigt diesen lokalen
  Anmelde-/Modellweg, weder eine PR-Veröffentlichung noch Felix' Einrichtung.
