# FACTORY-SMOKE – Harmlose Review-Fix-Abnahme

Status: Abnahmeauftrag nach menschlichem Bootstrap-Merge; noch kein Nachweis der vollständigen Review-Fix-Schleife. Isolierte Factory-Testfixture, kein Produktcode.

```factory-task
{"status":"approved","kind":"smoke","allowed_paths":["factory-smoke.json"]}
```

Ziel: Belegen, dass Tests, Astra-high-Review, gewählter Autor-Runner, neuer App-Commit und erneutes Review tatsächlich zusammenarbeiten.

Voraussetzungen: aktueller vertrauenswürdiger Main-Kontrollstand, bestätigte App-Zugänge im auf `main` beschränkten Environment und aktiv geprüfte Pflichtchecks `factory/deterministic` sowie `factory/senior-review`. Der Zielstand setzt `automatic_correction: true` mit höchstens zwei Korrekturrunden; aktuell ist nur `claude` als automatischer Runner zugelassen. Der Business-Reviewer benötigt kein `OPENAI_API_KEY`. Business-Anmeldung für den isolierten Codex-Autor bleibt unbestätigt und ist nicht Gegenstand einer Erfolgsmeldung dieses Tests.

Der erfolgreiche Federation-Lauf `40684684126` und Gabriels gemeldeter lokaler Astra/high-Smoke sind Teilnachweise, keine Ersatzabnahme. Details: [Federation und Reviewer-Anmeldung](FACTORY-WIF-SMOKE.md#nachweisstand-am-28102026). Docker-, native MCP- und Host-Prüfungen müssen auf einem berechtigten Rechner erfolgen; die Sandbox dieses Prüfagenten erlaubt weder Docker-Zugriff noch lokales Port-Binding.

Scope: ausschließlich die bezeichnete JSON-Testfixture. Nicht-Ziele: Produktänderungen, Änderungen an Prüflogik, Regeln, Anforderungen oder Berechtigungen.

Akzeptanz: `total` ist exakt `quantity * unit_price`. Positive Ausgangsprobe: 2 × 3 = 6 ohne künstliches Finding. Kontrollierter Reviewdefekt: numerische Werte weiterhin 2, 3 und 6; nur `explanation` wird auf `2 × 3 = 7` gesetzt. Die deterministische Rechenprüfung bleibt grün, der unabhängige Reviewer muss den Widerspruch zur korrekten Rechnung beanstanden. Der Autor korrigiert ausschließlich `explanation` auf `2 × 3 = 6`; der neue Commit startet alle Prüfungen erneut. Anschließend eine menschliche Kommentarprobe: Erläuterung der Korrektur anfordern, Antwort im PR prüfen. Keine automatischen Threadauflösungen oder Merges.

Belege: reale Run-/Check-IDs und Head-/Base-SHAs im PR, danach Abnahmeergebnis in `factory/evidence.md`. Mocktests allein erfüllen diese Abnahme nicht.

Der gemeinsame Einstieg ist `session.py`: `preflight` liefert nur eine beratende Quellprüfung ohne Testausführung; `submit` prüft erneut und reicht den bereits gepushten Stand ein; `watch` läuft auf dem aktiven Maintainer-Rechner. Die verbindliche Reviewzuständigkeit muss über den gemeinsamen Claim laufen, und nur der vertrauenswürdige Finalizer darf das Senior-Gate abschließen. `response --post` veröffentlicht die ausdrücklich angeforderte, quellgebundene Antwort ohne Korrekturauftrag oder Gate-Freigabe. Aufrufbeispiele stehen in [way-of-working.md](../way-of-working.md).

Zusätzliche Live-Gegenprobe: Zwei Geräte versuchen denselben offenen Reviewstand; genau eines erhält den Claim. Während eines laufenden Reviews einen neuen Head oder autorisiertes Feedback erzeugen: der alte Modellprozess muss enden und sein Ergebnis darf nicht publizieren. Lokale Tests mit echten Kindprozessen belegen bereits den Abbruchmechanismus, nicht diesen Live-Ablauf. Beide Felix-Konten gehören derselben Person; das zweite Konto ersetzt keine unabhängige menschliche Merge-Freigabe.

Ein falscher numerischer `total` bleibt als separate Negativprobe der deterministischen Prüfung sinnvoll: er darf kein Senior-Review starten. Diesen Fall nicht als Nachweis der Modell-Review-Fix-Schleife zählen. Die Textprobe prüft eine zweite, von diesem Test nicht bereits abgefangene Anforderung. Ein sauberes Gegenbeispiel behält die richtige Erklärung und darf keine künstlichen Findings erhalten.
