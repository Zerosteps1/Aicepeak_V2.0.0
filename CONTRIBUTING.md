# Beitragen

Lies `AGENTS.md`, [Policy](factory/policy.md) und `factory/config.json`. Starte den isolierten Client gemäß [README](README.md); arbeite mit frischem Kontext und einem eigenen Branch. Ein Produktauftrag benötigt den freigegebenen kanonischen Nordstern und passende Produktprüfungen. Fehlende Grundlagen werden als Blocker benannt.

## Auftrag → Änderung → Review

1. `factory-start`: Ziel, Scope, Nicht-Ziele, Risiken und beobachtbare Akzeptanzkriterien in `docs/work/NAME.md` festhalten. Der Auftrag muss vor seiner Umsetzung menschlich geprüft und im geschützten Basisstand vorhanden sein; ein `approved`-Text im eigenen PR genügt nicht. [Beispiel](docs/work/FACTORY-001.md).
2. `factory-change`: kleine angemessene Umsetzung und aussagekräftige Nachweise. API-/Bibliotheksannahmen mit versionierter Herstellerdokumentation prüfen; Context7 zuerst `resolve-library-id`, dann `query-docs`. Keine vorsorglichen Abstraktionen, erfundenen Schnittstellen oder Tests, die kritische Logik wegmocken.
3. `factory-review`: eigene Änderung und tatsächliche Ergebnisse gegen den Auftrag prüfen. Bei Skill-/Rollenänderungen `python3 tools/factory/clients.py sync --root .`, danach `check --root .`; vollständige Prüfung mit `python3 tools/factory/verify.py --root .`. Blockierte Prüfungen offen nennen. Lokales Review ersetzt den unabhängigen Serverlauf nicht.
4. Patch außerhalb des Modellworkers prüfen, auf dem Aufgabenbranch übernehmen und PR öffnen. Im PR Änderung, Nachweise und offene Grenzen beschreiben; genau einen Übergabeblock mit realem Auftrag und verifiziertem Maintainer verwenden:

```factory-handoff
{"runner":"codex","task":"docs/work/FACTORY-001.md","owner":"Zerosteps1"}
```

Regeln, Skills, Anforderungen, Tests und Budgets werden aus dem fixierten geschützten Basis-Commit geladen. Änderungen an dieser Grundlage sind eigene menschlich geprüfte Factory-/Anforderungsänderungen; der aktuelle PR kann seine Prüfung nicht durch eigene Regelrevisionen abschwächen. Automatische Korrekturen dürfen geschützte Dateien nicht ändern.

## Feedback und Wiederaufnahme

Gewöhnliche PR-Kommentare, Reviews und Inline-Kommentare konfigurierter menschlicher Maintainer werden nach Aktivierung automatisch erneut aus GitHub gelesen und geprüft. Eine besondere Bot-Syntax ist nicht nötig. Der unabhängige Reviewer ordnet sie dem aktuellen Auftrag und Head zu. Bot-/Fremdkommentare autorisieren keine Arbeit; Reviewthreads werden nicht automatisch aufgelöst.

`factory-fix-review` beantwortet jeden Punkt mit **erledigt**, **begründet bestritten** oder **blockiert**, jeweils mit Beleg. Berechtigte Befunde werden korrigiert und erneut geprüft. Sachliche Konflikte gehen an den Menschen zurück; neue Produktwünsche benötigen zuerst einen versionierten, menschlich geprüften Auftrag. Ändere weder Anforderungen noch Tests, um einen Befund verschwinden zu lassen.

`P0`/`P1` blockieren; `P2` sind Hinweise. Ein vollständig korrekter kleiner PR darf ohne Findings bestehen. `pass` verlangt vollständigen Prüfumfang und ausreichende Evidenz. `blocked`, fehlende Credentials, kein Fortschritt, Konflikte oder ausgeschöpfte Limits führen zu `needs-author-action`; maximal drei automatische Korrekturrunden, kein stiller Wechsel zwischen Codex und Claude.

Zur Wiederaufnahme die im PR genannte Ursache beheben, aktuellen Branch frisch auschecken und den dort angegebenen Runner starten:

```sh
python3 tools/factory/doctor.py --root . --runner codex
python3 tools/factory/clients.py launch --root . --runner codex
# Im Client: factory-fix-review für PR #<Nummer>, aktuellen Auftrag und Findings.
```

Launcher-Secret-Präsenz ersetzt keine gültigen API-Rechte. Bei fehlendem Zugang die in [README](README.md) genannten Secrets/Modelle herstellen; bei Konflikt zuerst menschliche Entscheidung im Auftrag festhalten. Patch prüfen, Branch aktualisieren; der neue Head startet frische Prüfungen. Ohne Codeänderung kann ein verifizierter Maintainer einen neuen Lauf mit `gh workflow run factory.yml --ref main -f pr=<Nummer> -f retry=true` starten. GitHubs „Re-run jobs“ wird abgewiesen, weil es alte Budgetreservierungen wiederverwenden würde. Alte Checks geben einen neuen Head oder Basisstand nicht frei.

Merge erst nach beiden erfolgreichen App-gebundenen Pflichtchecks und geklärten Threads. Gabriel oder Felix entscheidet selbst und merged; eine zweite menschliche Freigabe ist nicht nötig. CODEOWNERS bleibt der Wegweiser für Zuständigkeit und freiwillige Reviews. Auch Menschen dürfen rote Pflichtchecks nicht umgehen. Modelle haben keine GitHub-Zugangsdaten; keine Direktpushes auf `main`, automatischen Merges oder eigenmächtigen Schutzregeländerungen.
