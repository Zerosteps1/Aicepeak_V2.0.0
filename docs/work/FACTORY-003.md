# FACTORY-003 – Factory-Abnahme nach unabhängigem Review

Status: durch Gabriels Auftrag vom 28.10.2026 autorisierte Kontrolländerung; menschlicher Merge und reale Abnahme stehen aus. Der PR wird weiterhin gegen FACTORY-001 auf seiner Basis geprüft. Dieses Dokument ersetzt nicht seine eigene Prüfgrundlage.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":[".github/",".agents/",".claude/",".codex/",".mcp.json","AGENTS.md","CLAUDE.md","README.md","CONTRIBUTING.md","factory-smoke.json","factory/","tools/factory/","docs/work/","docs/decisions/"]}
```

Ziel: bestätigte Defekte aus PR #5/#6 beheben, unabhängige Reviews auf Gabriels und Felix' Geräten koordinieren, PR-Feedback wieder in die Autorphase führen und einen überprüfbaren Aktivierungsweg liefern.

Nicht-Ziele: Produktcode, Architektur, Stackwahl, Änderungen oder Freigabe des Nordsterns/der Produktverfassung, automatischer Merge, Kostenfreiheit oder Erfolg nicht ausgeführter Live-Tests.

Abnahme:

1. Zwei konkurrierende Geräte dürfen nicht denselben Reviewcheck überschreiben. GitHub vergibt eine eindeutige Zuständigkeit; nur der serialisierte Publisher schließt den Check. Falsche App/Run/PR/Claim/SHA/Policy, Wiederholungen und veraltete Ergebnisse werden abgewiesen. Abgebrochene Modellaufrufe behalten ihre Reservierung.
2. Frischer Astra/high-Kontext ohne Autorenverlauf; Befunde trennen Defekt, Frage, Empfehlung, Priorität und Evidenzsicherheit. Unveränderte direkte Python-Abhängigkeiten und versionierte Factory-Manifeste ergänzen den Diff. Fehlender notwendiger Kontext blockiert.
3. Vor-PR-Prüfung, PR-Einreichung mit erneuter Standprüfung, begrenztes Warten auf neue Reviewaufträge sowie quellgebundene PR-Fragen sind ausführbar. Menschliche Kommentare/Inline-Reviews werden authentifiziert, erneut gelesen und am aktuellen Stand bearbeitet; keine automatische Threadauflösung.
4. Isolierter Autorstart verwendet die echte Socket-Signatur; erfolgreiche unerlaubte Verbindungen werden geschlossen und blockieren. Unvollständige Streams/Fehler erstatten keine unbekannte Nutzung. Nicht unterstütztes einstündiges Caching wird vor dem Provider abgelehnt.
5. Gabriel und beide von ihm bestätigten Felix-Konten erhalten dieselben versionierten Regeln. Persönliche Tokens bleiben getrennt. Eine Freigabe über das zweite eigene Konto ist keine unabhängige menschliche Prüfung.
6. Gültiger kleiner Smoke-PR, semantischer Fehler bei grünen deterministischen Tests, autorisierte Korrektur, realer Writer-Push und erneutes Review werden auf GitHub nachgewiesen. Ein numerischer Fehler ist eine separate Negativprobe des deterministischen Gates.
7. Erst nach menschlichem Merge, aktiven geprüften Rulesets und Live-Negativproben ist die Factory einsatzbereit. Nicht ausführbare Integration bleibt als Blocker sichtbar.

Umsetzung: kleine Python-Standardbibliotheksmodule in tools/factory; vorhandene Workflows und App-Grenzen weiterverwenden. Getrennte Arbeitskopien für Broker, Review-Koordination und Sitzungseinstieg; danach gemeinsame Regressionen und frisches unabhängiges Astra/high-Review. Keine zusätzliche Agentenplattform oder private Wissensbasis.
