# FACTORY-001 – Gemeinsame Softwarefabrik einrichten

Status: durch den aktuellen Setup-Auftrag autorisierte Factory-Arbeit; Bootstrap-PR benötigt menschliche Prüfung. Keine Produktfreigabe.

```factory-task
{"status":"approved","kind":"factory","allowed_paths":[".github/",".agents/",".claude/",".codex/",".mcp.json","AGENTS.md","CLAUDE.md","README.md","CONTRIBUTING.md",".gitignore","factory-smoke.json","factory/","tools/factory/","docs/work/","docs/decisions/"]}
```

## Ziel und Umfang

Für `Zerosteps1/Aicepeak_V2.0.0` gemeinsame Regeln, vier Skills und Autor-/Reviewer-Rollen für Codex und Claude Code einrichten. Zentraler Reviewer ausschließlich `gpt-6-astra`, Effort `high`. PR-Prüfung, strukturierte Findings, begrenzte automatische Autor-Korrektur und menschliche Merge-Entscheidung ausführbar machen.

Verbindlich sind dieser Auftrag, `factory/policy.md`, `factory/config.json` und der von einem geschützten Basis-Commit geladene Regelstand. Ein PR ändert nicht seine eigene Prüfgrundlage. Projektwissen ausschließlich aus diesem Repository; öffentliche Herstellerdokumentation nur für technische Fakten. Kein Altprojekt, privates Memory oder persönlicher Chat als Produktquelle.

## Nicht-Ziele

Kein Produktstack, Anwendungscode, Datenmodell, Produktdeployment oder vorsorgliche Produktverzeichnisse. Kein Agent-Merge, keine Ausnahmen von Schutzregeln, keine zweite Nordstern-Kopie, kein erfundener Maintainer.

## Umsetzung und Abnahme

1. Ziel, Clients und offizielle Schnittstellen prüfen; belegte Versionen und Zugriffsblocker in `factory/evidence.md` festhalten.
2. Gemeinsame Skills/native Adapter und isolierte Starts mit leerem persönlichem Kontext implementieren; Drift und unerlaubte Außenlesezugriffe prüfen.
3. Reviewvertrag, Snapshot-/SHA-Prüfung, deterministisches Gate und begrenzte Korrekturen implementieren. Negative Tests für falsche App/Run/Policy/SHA, ungültiges pass, Pfade, Limits und doppelte Verarbeitung.
4. Vertrauenswürdige Default-Branch-Orchestrierung von Tests, Modellaufruf, Publisher und Patch-Writer trennen. Ruleset-Sollzustand mit idempotentem Diff/Apply bereitstellen.
5. Angemessene lokale Prüfungen und unabhängiges Astra-high-Review; Befunde korrigieren. Setup-PR oder überprüften lokalen Branch liefern.
6. Erst nach menschlichem Bootstrap-Merge, administrativer Aktivierung und realem Smoke-PR einschließlich Review-Fix-Schleife als einsatzbereit markieren.

Prüffokus: veraltete Reviews, manipulierte eigene Regeln, Secrets in untrusted Ausführung, erfundene Erfolgsnachweise, privilegierte Branchupdates, Wiederholungs-/Kostenlimits.

## Produktgrundlage

Das Zielrepository ist per öffentlicher GitHub-API als leer verifiziert (keine Branches, Contents-API 404); ein Nordstern fehlt dort. Kein Produktauftrag darf daraus abgeleitet werden. Eine außerhalb dieses Git-Arbeitsbereichs vorhandene Datei wird weder gelesen noch importiert. Nach bewusster menschlicher Ablage und Freigabe wird ausschließlich dessen Repo-Pfad in `factory/config.json` eingetragen; die Originaldatei bleibt erhalten.

## Arbeitsabgrenzung

Factory-Werkzeuge: Python-Standardbibliothek; Client-CLIs und Prüfwerkzeuge sind getrennt versioniert. Lokale Vorbereitung ist kein Nachweis aktiver GitHub-Durchsetzung. Nicht ausgeführte Integrations-/Abnahmeszenarien bleiben in `factory/evidence.md` offen.
