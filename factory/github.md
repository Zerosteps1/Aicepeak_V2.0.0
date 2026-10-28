# GitHub-Betrieb und technische Quellen

Stand: 27.10.2026. Implementierung und Sollzustand sind versioniert; **keine Remote-Durchsetzung ist bisher aktiviert**. Tatsächliche Belege und Blocker stehen in [evidence.md](evidence.md), die Bootstrap-Reihenfolge in [README](../README.md). Die Datei beschreibt die Factory, keine Produktarchitektur.

## Einstellungen prüfen und anwenden

`factory/github-settings.json` enthält die Schutzvorgaben; `factory/config.json` die verifizierten Identitäten, App-IDs und den Default-Branch. Noch fehlende App-IDs blockieren die Aktivierung. Gabriel ist als `Zerosteps1` eingetragen; Felix wird erst nach Verifikation ergänzt.

```sh
python3 tools/factory/settings.py codeowners
python3 tools/factory/settings.py inspect
python3 tools/factory/settings.py diff
python3 tools/factory/settings.py apply
```

`codeowners` prüft Login, numerische ID und Schreibberechtigung über GitHub und schreibt die lokale CODEOWNERS-Datei. Sie wird per PR übernommen. `inspect` und `diff` sind lesend. `apply` verändert ausschließlich die verwalteten Einstellungen, verweigert bekannte Blocker und liest den Zustand erneut zurück. Andere Rulesets bleiben bestehen. Apps, Secrets, Tarife und Merges werden nicht automatisch eingerichtet.

Für Administration ist eine separat angemeldete menschliche `gh`-Identität nötig. Für die App-Prüfung werden kurzlebige `FACTORY_PUBLISHER_APP_JWT` und `FACTORY_WRITER_APP_JWT` als Secret-Umgebungsvariablen benötigt: echte App-JWTs, keine Installation-Tokens. Diese werden nach der [offiziellen JWT-Anleitung](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-json-web-token-jwt-for-a-github-app) aus App-ID und privatem Schlüssel erzeugt. Das Prüfprogramm schreibt oder druckt sie nicht. Es prüft `/app`, Installation im Zielrepository, exakte Rechte und nicht suspendierten Zustand. Die Automatik erzeugt ihre kurzlebigen, auf das Zielrepository und benötigte Rechte beschränkten Installation-Tokens selbst. [Installation-Tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)

| Identität | Rechte | Verwendung |
|---|---|---|
| Publisher-App | Contents read, Pull requests write, Checks write, Actions read, Metadata read | Authentifizierte Checks, PR-Rückmeldungen, Label und Budgetledger |
| Writer-App | Contents write, Pull requests write, Metadata read | Ausschließlich validierter Patch auf den zugehörigen PR-Branch |
| Dispatcher-GITHUB_TOKEN | Contents read, Pull requests read, Checks read, Actions write | Metadaten prüfen, veraltete Runs abbrechen, zentralen Lauf starten |
| Review-/Test-Host | Je Job ausgewiesene Leserechte | Prüfmaterial beziehen; kein GitHub-Token im Modellworker/Testcontainer |

Apps haben keine Administration-, Workflow- oder Bypassrechte. `contents:write` beziehungsweise PR-Schreibrechte allein verbieten Merges nicht; die folgenden Rulesets erzwingen die Identitätsgrenze.

## Durchsetzung nach Aktivierung

Zwei Rulesets gelten gemeinsam auf dem tatsächlichen Default-Branch:

1. **Qualität, ohne Bypass:** PR-Pflicht, mindestens eine menschliche CODEOWNER-Freigabe, Verwerfen veralteter Freigaben, Freigabe des letzten Pushes, gelöste Reviewthreads, aktueller Basisstand, Schutz vor Löschen/Force-Push sowie `factory/deterministic` und `factory/senior-review` mit erwarteter Publisher-`integration_id`.
2. **Updates nur durch Menschen:** Default-Branch-Updates gesperrt; ausschließlich verifizierte menschliche User erhalten PR-only-Bypass dieser zweiten Regel. Die erste Regel bleibt für alle unverändert verpflichtend. Kein Agent/Bot erhält eine Ausnahme, kein Auto-Merge.

Die Regelkombination folgt der dokumentierten [Aggregation von Rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets#about-rule-layering). Reale Negativproben bleiben erforderlich. Administratoren können Einstellungen grundsätzlich verändern; die Factory behauptet keine Unveränderlichkeit gegenüber dem Repository-Administrator. [Rulesets-API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset), [verfügbare Regeln](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)

CODEOWNERS aus dem geschützten Basisstand schützt alle Dateien, insbesondere Regeln und sich selbst. Eine Änderung im PR ersetzt dessen eigene Owner nicht. Bei nur einem Maintainer kann Gabriel App-erstellte PRs freigeben; für einen von Gabriel selbst erstellten PR wird ein weiterer berechtigter menschlicher Reviewer benötigt. [CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

Das Environment `factory-control` erlaubt genau den Default-Branch vom Typ `branch`, keine gleichnamigen Tags oder Wildcards. Darin liegen `OPENAI_API_KEY`, beide App-Privatschlüssel und für die Autoren `CONTEXT7_API_KEY` sowie bei Claude `ANTHROPIC_API_KEY`. Gleichnamige Repository-Secrets werden als unsicherer Zustand abgewiesen. Default-GITHUB_TOKEN: read, keine PR-Freigabe. Nur GitHub-eigene Actions, volle SHA-Pins und `cache-mode:none`. [Environments](https://docs.github.com/en/rest/deployments/environments#create-or-update-an-environment), [Branch-Policies](https://docs.github.com/en/rest/deployments/branch-policies#create-a-deployment-branch-policy), [Actions-Rechte](https://docs.github.com/en/rest/actions/permissions), [cache-mode](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#cache-mode)

Das öffentliche Ziel wurde verifiziert; Tarif und administrative Endpunkte nicht. Bei einem privaten persönlichen Repository verlangt die aktuelle Dokumentation Pro für diese Rulesets/CODEOWNERS und Environment-Funktionen. `settings.py` blockiert private Aktivierung ohne belegten passenden Plan. Zusätzliche Environment-Reviewfreigaben sind tarifabhängig und werden hier nicht vorausgesetzt. [Verfügbarkeit](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets), [Environment-Tarife](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)

## Ausführbarer Review-Fix-Ablauf

`factory-dispatch.yml` verarbeitet PR-Erstellung, neue Commits, Wiederöffnung, Ready/Draft, Änderungen, menschliche PR-Kommentare und Default-Branch-Updates. Es lädt nur die fixierte geschützte Workflowrevision. Für Reviews/Inline-Kommentare liefert `factory-feedback.yml` ohne Rechte, Checkout oder Secrets nur numerische Referenzen. Der vertrauenswürdige `workflow_run`-Dispatcher liest Run, Workflow, menschlichen Autor und PR-Zuordnung erneut über GitHub. Manipulierte Titel oder gleich formatierte Kommentare sind keine Autorisierung. [Ereignisse](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [sicheres pull_request_target](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)

`factory.yml` läuft ausschließlich über `workflow_dispatch` auf dem geschützten Default-Branch. Seine Jobs trennen Snapshot, secretfreie Tests, werkzeugloses Astra-Review, deterministischen Publisher, Autor-Patch-Erzeugung und vertrauenswürdigen Writer. Native Dispatch-Jobchecks werden nicht als PR-Gate ausgegeben; die Publisher-App erstellt die beiden separaten Pflichtchecks am geprüften PR-Head. [Required Checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks), [Checks-API](https://docs.github.com/en/rest/checks/runs)

Jeder Lauf bindet Repository, PR, Head-, Base- und Policy-SHA, Run-ID und Run-Attempt. Prüfnachweise werden gegen authentifizierte GitHub-Run-/Workflow-/Jobdaten geprüft. Die Testorchestrierung kommt aus der Basis; Kandidatencode läuft ohne Netzwerk, Secrets, Home oder Docker-Socket im Container. Der Publisher akzeptiert kein PR-eigenes Erfolg-JSON. Nicht vollständige, übersprungene, abgebrochene oder widersprüchliche Nachweise geben nicht frei. [Run-API](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run), [Workflow-Kontext](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context)

Autorarbeit startet nur aus dem authentifizierten App-Review desselben Runs und Heads. Der Allowlist-Runner erhält keine GitHub-Zugangsdaten. Der Writer prüft Run, Artifact-ID/Digest, genau einen begrenzten Patch, Arbeitsauftrag, erlaubte Pfade und aktuellen Head; er führt keine Artefaktprogramme aus. Änderungen an Kontrollregeln sind ausgeschlossen. Ein App-Push soll den nächsten Prüflauf auslösen; dieser tatsächliche Folgetrigger ist Bestandteil des noch offenen Smoke-Nachweises. [Artefakte](https://docs.github.com/en/rest/actions/artifacts#get-an-artifact), [Folgetrigger](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)

Branch-Updates verwenden atomar [`updateRefs`](https://docs.github.com/en/graphql/reference/git#updaterefs) mit `beforeOid`, `afterOid` und `force:false`. Damit wird auch ein zwischenzeitliches Zurücksetzen auf einen Vorfahren abgewiesen. REST-`force:false` allein würde nur Fast-Forward prüfen. Quelle gelesen; echte Mutation noch nicht ausgeführt.

## Feedback, Wiederholung und Fehlerbehebung

Normale Kommentare, Reviews und Inline-Kommentare verifizierter Menschen werden im nächsten Lauf erneut gelesen. Der Review beantwortet fachlich relevante Fragen; korrigierte oder bestrittene Findings erhalten den Autorenbericht. Neues Feedback invalidiert alten Kontext. Menschliche Threads bleiben bis zur menschlichen Klärung offen. Bei erweitertem Scope muss zuerst ein überprüfbarer Auftrag im Repository freigegeben werden.

Ein PR-weites, App-authentifiziertes Ledger verweist auf echte Check-Datensätze und erhält Budgets/Runden über Rebase und Force-Push. Maximal drei automatische Korrekturen. Derselbe Kontext darf nicht doppelt verarbeitet werden. Die Serialisierung verhindert parallele Writer. Nur authentifizierte Runs für alte Heads/Basisstände werden aktiv abgebrochen; reine Titeländerungen unterbrechen keinen gültigen Lauf. Frische Standprüfungen vor jeder relevanten Stufe, vor Veröffentlichung und atomarem Push bleiben zusätzlich erforderlich. Bereits gestartete Provideranfragen können bis zum Abbruch Kosten erzeugen.

Ohne neuen Commit kann ein verifizierter Maintainer bewusst neu starten:

```sh
gh workflow run factory.yml --ref main -f pr=123 -f retry=true
```

`123` durch die konkrete PR-Nummer ersetzen. GitHubs „Re-run jobs“ wird verweigert, damit keine alten Budgetreservierungen erneut benutzt werden. Ein Retry setzt weder Runden noch Budget zurück. Bei ausgeschöpftem Budget, Konflikt, fehlenden Credentials oder fehlendem Fortschritt: `needs-author-action` und der konkrete Launcher-/Skill-Weg im PR. Kein stiller Clientwechsel.

Fehleranalyse: zuerst Run/Check-ID und Head vergleichen, dann Doctor sowie `settings.py inspect/diff`; Providerzugang separat mit `engine.py model-smoke`. Regeländerungen, erhöhte Limits und dauerhaft relevante Entscheidungen benötigen PR und menschliche Freigabe. Keine Schutzregel zum Erzwingen von Grün entfernen.

## Verifizierte Pins und Updates

Am 27.10.2026 anhand offizieller Release-/Commitseiten verifiziert:

| Action | Version | SHA / Quelle |
|---|---|---|
| checkout | v7.0.1 | [`3d3c42e5aac5ba805825da76410c181273ba90b1`](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1) |
| upload-artifact | v7.0.2 | [`cf430e030ddbb5b0abf93d22962f4752f3646cd9`](https://github.com/actions/upload-artifact/commit/cf430e030ddbb5b0abf93d22962f4752f3646cd9) |

Nur diese beiden Actions werden verwendet. Action-, Docker- und Clientpaket-Updates laufen als Dependabot-PRs. Prüfbinärversionen und SHA256 stehen in `factory/tools.lock.json`; deren Upgrade benötigt einen expliziten Factory-Auftrag und erneute Binary-/Workflow-Prüfung. Keine Produkt-Paketmanager oder Dummy-Prüfungen. Quellen betreffen technische Verträge, keine Produktanforderungen.
