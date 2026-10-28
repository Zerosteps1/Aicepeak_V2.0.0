# Verification status and pending activation

## Übergabe: nächster notwendiger Schritt

Stand 28.10.2026, 19:14 UTC: **PR #14 ist fachlich geprüft; die vollständige Factory-Live-Abnahme bleibt offen.** Der menschliche Merge wurde nicht durch den Agenten ausgeführt. Nur dieses Repository und seine GitHub-Nachweise sind Projektquellen. Keine alten Projekte, privaten Notizen oder vorherigen Chats zum Wiederanlauf laden.

1. [PR #14](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/14), Head `0d5b60824568341072b1af145a2eb4a5d7750985`: beide App-5510081-Pflichtchecks grün, deterministisch `123040214523`, Senior `123039502073`, Testlauf [40751574013](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40751574013), lokaler Ergebnisrecord `123041416575`. Echter Business-Reviewer: Codex 0.164.0, GPT-6 Astra/high, vollständiger Prüfumfang, keine Findings oder Grenzen. Die vorherige Kontextlücke ist behoben; Finding F-001 wurde nach der ECMAScript-Gegenprobe ausdrücklich zurückgenommen. Vor einem menschlichen Merge Head, Base und aktuelle Checks erneut lesen. Keine Regeln abschalten.
2. Danach den sauberen Main-Kontroll-Checkout aktualisieren und [Smoke-PR #10](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/10) regulär auf Main bringen. Zuletzt geprüfter Smoke-Head `288c5ef3729f153250f3c09c2d1dd67e82540022` enthält absichtlich die falsche Erklärung `2 × 3 = 7` bei korrekten Zahlen. Nicht manuell reparieren oder mergen: Das ist der genehmigte Defekt, den Reviewer und Claude-Autor bearbeiten sollen.
3. Mit `session.py watch --pr 10` auf einem eingerichteten Maintainer-Gerät die neue Prüfung starten. Ein neuer Main-Stand verlangt einen Neustart des Watchers; nicht unter dem laufenden Prozess den Kontroll-Checkout wechseln. Vor dem Modelllauf die echte aktuelle Claim-/Reviewzählung lesen: PR #10 hat bis hier zwei Claims verbraucht (sauberer Erfolg und ungültige Finding-ID). Der neue Head setzt das Limit nicht zurück. Erwartet: gültiges P1-Finding, authentifizierte Claude-Korrektur per WIF, Writer-App-Push, neue Tests, neuer Astra/high-Pass. Bei einem konkreten Fehler dessen tatsächlichen Record/Log prüfen; kein blinder Retry, kein höheres Budget und kein künstlicher Erfolg.
4. Anschließend die autorisierte menschliche Feedbackprobe des [Smoke-Auftrags](../docs/work/FACTORY-SMOKE.md) durchführen und Antwort/Bindung prüfen. Danach die verbleibenden Geräte-, MCP- und Identitäts-Gegenproben aus der Abnahmetabelle abarbeiten. Erst nach den jeweils echten Nachweisen den Status auf einsatzbereit ändern.

**Grenzen dieser Übergabe:** Der echte Claude-Autor-/Writer-/Folgereview-Durchlauf fehlt; die erfolgreiche einzelne WIF-Anmeldung ersetzt ihn nicht. Felix' eigener Business-Reviewer-Smoke, authentifizierte native Skill-/MCP-Aufrufe und Live-Gegenproben für gleichzeitige Geräte, veraltete Ergebnisse und App-Merge-/Fremdcheck-Grenzen sind offen. Die entsprechenden lokalen Regressionen und aktiven Regeln sind Teilnachweise, keine Live-Ergebnisse. Ein automatischer Codex-Autor ist weiterhin nicht freigegeben; nur Claude ist als Runner zugelassen. Der isolierte lokale Codex-Autor benötigt aktuell noch den API-Pfad, Business-Auth dafür ist unbestätigt. Diese Anforderung darf nicht stillschweigend als erfüllt gelten.

PR #4 sowie die Architektur-PRs #12/#13 sind eigenständige Arbeiten und nicht Bestandteil dieser Factory-Reparatur. Vorhandene Änderungen daran erhalten. Für den Weiterlauf werden keine neuen GitHub Apps, kein OpenAI-API-Schlüssel für den Reviewer und keine erneute Einrichtung der bereits verifizierten Rulesets benötigt. Benötigt werden ein laufendes Maintainer-Terminal mit eigenem Business-Token und der menschliche Merge von #14. Auf einem neuen Gerät gelten die Schritte im README und in factory/clients.md; keine Secrets in die Übergabe kopieren.

## Live-Aktivierung am 28.10.2026

Gabriel (`Zerosteps1`) hat [PR #11](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/11) persönlich gemergt. Der anschließend unabhängig gelesene [Merge-Commit `ce736a5`](https://github.com/Zerosteps1/Aicepeak_V2.0.0/commit/ce736a5080a04b2e72f091371ec61c49e8d84291) hat exakt die Eltern `faededdd7c1e734ce2e168502cca54f0f0a04fc3` und `90ee4f52443d719c645e9b55ad69f884930d8476` sowie den geprüften Tree `161ed940fa2651560e4bd5c70768d0cc83080858`. Der [GitHub-Testlauf 40734682121](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40734682121) dieses Heads bestand mit 203 unveränderten Basistests und 211 Kandidatentests, Struktur, Actionlint und Gitleaks; deterministischer Check `122980738257` von Publisher-App 5510081. Frische unabhängige Astra/high-Audits sind im Verlauf unten abgegrenzt.

Die einmalig genehmigte Senior-Check-Ausnahme ist geschlossen. [Ruleset 26049015](https://github.com/Zerosteps1/Aicepeak_V2.0.0/rules/26049015) verlangt wieder beide strikten Pflichtchecks von App 5510081, PR und geklärte Threads, ohne Bypass-Akteure; Force-Push und Löschen bleiben gesperrt. Zusätzliche Approvals sind wie ausdrücklich entschieden null, Codeowner-/Last-Push-Approval nicht verpflichtend. [Ruleset 26049017](https://github.com/Zerosteps1/Aicepeak_V2.0.0/rules/26049017) bleibt unverändert auf PR-Merges der drei verifizierten Konten von Gabriel und Felix begrenzt. Beide Live-Regeln wurden unabhängig gelesen und gegen den versionierten Sollzustand verglichen: übereinstimmend.

Der einmalige Terminal-Helfer meldete nach erfolgreicher Wiederherstellung `Mandatory checks restored, but final merge evidence is incomplete`. Seine letzte Abfrage enthielt damit nicht alle erwarteten Abschlussfelder; die konkrete fehlende Angabe wurde nicht protokolliert. Die nachfolgende direkte Prüfung bestätigt Merge-Akteur, exakte Eltern, Tree, aktuellen Main-Commit und vollständige Regeln. Es wurde weder nochmals gemergt noch erneut eine Ausnahme geöffnet. Der Helfer gehört nicht zum regulären Factory-Betrieb.

Gabriel aktualisierte danach seinen sauberen Kontroll-Checkout auf diesen Main-Stand und führte den vollständigen authentifizierten Abgleich aus. Übermitteltes Ergebnis: `configuration_ready: true`, `changes: []`, `blockers: []`, `missing_environment_secrets: []`; Publisher-/Writer-Installationen `176168187` und `176168111` bestätigt. Das ist ein vom Maintainer ausgeführter Host-Nachweis; der Agent hat keine privaten Schlüssel über den Connector gelesen.

**Die administrative Konfiguration ist bestätigt, die vollständige Factory-Abnahme steht weiterhin aus.** [Smoke-PR #10](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/10) wurde ohne Force-Push auf Main aktualisiert: Head `e0448b03fef9010e7dd372abe5162f563edbe41a`, Base/Policy `ce736a5080a04b2e72f091371ec61c49e8d84291`. Gegen Main ändert er ausschließlich die Einrückung der korrekten JSON-Testfixture. [Run 40736694244](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40736694244) veröffentlichte den deterministischen Erfolg `122987680684`. Weitere ausstehende Geräte-/MCP-/Negativproben stehen in der Abnahmetabelle unten. `configuration_ready` ersetzt diese Nachweise nicht.

### Tatsächliche Review-Fix-Abnahme auf PR #10

Der saubere Gegenfall besteht: Senior-Check `122987148751` wurde von Publisher-App 5510081 als `success` abgeschlossen. Der neue lokale Kontext verwendete Codex 0.164.0, `gpt-6-astra`, Effort `high` und Gabriels Business-Zugang; eine Modellrunde, 38.220 Eingabe- und 474 Ausgabetokens, keine Findings oder offenen Prüfgrenzen. Authentifizierter Claim-Run [40746853315](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40746853315), Ergebnisrecord `123023411972`. Der lokale Ergebnisrecord selbst war `neutral`; erst der serialisierte Finalizer gab den Pflichtcheck frei. Gabriel übermittelte `{"pr":10,"outcome":"pass","published":true}`; App-Identität, Head-/Base-Bindung, Reviewer und endgültiger Gate-Erfolg wurden zusätzlich über GitHub gelesen. Die Aussage umfasst diese harmlose Änderung, keine pauschale Abnahme aller Factory-Funktionen.

Anschließend wurde die im freigegebenen Smoke-Auftrag bezeichnete Fehlerprobe als Commit `288c5ef3729f153250f3c09c2d1dd67e82540022` eingebracht. Genau eine Zeile in `factory-smoke.json` verändert `explanation` von `2 × 3 = 6` zu `2 × 3 = 7`; numerische Werte, Tests und Regeln bleiben unverändert. Der deterministische Check `123025891334` bestand ([Run 40747539017](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40747539017)). Der Reviewer brach dagegen mit der von Gabriel übermittelten Meldung `BLOCKED: review.findings[].id: pattern` ab. Senior-Gate `123025321037` blieb `failure`, Ergebnisrecord `123026851044` enthielt kein gültiges Review und autorisierte keine automatische Korrektur. Das ist eine echte Ablehnung ungültiger Reviewdaten, noch kein erfolgreicher Defekt-/Fix-Durchlauf.

Die reproduzierte Schemaabweichung wird regulär in [PR #14](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/14) korrigiert; die konkret fehlgeschlagene Modell-ID wurde nicht aufbewahrt. Bis zum menschlichen Merge und einem neuen gültigen Review bleiben automatische Claude-Korrektur, Writer-Folgetrigger und erneutes Review offen. Die fehlerhafte Ausgabe wird nicht nachträglich als Finding akzeptiert; beide Pflichtchecks bleiben aktiv.

## Finding-ID-Fehler bei der Live-Abnahme am 28.10.2026

Der saubere Smoke-Head `e0448b03fef9010e7dd372abe5162f563edbe41a` bestand den echten Astra/high-Review: App-Check `122987148751`, keine Findings, Base/Policy `ce736a5080a04b2e72f091371ec61c49e8d84291`. Beim anschließend ausdrücklich vorgesehenen Erklärungsdefekt am Head `288c5ef3729f153250f3c09c2d1dd67e82540022` bestanden die deterministischen Prüfungen ([Run 40747539017](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40747539017)); der lokale Reviewer brach mit Gabriels übermittelter Meldung `review.findings[].id: pattern` ab. App-Gate `123025321037` blieb `failure`, Ergebnisrecord `123026851044` enthielt kein gültiges Review, automatische Korrektur wurde nicht autorisiert. Die konkrete erzeugte ID wurde nicht aufbewahrt.

Reproduzierter Vertragsfehler: JSON Schema wertet `pattern` als Teiltreffer aus, der lokale Validator verwendet einen vollständigen Treffer. Das bisher unverankerte `[A-Z0-9_-]+` ließ daher beispielsweise `f-1` oder `F-001-suffix` im Generierungsschema zu, die lokal abgelehnt werden. Die Korrektur verankert das vorhandene Muster als `^[A-Z0-9_-]+$` und erläutert das bestehende ID-Format mit `F-001`. Der lokale Validator und die Gate-/Prioritätsregeln bleiben unverändert; IDs werden nicht nachträglich umgeschrieben. Quellen: [JSON Schema: pattern-Semantik](https://json-schema.org/understanding-json-schema/reference/string#regexp), [OpenAI: unterstützte Structured-Output-Eigenschaften](https://developers.openai.com/api/docs/guides/structured-outputs#supported-schemas), geprüft am 28.10.2026. Die exakte fehlgeschlagene Modellausgabe ist damit nicht rekonstruiert.

Neue Gegenprobe vor der Korrektur: sechs ungültige Teiltreffer scheiterten wie erwartet. Danach bestehen alle elf Vertragstests einschließlich gültiger IDs, weiterhin blockierender Findings und der neuen Teiltreffer-Gegenprobe. Struktur-/Schema-/Adapter-/Linkprüfung bestanden lokal. Ein neuer echter Review mit korrigiertem Schema steht noch aus; diese Änderung muss regulär durch beide Pflichtchecks und einen menschlichen Merge auf `main`, bevor sie einen Smoke-Review beeinflusst. Kein Retry der fehlgeschlagenen Ausgabe, keine neue Bootstrap-Ausnahme.

Ein frischer unabhängiger Astra/high-Reviewer prüfte die drei geänderten Dateien, führte die elf Vertragstests erfolgreich aus und bestätigte den engen Umfang ohne blockierende Befunde. Zusätzlich wurden die gültigen und ungültigen Beispiele mit Nodes ECMAScript-RegExp geprüft. Das beratende Review ersetzt keinen GitHub-Pflichtcheck und keinen echten Modelllauf mit dem korrigierten Schema.

### Rücklauf aus dem echten Review von PR #14

Head `9519123c0bcb36007e66b90ec70e3f6da5992510` bestand die deterministischen Prüfungen ([Run 40749742201](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40749742201)). Der gültige Astra/high-Ergebnisrecord `123035229118` blockierte mit fehlendem Validator-Kontext; Senior-Gate `123033019403` blieb korrekt `failure`. Der bisherige Kontextleser fand absolute Python-Imports nur neben der geänderten Datei oder im Repo-Root. Dadurch fehlte `contracts.py`, das die Factory-Tests aus ihrem Elternverzeichnis importieren.

Die Kontextaufnahme liest jetzt auch passende Quellen in den Repository-Vorfahren, ohne Importcode oder `sys.path`-Änderungen auszuführen. Bei mehreren Treffern werden alle als Evidenz aufgenommen; ihre tatsächliche Laufzeitauswahl wird nicht behauptet. Baum-, Dateimodus-, Abhängigkeits- und Größenlimits bleiben bestehen. Zwei neue Regressionen scheiterten zuvor und bestehen danach. Der ergänzte Kommentar am unveränderten `re.fullmatch` dokumentiert die beabsichtigte Ganzstring-Prüfung; damit enthält schon das von der bisherigen Main-Policy erzeugte Prüfmaterial den vollständigen Validator. Der geänderte Kontextleser wird erst nach menschlichem Merge zur Prüfgrundlage.

Finding `F-001` (P2) desselben Reviews wird mit Gegenbeleg bestritten: Es behauptete, ECMAScript akzeptiere `F-001` mit abschließendem Zeilenumbruch. Ohne Multiline-Flag verlangt `$` das tatsächliche Stringende ([ECMAScript Assertion](https://tc39.es/ecma262/multipage/text-processing.html#sec-compileassertion), [JSON-Schema-RegExp](https://json-schema.org/understanding-json-schema/reference/regular_expressions)). Die Regression verwendet jetzt Node-RegExp statt Python-`re.search` und prüft zusätzlich LF, CR, CRLF, U+2028 und U+2029 gegen den lokalen Validator; alle werden abgelehnt. Lokal ausgeführt mit Node 25.8.1, elf Vertragstests und fünf Kontexttests bestanden. Die Factory-CI verwendet die bereits gepinnte Node-Laufzeit. Das belegt die dokumentierte Schema-Semantik, keinen neuen Provider-Aufruf mit dem Kandidatenschema.

Der unabhängige Astra/high-Prüfer prüfte auch diesen Folge-Diff und führte alle 16 betroffenen Tests erfolgreich aus; keine blockierenden Befunde. Die deterministische CI und das verbindliche lokale Review müssen den neuen Head regulär erneut prüfen. Es gibt keinen Retry ohne Änderung und keine Lockerung der Gates.


## Verlauf bis zur Bootstrap-Reparatur

[PR #9](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/9) wurde menschlich nach `main` übernommen (`faededdd7c1e734ce2e168502cca54f0f0a04fc3`). Die beiden Rulesets `26049015` (PR, menschliche Codeowner-Freigabe, App-gebundene Pflichtchecks) und `26049017` (Updates nur durch menschliche PR-Merges) wurden anschließend tatsächlich aktiviert und per GitHub-API gelesen. Beide App-Schlüssel und `CONTEXT7_API_KEY` sind im auf Branch `main` begrenzten Environment hinterlegt. Der Soll-/Ist-Vergleich meldete noch die unten erklärte Parameter-Normalisierung.

**Die Factory ist noch nicht einsatzbereit.** Der erste [Live-Smoke-PR #10](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/10) startete [Run 40708139409](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40708139409): Snapshot erfolgreich, deterministische Tests fehlgeschlagen, beide App-Gates korrekt ohne Freigabe abgeschlossen. Kein Modelllauf dieses PRs hat stattgefunden. Die vollständige Review-Fix-Abnahme steht aus. Produktarbeit bleibt blockiert: der Nordstern-Pfad ist gesetzt, seine Freigabe und Produktprüfungen fehlen.

### Reparatur aus der ersten Linux-Abnahme

- Das tatsächlich gebaute Bookworm-Image enthält Git **2.39.5**. Die CLI-Option `--no-lazy-fetch` existiert erst ab 2.45. Die Objektlesezugriffe verwenden jetzt `GIT_NO_LAZY_FETCH=1` und zusätzlich eine leere `GIT_ALLOW_PROTOCOL`-Liste. Echte Git-Proben prüfen jede Sperre getrennt, einschließlich absichtlich ungeschützter SSH-/Remote-Helper-Gegenproben. Quellen: [Git 2.45 Release Notes](https://raw.githubusercontent.com/git/git/v2.45.0/Documentation/RelNotes/2.45.0.txt), [2.39.5 Fetch-Sperre](https://raw.githubusercontent.com/git/git/v2.39.5/promisor-remote.c), [Transport-Allowlist](https://raw.githubusercontent.com/git/git/v2.39.5/Documentation/git.txt).
- Ohne Init-Prozess blieben beendete Reviewer-Kinder unter Linux als Zombies sichtbar. Der Reviewer aktiviert vorübergehend den Linux-Subreaper und wartet ausschließlich Kinder der Reviewer-Prozessgruppe mit `waitpid` ab; vorheriger Subreaper-Zustand und fremde direkte Kindprozesse bleiben erhalten. Auch erfolgreicher Elternprozess-Austritt räumt Kinder auf. Neue Container erhalten zusätzlich `--init`. Quellen: [Linux Subreaper](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html), [waitpid-Prozessgruppen](https://man7.org/linux/man-pages/man2/waitpid.2.html), [Docker init](https://docs.docker.com/reference/cli/docker/container/run/#init).
- GitHub gibt die deaktivierte Update-Ausnahme als `{"type":"update"}` ohne das optionale Parameterobjekt zurück. Der Vergleich normalisiert ausschließlich diesen Fall; eine aktivierte Ausnahme, ein leeres explizites Parameterobjekt und eine fehlende Regel bleiben Abweichungen. Live-Quelle: [Ruleset 26049017](https://api.github.com/repos/Zerosteps1/Aicepeak_V2.0.0/rulesets/26049017); [API-Regelschema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).
- Gabriel führte den unveränderten Verifier von `main` gegen den Reparaturkandidaten im bestehenden Linux-Image aus, ohne Netzwerk, Secrets oder `--init`: **203 unveränderte Basistests und 208 Kandidatentests bestanden**, ebenso Struktur, Actionlint und Gitleaks. Zuvor scheiterten zwei neue Git-Gegenproben an `/tmp` mit `noexec`; sie verwenden nun den vorhandenen `/bin/sh` als Interpreter. Die Mount-Sperre wurde nicht gelockert. Diese 208er-Probe lag vor der nachfolgend ergänzten Budgetregression.
- Ein frischer unabhängiger Reviewer mit **GPT-6 Astra/high** prüfte den Laufzeit-/Settings-Diff und führte lokale Tests aus: Settings 21/21, Session 23/23, Local Review 26 bestanden; die Linux-spezifische Probe war auf macOS übersprungen, der lokale Socket-Test durch die Agenten-Sandbox blockiert. Keine bestätigten P0/P1-Befunde. Dies ist unabhängige Prüfevidenz, keine Veröffentlichung des GitHub-App-Gates.

### Review-Größe und genehmigte Bootstrap-Reparatur

Das alte Limit von 160.000 Eingabebytes lässt nach Instruktionsreserve nur 142.000 Bytes Prüfmaterial zu. Schon `session.py` allein benötigt mit beiden Dateiständen, direkten Abhängigkeiten und dem 99.113-Byte-Nordstern über 256.000 Bytes; der acht Dateien umfassende Laufzeitfix über 675.000 Bytes, jeweils vor Auftrag und Feedback. Die unabhängige Nachmessung bestätigte: Aufteilen allein kann das nicht lösen.

Der Kandidat setzt die feste Eingabegrenze deshalb auf **800.000 UTF-8-Bytes**, davon weiterhin 18.000 Bytes Instruktionsreserve. Vollständige Quellen, ursprüngliche Policy-Bindung, App-Identitäten, Pflichtchecks, Modell/Effort, 900 Sekunden, sechs Reviewversuche und Autor-Kostenlimits bleiben erhalten. Eine Regression erzeugt das Prüfmaterial aus den tatsächlichen Factory-Dateien und prüft auch die Ablehnung genau oberhalb der Bytegrenze. Die Fehlermeldung nennt jetzt Ist-/Sollgröße; es gibt keine stille Kürzung oder Umgehungsoption.

Auch diese Ergänzung wurde unabhängig mit Astra/high geprüft. Die neue Budgetregression und der korrigierte Git-Helper-Test bestanden; mit der alten Budgetkonfiguration scheiterte die Budgetregression wie vorgesehen. Keine bestätigten P0/P1-Befunde. Die Testquelle verwendet dieselben aktuellen Dateien für beide Revisionsrollen; sie beweist Größenabdeckung und vollständige Textaufnahme, keine historische SHA-Auswahl. Die tatsächliche Revisionstreue bleibt durch die unveränderte Snapshot-/Quellenlogik und deren separate Prüfungen abgedeckt.

Bytes sind keine Tokens: Der gelesene gebündelte Katalog von Codex 0.164.0 nennt für Astra standardmäßig 272.000 und maximal 872.000 Kontexttokens; die [OpenAI-Modellseite](https://developers.openai.com/api/docs/models/gpt-6-astra) nennt für die API 1.050.000. Diese Werte belegen weder die Business-Kontingente noch einen erfolgreichen großen Reviewlauf. Native Kontextgrenzen werden nicht überschrieben; Modell-/Kontingentfehler blockieren weiterhin. Größere tatsächlich übergebene Eingaben beanspruchen mehr Business-Kontingent. Der echte große Review bleibt ein ausstehender Nachweis.

**Dieser PR kann seine neue Grenze nicht selbst anwenden.** Die gültige `main`-Policy blockiert sein Review; ein Budget-only-PR scheitert wiederum an den alten Linux-Tests. Gabriel hat am 28.10.2026 die einmalige Bootstrap-Reparatur für [PR #11](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/11) ausdrücklich genehmigt: ausschließlich den Senior-Pflichtcheck kurzzeitig ausnehmen, den exakten geprüften Head persönlich mergen und den Check unmittelbar wiederherstellen. Der deterministische App-Check und die übrigen Schutzgrenzen bleiben erhalten; währenddessen darf kein anderer PR gemergt werden. Bei Abbruch ohne Merge gilt wieder die ursprüngliche Regel. Ein rotes Gate wird nicht als grün ausgegeben und kein Agent merged. Die administrative Ausführung und Wiederherstellung sind noch nicht belegt; danach folgt der vollständige Live-Smoke.

Der tatsächliche [GitHub-Run 40715161620](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40715161620) bestand mit Head `ab62ba04e23885b4471314163bbaa450a7d1452e` und Base/Policy `faededdd7c1e734ce2e168502cca54f0f0a04fc3`: 203 unveränderte Basistests, 209 Kandidatentests, Struktur, Actionlint und Gitleaks. Publisher-App 5510081 veröffentlichte den deterministischen Erfolg (Check 122914904311); Senior-Check 122910859944 wartete weiterhin. Dieser Nachweis liegt vor der nachstehenden Merge-Regeländerung und gibt deren neuen Commit nicht frei.

### Bestätigte dauerhafte Merge-Regel

Gabriel entschied anschließend ausdrücklich: **„Ohne zweite Freigabe, Pflichtchecks bleiben bestehen“**. Die versionierte Einstellung `require_second_human_review: false` setzt zusätzliche Approvals auf null und hebt die verpflichtende Codeowner-/Last-Push-Approval auf. Gabriel oder Felix trifft die menschliche Entscheidung selbst; beide strikten App-Checks, PR-Pflicht, geklärte Threads und die menschliche Identitätsgrenze bleiben bestehen. CODEOWNERS bleibt für Zuständigkeiten erhalten. Diese dauerhafte Änderung ist von der einmaligen Senior-Check-Ausnahme getrennt: Nach erfolgreichem Bootstrap-Merge werden beide Pflichtchecks wiederhergestellt, die zweite menschliche Freigabe bleibt entfallen. Ohne explizite Einstellung behalten ältere Konfigurationen ihre bisherige zweite Freigabe; nichtboolesche Werte blockieren.

Zwei neue Regressionen scheiterten vor der Implementierung und bestehen danach: vollständige neue Merge-Regel einschließlich App-/Identitätsbindung und Ablehnung ungültiger Einstellungswerte. Alle 23 Settings-Tests sowie die Struktur-/Vertrags-/Adapter-/Linkprüfung bestanden lokal. Die abschließende GitHub-Prüfung dieses neuen Stands steht zum Zeitpunkt dieses Eintrags aus; die vorherigen 209 Kandidatentests sind kein Nachweis dafür.

Ein unabhängiger Astra/high-Reviewer prüfte auch diese eng begrenzte Regeländerung, bestätigte die unveränderten technischen Gates und menschlichen Identitäten und führte die 23 Settings-Tests erfolgreich aus; keine bestätigten P0/P1. Die zusammengeführte Bootstrap-Änderung umfasst mit der ergänzten Dokumentation 15 Dateien und rund 835.000 Materialbytes vor zusätzlichem Feedback. Sie überschreitet auch die neue Materialgrenze von 782.000 Bytes. Das Limit wird deshalb nicht erneut angehoben: Der separat geprüfte Bootstrap bleibt eine einmalige Ausnahme, spätere Änderungen müssen den begrenzten regulären Reviewumfang einhalten. Die neue Grenze deckt den zusammenhängenden Laufzeitfix ab, nicht beliebig große Sammel-PRs.

Gabriel (`Zerosteps1`) und Felix (`truFelix-Zentru`, `ftrutschnig`) sind bestätigt. Beide Felix-Konten gehören derselben Person; ein zweites eigenes Konto ersetzt keine unabhängige menschliche Freigabe.

Im korrigierten Kandidaten sind folgende Befunde mit gezielten Regressionen bearbeitet:

- R-01: geräteübergreifender Claim vor dem Modelllauf; nur der serialisierte Workflow-Finalizer kann das Gate abschließen. Fremde, doppelte oder veraltete Ergebnisse können es nicht überschreiben.
- R-02: Netzwerkprobe mit der echten `socket.create_connection`-Signatur; unerwartet erfolgreiche Verbindungen werden geschlossen.
- R-03: direkter Workflow wird über `workflow_ref` gebunden; der Live-Federationsnachweis steht unten.
- R-04/R-05: Claude-Verbrauch erst nach gültiger terminaler Usage, `message_stop` und sauberem EOF verrechnen; unklare/abgebrochene Streams behalten die Reservierung. Einstündiges Caching wird vor Upstream abgelehnt. Die Eingangsreservierung verwendet Bytes statt eines mittleren Bytes-pro-Token-Werts.
- Gemeinsamer Einstieg: `session.py preflight/submit/watch/response`, getrennte beratende Vorprüfung und PR-Antwort, begrenztes Repository-Kontextpaket sowie strukturierte Defekte, Prüffragen und Empfehlungen. Vorprüfung führt keine Tests aus und gibt kein Gate frei.
- Aktiver Abbruch: Änderungen an Head, Feedback oder Claim sowie Frist-/Controller-Abbruch beenden die laufende Reviewer-Prozessgruppe. Lokale Tests mit echten Kindprozessen prüfen auch verbleibende Nachkommen; dies ist kein Live-Doppelgeräte-Nachweis.

Abschlussprüfung des Codes bis `bc11c83384ce7b503d8ec98f51c7ac418c5233b0`: 203 Tests gestartet, davon 202 in der Agenten-Sandbox bestanden; der reale lokale TCP-Testserver wurde dort durch `PermissionError` blockiert. Gabriel führte anschließend denselben vollständigen `verify.py`-Lauf in seinem normalen Terminal aus und übermittelte alle vier PASS-Zeilen einschließlich der vollständigen Suite. Syntax/Verträge/Adapter/Links, Actionlint 1.7.12 und Gitleaks 8.30.1 bestanden ebenfalls. Der Host-Nachweis stammt aus Gabriels Ausgabe, nicht aus einer vom Agenten ausgeführten Host-Shell.

Das unabhängige GPT-6-Astra/high-Review prüfte den Code bis derselben Revision und die ursprünglichen Fehlerszenarien erneut. Behoben sind alte Korrekturfreigaben nach einem neuen Review, verlorene Benachrichtigungen nach teilweise erfolgreicher Veröffentlichung, Bytecode-Dateien beim CLI-Start, überholte Watcher-Aufträge und ein PR-Erstellungsrennen. 22 Sitzungstests und sieben echte Prozess-Abbruchtests bestanden beim Reviewer; kein weiterer konkreter blockierender Codefehler blieb offen. Nachfolgende Dokumentationsänderungen wurden vom Hauptagenten geprüft.

Docker ist für diesen Agenten nicht zugänglich. Gabriels erster Build brach wegen eines nicht über PATH gefundenen Credential-Helpers ab. Mit dem überprüften temporären Helper-Pfad und explizitem lokalen Docker-Endpunkt baute Gabriel das gepinnte Image erfolgreich. Sein `clients.py smoke` meldete `passed`: Codex 0.164.0, Claude Code 2.1.311; Projektlesen erlaubt, fremde Host-Dateien/Symlink-Ausbruch/Schreiben vertrauenswürdiger Regeln verweigert. Codex erkannte alle vier kanonischen Skills, beide Rollen und beide MCP-Konfigurationen; Claude-Validierung und Doctor wurden ausgeführt. Dieser vom Nutzer übermittelte Lauf unternahm keinen Modellaufruf. Authentifizierte Claude-Skill-Erkennung und echte native Context7-/OpenAI-Docs-Aufrufe bleiben ausdrücklich ungetestet. Die historischen Testzahlen unten sind keine aktuelle Gesamtzahl. Der Business-Codex-Autor ist weiterhin nicht unterstützt/verifiziert; automatische Autoren sind aktuell ausschließlich Claude. Der native Business-Reviewer benötigt kein `OPENAI_API_KEY`.

Historischer Stand vor dem Merge von PR #9: Der zusammengeführte Kontrolländerungs-PR ersetzte die technischen Entwürfe #5/#6. Seine 44 geänderten Dateien überschritten die reguläre 40-Dateien-Grenze; diese wurde nicht angehoben. Der damalige Main-Workflow erwartete noch den inzwischen abgelösten API-Reviewer. Gabriel prüfte und mergte den Bootstrap-PR; erst danach wurden die heutigen Rulesets aktiviert. Diese frühere Initialisierung ist keine Genehmigung einer weiteren Ausnahme. PR #4 bleibt wegen zusätzlicher Produkt-/Scope-Entscheidungen unabhängig offen.

## Anmeldung und App-Registrierung

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
die Branch-Grenze vor dem Speichern der Secrets. Bei der zweiten Ausgabe waren Factory-Rulesets und App-Secrets noch nicht vorhanden. Die dritte, von Gabriel übermittelte Ausgabe bestätigt beide App-Secrets; nur der alte `OPENAI_API_KEY`-Sollwert fehlt. Diese Inspector-Ausgabe enthielt noch keine Rulesets. Das gemeldete fehlende `OPENAI_API_KEY` gehört zum alten
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
Main-Workflows. Der Agent hat keine App-Secrets ausgelesen oder hochgeladen; deren Speicherung ist durch Gabriels dritte Inspector-Ausgabe bestätigt. Eine Ruleset-Aktivierung oder vollständige Review-Fix-Abnahme ist damit nicht belegt. Die folgenden Angaben vom
27.10. bleiben historische Nachweise des ursprünglichen Bootstrap-Stands.

## Historischer Bootstrap-Stand

Stand: 27.10.2026. **Factory lokal implementiert; noch nicht einsatzbereit.** Dieser Nachweis trennt ausgeführte Prüfungen von ausstehenden Live-Szenarien. Kein Merge und keine administrativen Remote-Änderungen wurden vorgenommen.

## Historical PR B2 evidence (2026-10-28, before the corrections above)

Executed locally for PR B2 (usage-based broker accounting, federated Claude author, egress self-test, Claude brakes):

- `python3 -I -m unittest discover -s tools/factory/tests`: **107 tests OK**, including a 30-turn session with 60 KB context per runner within budget, SSE and JSON usage parsing, the Workload Identity Federation exchange against a fake transport (fresh GitHub OIDC token per exchange, caching, URL and ID validation), OIDC request credentials reaching only the broker, and the fail-closed worker egress self-test.
- `python3 tools/factory/verify.py --root .`: all four PASS lines (actionlint 1.7.12, gitleaks 8.30.1).
- Claude Code 2.1.312 (one patch above the pinned 2.1.311) captured against a local capture server: all body fields allowlisted; `max_tokens: 128000` and six betas that the broker previously dropped (see [Clients](clients.md)). Redacted fixture: `tools/factory/tests/fixtures/claude-code-2.1.312-request.json`.

At that earlier checkpoint, token exchange, Docker/container runs and real model calls had not been executed, and automatic correction was disabled. The later federation and local Business reviewer successes above supersede the authentication statement. The current target enables bounded automatic correction after bootstrap; The later host build and boundary smoke above passed; the real review/fix cycle still needs acceptance.

## Historical PR B1 evidence (2026-10-28, before the live smoke)

Executed locally on the maintainer's Mac for PR B1 (maintainer-local senior reviewer, pipeline without `OPENAI_API_KEY`, broker allowlist):

- `python3 -I -m unittest discover -s tools/factory/tests`: **95 tests OK**.
- `python3 tools/factory/clients.py check --root .`: passed.
- `python3 tools/factory/verify.py --root .`: all four PASS lines (structure, links and adapter drift; workflow syntax, cache isolation and Action SHAs; Gitleaks; trusted regression suite and candidate tests), with actionlint 1.7.12 darwin_arm64 (SHA-256 verified against the official release checksums) and Gitleaks 8.30.1 in the PATH.
- The reviewer command line was accepted by codex-cli 0.164.0 with `--strict-config`.
- The model-visible tool surface was captured against a local capture server and with `codex debug prompt-input`. Default configuration: `exec_command`, `apply_patch`, `view_image` and `spawn_agent`. Reviewer configuration: only `exec`, `wait` and `request_user_input`, with the MCP resource helpers nested in `exec` and no MCP server configured. Details in [Clients](clients.md#senior-reviewer-maintainer-local).
- `local_review.py --smoke` with a deliberately invalid token completed the version, catalog and tool-surface checks and failed at the model call with 401. Codex sent no credential for the malformed token, so acceptance of a real ChatGPT Business access token was **unverified at that checkpoint**. Gabriel's later successful local smoke is recorded above.

Not executed at that checkpoint: live GitHub runs, Docker/container runs, real model calls or `settings.py apply`. Do not use this historical list as the current authentication status.

## Target and prerequisites (setup, 2026-10-27)

Public GitHub API actually read: `Zerosteps1/Aicepeak_V2.0.0`, repository ID `1436114884`, public, configured default `main`; branch list empty, contents endpoint 404. A repeated branch query at the end was still empty. Owner `Zerosteps1`, user ID `115100163`, confirmed by the user as Gabriel. Felix not yet named. The SSH origin is `git@github.com:Zerosteps1/Aicepeak_V2.0.0.git`.

The target repository contained no north star yet; `northstar_path:null` is the explicit blocker, not a substitute document. Since PR #2, `AICEPEAK_NORDSTERN.md` is in the repository. The current configuration records that path with `northstar_approved:false`; this does not grant product scope. No old projects, earlier work or personal knowledge collections were taken over for the factory. A document outside the target repository was not imported as a repository source.

`gh` and the GitHub connector provided no valid login; SSH/Git network access was not possible in this environment. Public HTTPS queries through the permitted curl call worked. Plan, Actions, environment and administration rights were therefore not verified with authentication. The repository is public; private use needs a new plan and feature check. **No rulesets have been activated by this setup.**

Checked locally: Git 2.50.1, gh 2.87.0, Codex 0.164.0, Claude Code 2.1.311, Python 3.15.2, Node 25.8.1, npm 11.11.0, Docker 29.1.3, Gitleaks 8.30.1. Actionlint 1.7.12 was downloaded from the official release and verified against its SHA256. Docker daemon not reachable. CLI help and native configuration sources are documented in [Clients](clients.md). The factory needs only the Python standard library plus pinned check and client tools; this does not determine a product stack.

## Executed local checks (setup, 2026-10-27)

- Python syntax, JSON/TOML, native adapter drift, internal documentation links, complete Action SHAs and controlled smoke calculation.
- Actionlint over all workflow files. The only compatibility treatment: the line `cache-mode: none`, documented by GitHub but not yet understood by Actionlint 1.7.12, is first checked exactly and removed only for its parser. All other fields are checked completely. No general filtering of linter errors.
- Gitleaks with a trusted rule file, an empty ignore file and inline exceptions disabled. One narrowly scoped AND exception covers only the public internal broker URL literal in `clients.py`, not a credential value.
- Unit and regression tests check the review contract, SHA/App/run binding, three rounds, monotonic budget despite force push, duplicate processing, draft to ready, missing model key, new human feedback, path and rename limits, a real Git rename, atomic ref update, settings diff and idempotence, and broker/worker boundaries. GitHub and provider transports are simulated; this is no live evidence.
- Negative probe: a deliberately broken candidate validation stays red in the isolated trusted suite despite `unittest.py`/`sitecustomize.py` in the candidate. Existing base tests explicitly load candidate code; missing tests do not count as success.
- Positive counter-example: a complete, correct review contract without artificial findings is accepted. A real Astra gate review of this clean PR counter-example is still pending.
- The doctor was run against the actual local state and reports open prerequisites. Additional diagnostic probes check, among other things, that even a seemingly complete local state produces no live approval and that secret values are not printed.
- The npm lockfile was built against actual public package metadata including integrity values and checked offline with a fresh temporary home without personal npm configuration.

Reproducible with `python3 -I -m unittest discover -s tools/factory/tests -v` and `python3 tools/factory/verify.py --root .`. If Actionlint is not in the PATH: `--actionlint /absolute/path/actionlint`. Final local run at setup: **67 tests passed**, full verifier exit 0, `git diff --check` exit 0. Doctor exit 2 (open prerequisites), model smoke exit 1 (missing API key; `engine.py model-smoke` was removed in PR B1), container smoke exit 2 (Docker access denied). This file claims no live tests that were not executed.

## Documentation and model access (setup, 2026-10-27)

The OpenAI Docs MCP `https://developers.openai.com/mcp` was queried directly with `initialize`, `tools/list`, `search_openai_docs` and `fetch_openai_doc`; server `openai-docs-mcp` 1.0.0. Context7 `resolve-library-id` and `query-docs` were used through the existing connector. Only generic technical questions, no private diffs or requirements. **This does not prove** reachability from the isolated clients; their MCP smoke is pending.

Centrally configured: `gpt-6-astra`, `reasoning.effort=high`, no fallback. At setup the actual command `python3 tools/factory/engine.py model-smoke` blocked before the network call because `OPENAI_API_KEY` was missing. At that checkpoint, neither a successful model response nor API permission was demonstrated. PR B1 removed this API path. Gabriel subsequently reported that `python3 tools/factory/local_review.py --smoke` passed with a real Business access token. Each reviewer host still needs its own acceptance, and a PR gate publication is a separate test.

## Independent review and resolved findings (setup)

An independent subagent was actually run with GPT-6 Astra / high. This was local review evidence, not proof of provider access at that time. Later audits found the defects listed in the current section; the earlier conclusion is not approval of today's integrated candidate.

First review: budget loss on force push, missing check of the rename source, rename treated as a copy by the writer, and a blocked draft to ready transition. Fixed with a PR-wide authenticated ledger, checks of both paths, complete delete/add capture and draft binding; targeted regressions exist.

Second review: test discovery through candidate imports, base tests without a candidate target, uncounted GitHub job reruns, cancellation with unchanged context, missing atomic expected-head check and a misleading dispatcher retry. Fixed with an isolated test start, an explicit candidate target, run-attempt binding and a fresh paid retry, serialized runs with targeted cancellation of stale runs, GraphQL `updateRefs.beforeOid` and exactly one human retry entry point. Author reports and answers to human questions are kept as reviewable PR feedback. The final independent re-review confirmed all fixes without a remaining evidenced blocker; it ran 65 tests itself successfully. Afterwards two local diagnostic regressions raised the suite to 67.

## Live acceptance after activation

| Scenario | Present / checked locally | Live evidence still required |
|---|---|---|
| Fresh checkout, same rules/skills | Adapter generation and drift check | Native discovery and actual skill execution in both clients |
| Isolated context | Gabriel-reported container smoke passed: project read allowed; foreign-host read, symlink escape and trusted-rule write denied | Live authenticated author run and resulting patch |
| Valid PR | Real clean PR #10 passed both App checks; PR #14 also has a bound Astra/high pass | Repeat at each new head; no prior approval is transferable |
| Maintainer-local reviewer | Gabriel real Business smoke and bound App-gate publication on PRs #10/#14; tool-surface/claim regressions | Felix's own host smoke and workspace usage/entitlement verification |
| Defect and fix | [Smoke work order](../docs/work/FACTORY-SMOKE.md), real clean counter-example; controlled text defect still present | Valid defect finding, real author fix, App push, new check run and final review |
| Human feedback | Identity/PR association, re-reading, changed context | Comment, inline comment and review, each with an understandable response |
| Old head/base/run | Binding regressions and active cancellation with real child processes | New head/feedback during a live review cancels that work; stale results cannot publish |
| Missing credentials/schema/API | Local fail-closed tests; real malformed finding-ID output left PR #10 blocked, with no author authorization | Live invalid-token/API-failure counterpart remains separate |
| Control changed in PR | PR #14 schema/context changes reviewed with unchanged ce736a5 policy; both versions supplied as evidence | Continue verifying policy SHA for every control change |
| Secret/identity boundary | Separate jobs, broker, App scope check | Tests without secrets; no Codex token on GitHub; an agent can neither update `main` nor merge |
| Foreign check with same name | Expected App ID in the ruleset, contract negative test | A foreign check App does not satisfy the required check |
| Budget/concurrency | Force push/rerun/duplicate/CAS and shared-claim regressions | Two correction rounds, exhausted reserves and competing devices produce the correct handoff without losing a blocking finding |
| MCPs | Separate direct documentation queries | Both native clients reach only allowed servers; generic queries succeed |

Only after this evidence may the status "ready for operation" be set. Record successful GitHub run and check IDs and verified SHAs in the smoke PR, then add the lasting acceptance here through a PR.

## Tool and cost decision

Existing Codex/Claude CLIs, GitHub Actions/API, two narrowly scoped Apps, Python and small free check tools are sufficient. No additional AI review subscription, no agent platform and no product infrastructure were bought. The senior reviewer uses the Business workspace access-token path, not a Platform API key. Workspace entitlements, usage limits and any additional billing must be checked; no blanket free-operation guarantee follows. Docker serves only as the factory's process boundary. Context7 and OpenAI Docs provide public technical documentation; no project memory and no external indexing.

Current configured limits: at most 2 automatic corrections, USD 12 reserved per author run and USD 25 per PR, 900 seconds execution limit, and 6 claimed senior-review attempts per PR, including failed attempts and dry-runs. The author reservation is conservative; failed or cancelled runs do not release it automatically. Provider billing, requests already started and GitHub Actions usage must still be watched, as must the reviewer's share of the Codex seat window. Author prices are versioned in `factory/config.json`, sources in [Clients](clients.md) and [GitHub operation](github.md). A public repository does not mean free model calls. For private repositories, no blanket assumption of free code security or secret protection products.

The current execution image pins Node `26.12.0-bookworm-slim` in [Dockerfile](Dockerfile); older host-version observations above are historical. A trusted image build must still record the resolved image ID and package inventory. Federation changes authentication only; the Claude author remains API usage, with actual credit coverage or additional charges determined by the Console billing state.
