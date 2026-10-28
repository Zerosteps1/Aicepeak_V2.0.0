# Verification status and pending activation

## Aktueller Abnahmestand am 28.10.2026

[PR #9](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/9) wurde menschlich nach `main` übernommen (`faededdd7c1e734ce2e168502cca54f0f0a04fc3`). Die beiden Rulesets `26049015` (PR, menschliche Codeowner-Freigabe, App-gebundene Pflichtchecks) und `26049017` (Updates nur durch menschliche PR-Merges) wurden anschließend tatsächlich aktiviert und per GitHub-API gelesen. Beide App-Schlüssel und `CONTEXT7_API_KEY` sind im auf Branch `main` begrenzten Environment hinterlegt. Der Soll-/Ist-Vergleich meldete noch die unten erklärte Parameter-Normalisierung.

**Die Factory ist noch nicht einsatzbereit.** Der erste [Live-Smoke-PR #10](https://github.com/Zerosteps1/Aicepeak_V2.0.0/pull/10) startete [Run 40708139409](https://github.com/Zerosteps1/Aicepeak_V2.0.0/actions/runs/40708139409): Snapshot erfolgreich, deterministische Tests fehlgeschlagen, beide App-Gates korrekt ohne Freigabe abgeschlossen. Kein Modelllauf dieses PRs hat stattgefunden. Die vollständige Review-Fix-Abnahme steht aus. Produktarbeit bleibt blockiert: der Nordstern-Pfad ist gesetzt, seine Freigabe und Produktprüfungen fehlen.

### Reparatur aus der ersten Linux-Abnahme

- Das tatsächlich gebaute Bookworm-Image enthält Git **2.39.5**. Die CLI-Option `--no-lazy-fetch` existiert erst ab 2.45. Die Objektlesezugriffe verwenden jetzt `GIT_NO_LAZY_FETCH=1` und zusätzlich eine leere `GIT_ALLOW_PROTOCOL`-Liste. Echte Git-Proben prüfen jede Sperre getrennt, einschließlich absichtlich ungeschützter SSH-/Remote-Helper-Gegenproben. Quellen: [Git 2.45 Release Notes](https://raw.githubusercontent.com/git/git/v2.45.0/Documentation/RelNotes/2.45.0.txt), [2.39.5 Fetch-Sperre](https://raw.githubusercontent.com/git/git/v2.39.5/promisor-remote.c), [Transport-Allowlist](https://raw.githubusercontent.com/git/git/v2.39.5/Documentation/git.txt).
- Ohne Init-Prozess blieben beendete Reviewer-Kinder unter Linux als Zombies sichtbar. Der Reviewer aktiviert vorübergehend den Linux-Subreaper und wartet ausschließlich Kinder der Reviewer-Prozessgruppe mit `waitpid` ab; vorheriger Subreaper-Zustand und fremde direkte Kindprozesse bleiben erhalten. Auch erfolgreicher Elternprozess-Austritt räumt Kinder auf. Neue Container erhalten zusätzlich `--init`. Quellen: [Linux Subreaper](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html), [waitpid-Prozessgruppen](https://man7.org/linux/man-pages/man2/waitpid.2.html), [Docker init](https://docs.docker.com/reference/cli/docker/container/run/#init).
- GitHub gibt die deaktivierte Update-Ausnahme als `{"type":"update"}` ohne das optionale Parameterobjekt zurück. Der Vergleich normalisiert ausschließlich diesen Fall; eine aktivierte Ausnahme, ein leeres explizites Parameterobjekt und eine fehlende Regel bleiben Abweichungen. Live-Quelle: [Ruleset 26049017](https://api.github.com/repos/Zerosteps1/Aicepeak_V2.0.0/rulesets/26049017); [API-Regelschema](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).
- Gabriel führte den unveränderten Verifier von `main` gegen den Reparaturkandidaten im bestehenden Linux-Image aus, ohne Netzwerk, Secrets oder `--init`: **203 unveränderte Basistests und 208 Kandidatentests bestanden**, ebenso Struktur, Actionlint und Gitleaks. Zuvor scheiterten zwei neue Git-Gegenproben an `/tmp` mit `noexec`; sie verwenden nun den vorhandenen `/bin/sh` als Interpreter. Die Mount-Sperre wurde nicht gelockert. Diese 208er-Probe lag vor der nachfolgend ergänzten Budgetregression.
- Ein frischer unabhängiger Reviewer mit **GPT-6 Astra/high** prüfte den Laufzeit-/Settings-Diff und führte lokale Tests aus: Settings 21/21, Session 23/23, Local Review 26 bestanden; die Linux-spezifische Probe war auf macOS übersprungen, der lokale Socket-Test durch die Agenten-Sandbox blockiert. Keine bestätigten P0/P1-Befunde. Dies ist unabhängige Prüfevidenz, keine Veröffentlichung des GitHub-App-Gates.

### Review-Größe und noch notwendige Bootstrap-Entscheidung

Das alte Limit von 160.000 Eingabebytes lässt nach Instruktionsreserve nur 142.000 Bytes Prüfmaterial zu. Schon `session.py` allein benötigt mit beiden Dateiständen, direkten Abhängigkeiten und dem 99.113-Byte-Nordstern über 256.000 Bytes; der acht Dateien umfassende Laufzeitfix über 675.000 Bytes, jeweils vor Auftrag und Feedback. Die unabhängige Nachmessung bestätigte: Aufteilen allein kann das nicht lösen.

Der Kandidat setzt die feste Eingabegrenze deshalb auf **800.000 UTF-8-Bytes**, davon weiterhin 18.000 Bytes Instruktionsreserve. Vollständige Quellen, ursprüngliche Policy-Bindung, App-Identitäten, Pflichtchecks, Modell/Effort, 900 Sekunden, sechs Reviewversuche und Autor-Kostenlimits bleiben erhalten. Eine Regression erzeugt das Prüfmaterial aus den tatsächlichen Factory-Dateien und prüft auch die Ablehnung genau oberhalb der Bytegrenze. Die Fehlermeldung nennt jetzt Ist-/Sollgröße; es gibt keine stille Kürzung oder Umgehungsoption.

Auch diese Ergänzung wurde unabhängig mit Astra/high geprüft. Die neue Budgetregression und der korrigierte Git-Helper-Test bestanden; mit der alten Budgetkonfiguration scheiterte die Budgetregression wie vorgesehen. Keine bestätigten P0/P1-Befunde. Die Testquelle verwendet dieselben aktuellen Dateien für beide Revisionsrollen; sie beweist Größenabdeckung und vollständige Textaufnahme, keine historische SHA-Auswahl. Die tatsächliche Revisionstreue bleibt durch die unveränderte Snapshot-/Quellenlogik und deren separate Prüfungen abgedeckt.

Bytes sind keine Tokens: Der gelesene gebündelte Katalog von Codex 0.164.0 nennt für Astra standardmäßig 272.000 und maximal 872.000 Kontexttokens; die [OpenAI-Modellseite](https://developers.openai.com/api/docs/models/gpt-6-astra) nennt für die API 1.050.000. Diese Werte belegen weder die Business-Kontingente noch einen erfolgreichen großen Reviewlauf. Native Kontextgrenzen werden nicht überschrieben; Modell-/Kontingentfehler blockieren weiterhin. Größere tatsächlich übergebene Eingaben beanspruchen mehr Business-Kontingent. Der echte große Review bleibt ein ausstehender Nachweis.

**Dieser PR kann seine neue Grenze nicht selbst anwenden.** Die gültige `main`-Policy blockiert sein Review; ein Budget-only-PR scheitert wiederum an den alten Linux-Tests. Eine Installation benötigt daher eine ausdrücklich menschlich autorisierte, eng begrenzte Bootstrap-Reparatur mit unabhängigem Review und echten Linux-Nachweisen. Eine solche Ausnahme ist bisher **nicht** genehmigt oder eingerichtet. Die aktiven Schutzregeln werden nicht automatisch geändert, kein rotes Gate wird als grün ausgegeben und kein Agent merged. Danach sind die normalen Regeln erneut zu prüfen und der vollständige Live-Smoke durchzuführen.

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
| Valid PR | Dispatcher and contract tests | Both App checks appear; `local_review.py` completes the pending senior review with Astra-high |
| Maintainer-local reviewer | Gabriel-reported real Astra/high Business smoke; local tool-surface, claim and publication regressions | Felix's own host smoke, real bound gate publication, and workspace usage/entitlement verification |
| Defect and fix | [Smoke work order](../docs/work/FACTORY-SMOKE.md), real Git patch probe | Real author fix, App push, new check run, clean counter-example |
| Human feedback | Identity/PR association, re-reading, changed context | Comment, inline comment and review, each with an understandable response |
| Old head/base/run | Binding regressions and active cancellation with real child processes | New head/feedback during a live review cancels that work; stale results cannot publish |
| Missing credentials/schema/API | Local fail-closed tests | A deliberately invalid token or schema keeps the review blocked |
| Control changed in PR | Base policy/orchestration and read-only author adapters | A real PR rule change does not influence its own check |
| Secret/identity boundary | Separate jobs, broker, App scope check | Tests without secrets; no Codex token on GitHub; an agent can neither update `main` nor merge |
| Foreign check with same name | Expected App ID in the ruleset, contract negative test | A foreign check App does not satisfy the required check |
| Budget/concurrency | Force push/rerun/duplicate/CAS and shared-claim regressions | Two correction rounds, exhausted reserves and competing devices produce the correct handoff without losing a blocking finding |
| MCPs | Separate direct documentation queries | Both native clients reach only allowed servers; generic queries succeed |

Only after this evidence may the status "ready for operation" be set. Record successful GitHub run and check IDs and verified SHAs in the smoke PR, then add the lasting acceptance here through a PR.

## Tool and cost decision

Existing Codex/Claude CLIs, GitHub Actions/API, two narrowly scoped Apps, Python and small free check tools are sufficient. No additional AI review subscription, no agent platform and no product infrastructure were bought. The senior reviewer uses the Business workspace access-token path, not a Platform API key. Workspace entitlements, usage limits and any additional billing must be checked; no blanket free-operation guarantee follows. Docker serves only as the factory's process boundary. Context7 and OpenAI Docs provide public technical documentation; no project memory and no external indexing.

Current configured limits: at most 2 automatic corrections, USD 12 reserved per author run and USD 25 per PR, 900 seconds execution limit, and 6 claimed senior-review attempts per PR, including failed attempts and dry-runs. The author reservation is conservative; failed or cancelled runs do not release it automatically. Provider billing, requests already started and GitHub Actions usage must still be watched, as must the reviewer's share of the Codex seat window. Author prices are versioned in `factory/config.json`, sources in [Clients](clients.md) and [GitHub operation](github.md). A public repository does not mean free model calls. For private repositories, no blanket assumption of free code security or secret protection products.

The current execution image pins Node `26.12.0-bookworm-slim` in [Dockerfile](Dockerfile); older host-version observations above are historical. A trusted image build must still record the resolved image ID and package inventory. Federation changes authentication only; the Claude author remains API usage, with actual credit coverage or additional charges determined by the Console billing state.
