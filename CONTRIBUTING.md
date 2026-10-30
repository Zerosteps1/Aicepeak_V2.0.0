# Beitragen

Lies `AGENTS.md`, [Policy](factory/policy.md) und `factory/config.json`. Richte dein Gerät gemäß [dev-setup.md](docs/dev-setup.md) ein und starte den isolierten Client gemäß [way-of-working.md](docs/way-of-working.md); arbeite mit frischem Kontext und einem eigenen Branch. Ein Produktauftrag benötigt den freigegebenen kanonischen Nordstern und passende Produktprüfungen. Fehlende Grundlagen werden als Blocker benannt.

## Auftrag → Änderung → Review

1. `factory-start`: Ziel, Scope, Nicht-Ziele, Risiken und beobachtbare Akzeptanzkriterien in `docs/work/NAME.md` festhalten. Der Auftrag muss vor seiner Umsetzung menschlich geprüft und im geschützten Basisstand vorhanden sein; ein `approved`-Text im eigenen PR genügt nicht. [Beispiel](docs/work/FACTORY-001.md).
2. `factory-change`: kleine angemessene Umsetzung und aussagekräftige Nachweise. API-/Bibliotheksannahmen mit versionierter Herstellerdokumentation prüfen; Context7 zuerst `resolve-library-id`, dann `query-docs`. Keine vorsorglichen Abstraktionen, erfundenen Schnittstellen oder Tests, die kritische Logik wegmocken.
3. `factory-review`: eigene Änderung und tatsächliche Ergebnisse gegen den Auftrag prüfen. Bei Skill-/Rollenänderungen `python3 tools/factory/clients.py sync --root .`, danach `check --root .`; vollständige Prüfung mit `python3 tools/factory/verify.py --root .`. Blockierte Prüfungen offen nennen. Lokales Review ersetzt den unabhängigen Serverlauf nicht.
4. Patch außerhalb des Modellworkers prüfen und auf dem Aufgabenbranch übernehmen. Vor dem PR aus dem Kontroll-Checkout `python3 tools/factory/session.py collisions --candidate <Pfad> --task <Auftrag>` ausführen (auch aus einer eigenen Claude- oder Codex-Sitzung): Der Kandidat muss das aktuelle `main` enthalten; Konflikte mit `main` löst der Autor im Kandidaten. Überschneidungen mit anderen offenen PRs werden nur angezeigt und über die Merge-Reihenfolge geklärt, nie durch Anpassung an ungemergten Code. Danach PR öffnen; `session.py submit` wiederholt die Prüfung und vermerkt sie im PR. Im PR Änderung, Nachweise und offene Grenzen beschreiben; genau einen Übergabeblock mit realem Auftrag und verifiziertem Maintainer verwenden:

```factory-handoff
{"runner":"claude","task":"docs/work/FACTORY-001.md","owner":"Zerosteps1"}
```

`runner` muss in `runners` von `factory/config.json` stehen; derzeit ist nur `claude` zugelassen, `codex` blockiert den PR. Ein neuer Auftrag in `docs/work/` braucht einen eigenen, vorher gemergten PR (Vorlage: [TEMPLATE](docs/work/TEMPLATE.md)); erst danach kann ein Umsetzungs-PR auf ihn verweisen.

Regeln, Skills, Anforderungen, Tests und Budgets werden aus dem fixierten geschützten Basis-Commit geladen. Änderungen an dieser Grundlage sind eigene menschlich geprüfte Factory-/Anforderungsänderungen; der aktuelle PR kann seine Prüfung nicht durch eigene Regelrevisionen abschwächen. Automatische Korrekturen dürfen geschützte Dateien nicht ändern.

## Feedback und Wiederaufnahme

Gewöhnliche PR-Kommentare, Reviews und Inline-Kommentare konfigurierter menschlicher Maintainer werden nach Aktivierung automatisch erneut aus GitHub gelesen und geprüft. Eine besondere Bot-Syntax ist nicht nötig. Der unabhängige Reviewer ordnet sie dem aktuellen Auftrag und Head zu. Bot-/Fremdkommentare autorisieren keine Arbeit; Reviewthreads werden nicht automatisch aufgelöst.

`factory-fix-review` beantwortet jeden Punkt mit **erledigt**, **begründet bestritten** oder **blockiert**, jeweils mit Beleg. Berechtigte Befunde werden korrigiert und erneut geprüft. Sachliche Konflikte gehen an den Menschen zurück; neue Produktwünsche benötigen zuerst einen versionierten, menschlich geprüften Auftrag. Ändere weder Anforderungen noch Tests, um einen Befund verschwinden zu lassen.

`P0`/`P1` blockieren; `P2` sind Hinweise. Ein vollständig korrekter kleiner PR darf ohne Findings bestehen. `pass` verlangt vollständigen Prüfumfang und ausreichende Evidenz. `blocked`, fehlende Credentials, kein Fortschritt, Konflikte oder ausgeschöpfte Limits führen zu `needs-author-action`; maximal drei automatische Korrekturrunden, kein stiller Wechsel zwischen Codex und Claude.

Zur Wiederaufnahme die im PR genannte Ursache beheben, aktuellen Branch frisch auschecken und den dort angegebenen Runner starten:

```sh
python3 tools/factory/doctor.py --root . --runner claude
python3 tools/factory/clients.py launch --root . --runner claude
# Im Client: factory-fix-review für PR #<Nummer>, aktuellen Auftrag und Findings.
```

Launcher-Secret-Präsenz ersetzt keine gültigen API-Rechte. Bei fehlendem Zugang die in [dev-setup.md](docs/dev-setup.md) genannten Secrets/Modelle herstellen; bei Konflikt zuerst menschliche Entscheidung im Auftrag festhalten. Patch prüfen, Branch aktualisieren; der neue Head startet frische Prüfungen. Ohne Codeänderung kann ein verifizierter Maintainer einen neuen Lauf mit `gh workflow run factory.yml --ref main -f pr=<Nummer> -f retry=true` starten. GitHubs „Re-run jobs“ wird abgewiesen, weil es alte Budgetreservierungen wiederverwenden würde. Alte Checks geben einen neuen Head oder Basisstand nicht frei.

Normalfall: Merge nach beiden erfolgreichen App-gebundenen Pflichtchecks und geklärten Threads. Maintainer entscheiden selbst und mergen mit `python3 tools/factory/session.py merge --pr <Nummer>`, immer nur einen PR zur Zeit; nur der als Nächstes gemergte PR wird per „Update branch“ aktualisiert. Der Befehl prüft, dass der Head das aktuelle `main` enthält und beide Checks genau an diesen Head und dieses `main` gebunden sind, und serialisiert Merges über ein Lock; der manuelle Bypass liegt außerhalb dieser Garantie. Eine zweite menschliche Freigabe ist nicht nötig. CODEOWNERS bleibt der Wegweiser für Zuständigkeit und freiwillige Reviews. Hängt ein PR (kein Reviewer-Gerät, Modellfehler, ausgeschöpfte Limits), dürfen Maintainer bewusst per Bypass mergen („Merge without waiting for requirements“); vorher den Grund als PR-Kommentar festhalten. Modelle haben keine GitHub-Zugangsdaten; keine Direktpushes auf `main`, automatischen Merges oder eigenmächtigen Schutzregeländerungen.
