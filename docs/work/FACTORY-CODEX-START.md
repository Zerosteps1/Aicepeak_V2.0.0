# Codex-Start über den Factory-Broker

Status: Korrekturvorschlag zur menschlichen Prüfung. Auslöser: gemeldeter Startfehler mit Codex 0.164.0 nach frischem Checkout.

Ziel: Die dokumentierten isolierten Codex-Starts laden den geprüften Factory-Provider über eine unterstützte Konfigurationsebene.

Scope: interaktiver und unbeaufsichtigter Launcher, native Smoke-Discovery, generierter Projektadapter und Startanleitung. Keine Produktänderung, keine globale Benutzerkonfiguration, keine Änderung der Isolation, MCP-Pflicht, Modelle, Budgets oder Freigaberegeln.

Akzeptanz:
- Die wirksame Codex-Konfiguration verwendet den Factory-Broker und ausschließlich die Referenz auf das wegwerfbare Job-Token.
- Der Projektadapter enthält keine von Codex ignorierten Provider-Schlüssel.
- Der Launcher erzeugt ausschließlich die notwendige Projekt-Vertrauensangabe im neuen Container-Codex-Verzeichnis, ohne vorhandene Dateien zu überschreiben; persönliche Konfiguration bleibt ausgeschlossen.
- Beide Autorenwege und native Discovery verwenden dieselbe geprüfte Provider-Konfiguration.
- Ein nativer Konfigurationscheck ohne Modellaufruf ergänzt die Regressionstests; nicht ausgeführte Container-/API-Tests bleiben offen.
- Die Anleitung erklärt, warum ein direkter Host-Start nicht funktioniert und welches Startprogramm erforderlich ist.

Quellen: `AGENTS.md`, `factory/policy.md`, `factory/clients.md`, `tools/factory/clients.py` und die im Client-Dokument verlinkte offizielle Codex-Konfigurationsreferenz. Keine Altprojektquellen.

Die Übernahme ist eine geschützte Factory-Änderung und folgt dem manuellen Reviewweg. Dieser Vorschlag erklärt sich nicht selbst zur freigegebenen Prüfbasis.
