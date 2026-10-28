# FACTORY-SMOKE – Harmlose Review-Fix-Abnahme

Status: nur nach menschlichem Bootstrap-Merge aktiv. Isolierte Factory-Testfixture, kein Produktcode.

```factory-task
{"status":"approved","kind":"smoke","allowed_paths":["factory-smoke.json"]}
```

Ziel: Belegen, dass Tests, Astra-high-Review, gewählter Autor-Runner, neuer App-Commit und erneutes Review tatsächlich zusammenarbeiten.

Scope: ausschließlich die bezeichnete JSON-Testfixture. Nicht-Ziele: Produktänderungen, Änderungen an Prüflogik, Regeln, Anforderungen oder Berechtigungen.

Akzeptanz: `total` ist exakt `quantity * unit_price`. Positive Ausgangsprobe: 2 × 3 = 6 ohne künstliches Finding. Kontrollierter Defekt: total 7 bei unveränderten übrigen Angaben. Der Reviewer benennt den Fehler; Autor korrigiert ausschließlich total auf 6; der neue Commit startet alle Prüfungen erneut. Anschließend eine menschliche Kommentarprobe: Erläuterung der Korrektur anfordern, Antwort im PR prüfen. Keine automatischen Threadauflösungen oder Merges.

Belege: reale Run-/Check-IDs und Head-/Base-SHAs im PR, danach Abnahmeergebnis in `factory/evidence.md`. Mocktests allein erfüllen diese Abnahme nicht.
