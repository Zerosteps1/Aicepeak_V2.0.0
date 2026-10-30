# Aicepeak – Nordstern

## 1. Leitbild und Geltung

## Aicepeak verbindet das Wissen über ein Unternehmen mit seiner finanziellen Entwicklung und mit relevanten Informationen aus der Außenwelt. Der Kern ist Financial und Commercial Modelling: stark KI-gestützt, aber deterministisch reproduzierbar und vollständig nachvollziehbar. 

Aicepeak soll ein vollständig nachvollziehbares, KI-gestütztes Forecasting-Tool sein, das interne Unternehmens- und Finanzdaten mit relevanten externen Marktinformationen verbindet. Es soll auf Ebene einzelner Finanzpositionen erklären, wie ein Forecast zustande kommt, und sich bei neuen Informationen gezielt aktualisieren lassen. Controller und Finanzverantwortliche behalten die Kontrolle und können die Ergebnisse auch in Excel weiterbearbeiten.

Dieses Dokument beschreibt, **was das fertige Produkt können soll**, nicht, wie es technisch gebaut wird. Es ist der gemeinsame Bezugspunkt für Produktentscheidungen, spätere Anforderungen, Implementierung und Reviews. Es beschreibt den Zielzustand, noch keine Aufteilung in MVP und spätere Releases.

## 2. Für wen wir das Produkt bauen

| Nutzergruppe | Was sie mit Aicepeak erreichen soll |
| --- | --- |
| Controller und Finanzverantwortliche | Daten prüfen, Planungsannahmen verstehen und beeinflussen, Forecasts erstellen und aktualisieren, Ergebnisse nachvollziehen und in Excel weiterbearbeiten. |
| Fachliche Wissensträger im Unternehmen | Unternehmenskontext, relevante Märkte, Ressourcen und operative Annahmen einbringen und vorgeschlagene Zusammenhänge validieren. |
| Geschäftsführung und Management | Die erwartete Geschäftsentwicklung, wesentliche Einflussfaktoren, Veränderungen und Risiken verstehen und als Entscheidungsgrundlage nutzen. |

Diese Gruppen beschreiben den fachlichen Bedarf, noch kein technisches Rollen- oder Berechtigungssystem. Menschen und Coding Agents nutzen dieses Dokument zusätzlich als Orientierung für die Entwicklung.

Aicepeak soll **branchenübergreifend** funktionieren. Papierproduktion ist ein anschauliches Beispiel, keine fachliche Begrenzung des Produkts.

## 3. Welche Daten das Produkt zusammenführt

| Datenbasis | Beispiele und Bedeutung |
| --- | --- |
| Historische Finanzdaten | Ist-Umsätze, Ist-Kosten, Kostenentwicklungen und weitere Positionen der Gewinn- und Verlustrechnung (GuV). Sie beschreiben die tatsächliche Vergangenheit. |
| Frühere Planungen | Alte Forecasts, Budgets und andere Planungsstände. Sie müssen als damalige Erwartungen erkennbar bleiben und dürfen nicht mit Ist-Daten vermischt werden. |
| Unternehmensunterlagen | PDFs, CSVs, Tabellen, Exporte und weitere relevante Dateien sowie Transkripte und Notizen. Sie liefern Zahlen und qualitativen Kontext. |
| Angaben zum Unternehmen | Geschäftstätigkeit, Produkte, Absatzmärkte, Beschaffungsregionen, Rohstoffe, Energiebedarf und weitere relevante Abhängigkeiten. |
| Externe Informationen | Nachrichten, Marktpreise, Zeitreihen und andere relevante Informationen aus Internet und Datenbanken, etwa zu Energie, Rohstoffen, Arbeitskosten oder wirtschaftlichen und geopolitischen Entwicklungen. |

Interne Dokumente und Unternehmensangaben bestimmen gemeinsam, welche externen Informationen für einen Forecast relevant sind. Das Produkt soll diese Zusammenhänge erkennen, dem Nutzer verständlich machen und zur Prüfung vorlegen können.

## 4. Verbindliche Kernanforderungen

Die folgenden Anforderungen bilden den Produktkern. Ihre Kennungen dienen als stabile Referenzen für spätere Arbeitspakete und Reviews.

### AIC-01 – Mehrere Forecast-Projekte und frei wählbare Zeiträume

Nutzer können mehrere Forecast-Projekte anlegen und je Projekt festlegen, von wann bis wann sie forecasten möchten. Daten, Unternehmenskontext, Annahmen und Ergebnisse müssen dem jeweiligen Projekt und Forecast zugeordnet bleiben. Unterschiedliche Berechnungsstände müssen unterscheidbar sein, damit eine Aktualisierung nachvollzogen werden kann.

### AIC-02 – Daten aufnehmen, extrahieren und validieren

Aicepeak nimmt die beschriebenen internen Daten auf und erschließt sie mit KI. Finanzinformationen werden sauber in **Line Items**, also einzelne Finanzpositionen wie Umsatz, Stromkosten oder Personalkosten, zerlegt und klassifiziert.

Dabei muss erkennbar sein, was Ist-Daten, frühere Forecasts, andere Planwerte oder qualitative Annahmen sind. Werte müssen mit ihrem Zeitraum, ihrer Bedeutung und ihrer Fundstelle nachvollziehbar bleiben. Bei alten Forecasts sind der damalige Planungsstand und der prognostizierte Zeitraum auseinanderzuhalten.

Nutzer können extrahierte Werte und Zuordnungen kontrollieren, korrigieren und bestätigen. Fehlende, widersprüchliche oder unsicher erkannte Informationen müssen sichtbar werden; sie dürfen nicht unbemerkt als gesicherte Daten in den Forecast eingehen.

### AIC-03 – Unternehmenskontext aufbauen

Aus Unterlagen und Nutzerangaben entsteht ein fachlich verständliches Unternehmensprofil. Ein ergänzendes Profilformular soll dort helfen, wo die Dokumente nicht genug Kontext liefern; bereits bekannte Informationen sollen nicht unnötig erneut abgefragt werden.

Beispiel: Ein Papierhersteller verkauft in Deutschland, Österreich und der Schweiz, beschafft in mehreren Ländern und benötigt Zellstoff, Recyclingpapier, Strom und Gas. Diese Angaben machen verständlich, welche Märkte und Entwicklungen für seine Planung relevant sind. Nutzer können das Profil prüfen und anpassen.

### AIC-04 – Relevante News und Marktdaten erschließen

Aicepeak recherchiert auf Basis des Unternehmensprofils und der Dokumente gezielt forecastrelevante Nachrichten und Marktdaten. Es soll die für das Unternehmen wesentlichen externen Einflüsse möglichst umfassend erfassen – einschließlich Risiken, soweit sie die Finanzplanung beeinflussen können.

Ein **Marktdashboard** zeigt relevante Marktentwicklungen und Trends. Ein **News-Dashboard** macht Nachrichten zugänglich und ermöglicht eine erneute Suche bei Bedarf. Quellen, Zeitbezug und die Begründung der Unternehmensrelevanz müssen nachvollziehbar sein. Wesentliche Aussagen sollen nach Möglichkeit durch mehrere voneinander unabhängige Quellen gestützt werden; fehlende Bestätigung und Widersprüche bleiben sichtbar.

### AIC-05 – Business Modeling und Zuordnung zu Finanzpositionen

Das Produkt bildet verständlich ab, wie das Geschäft funktioniert und welche Faktoren Umsatz und Kosten beeinflussen. Dieses Business Modeling verbindet Unternehmenswissen, Finanzpositionen und externe **Market Driver**, also Einflussgrößen wie Strompreis, Rohstoffpreis oder Nachfrageentwicklung.

Relevante News und Marktdaten werden diesen Treibern und den betroffenen Line Items zugeordnet. Nutzer können nachvollziehen, warum ein Zusammenhang vorgeschlagen wurde, und Zuordnungen sowie Wirkungsannahmen prüfen und verändern. Eine Nachricht allein rechtfertigt noch keine automatische numerische Veränderung einer Finanzposition.

### AIC-06 – Quantitativ fundierte Forecasts pro Line Item

Aicepeak berechnet aus historischen Daten, Unternehmenskontext, Annahmen und relevanten Markteinflüssen einen plausiblen Forecast pro Line Item. Daraus entsteht ein in sich konsistenter Gesamtforecast für die GuV. Das Ziel umfasst Umsatz und sämtliche relevanten GuV-Positionen, nicht nur ausgewählte Kostenarten.

**Die Berechnung darf keine frei erfundene Zahlenantwort eines LLM sein.** Sie muss einer expliziten, nachvollziehbaren und reproduzierbaren quantitativen Logik folgen. KI kann Informationen erschließen, Zuordnungen und Annahmen vorschlagen und Ergebnisse erklären. Zahlen müssen aus der ausgewiesenen Berechnungsgrundlage ableitbar sein.

Gleiche Daten, Annahmen und festgehaltene Berechnungseinstellungen müssen zu reproduzierbaren Ergebnissen führen. Unsicherheit, Datenlücken und Grenzen der Aussagekraft bleiben erkennbar. „Plausibel“ bedeutet fachlich begründet und überprüfbar, nicht garantiert richtig.

### AIC-07 – Bei neuen Informationen gezielt neu rechnen

Nutzer können neue Marktinformationen recherchieren und ihren Forecast **per Knopfdruck aktualisieren**. Dabei muss sichtbar werden, welche neuen Informationen berücksichtigt wurden, welche Annahmen sich geändert haben und welche Line Items und Gesamtergebnisse dadurch beeinflusst werden.

Der vorherige Stand bleibt nachvollziehbar. Das Produkt darf nicht unbemerkt Annahmen austauschen oder historische Trends und neue Markteffekte doppelt anrechnen.

### AIC-08 – Transparenz, Mindmap und fachliche Kontrolle

Jeder Forecast muss bis zu seinen wesentlichen Daten, Quellen, Zuordnungen, Annahmen und Berechnungsschritten nachvollziehbar sein. Nutzer können fachliches Feedback geben und relevante Annahmen und Einflussstärken verändern; Gewichtungen sollen bearbeitbar sein, soweit sie Bestandteil des verwendeten Verfahrens sind.

Eine **Mindmap mit Konnektoren pro Forecast** macht die Zusammenhänge sichtbar: welche internen Daten und News welche Treiber stützen, welche Finanzpositionen diese beeinflussen und wie daraus Ergebnisse entstehen. Sie dient als Werkzeug zum Verstehen, Prüfen und Rückmelden, nicht nur als Illustration.

### AIC-09 – Mit dem Forecast chatten

Ein integrierter LLM-Chat beantwortet Fragen im Kontext des jeweiligen Forecasts, seiner Daten, Annahmen, Berechnung und Quellen. Beispielsweise:

- „Warum wurde diese Position angepasst?“
- „Wie beeinflusst diese Nachricht das Line Item Stromkosten?“
- „Wie hat die Engine diesen Wert berechnet?“
- „Was hat sich gegenüber dem vorherigen Forecast verändert?“
- „Welche neuen Nachrichten sind für unser Unternehmen relevant?“

Der Chat schafft zusätzliche Transparenz und verweist auf die tatsächliche Grundlage seiner Antworten. Er unterscheidet zwischen belegten Informationen, Modellannahmen und offenen Fragen. Er darf keine Erklärung erfinden, die nicht der tatsächlich verwendeten Berechnung entspricht.

### AIC-10 – In Excel weiterarbeiten

Nutzer können den Forecast als Excel-Datei exportieren und darin fachlich weiterarbeiten. Der Export soll Ergebnisse und die für ihre Prüfung und Bearbeitung relevanten Eingaben, Annahmen und Zusammenhänge verständlich mitgeben. Ein reiner Export statischer Ergebniszahlen erfüllt diesen Anspruch nicht.

Anpassbare Annahmen und Parameter sollen auch außerhalb des Tools nutzbar sein, etwa Gewichtungen, soweit das gewählte Verfahren dies sinnvoll erlaubt. Welche Berechnungen vollständig in Excel nachvollzogen und neu gerechnet werden können, ist noch zu konkretisieren. Grenzen müssen klar sein; eine vollständige Nachbildung jeder möglichen Forecast-Engine in Excel ist damit noch nicht festgelegt.

### AIC-11 – Hohe Qualität bei wirtschaftlicher Nutzung

Aicepeak darf leistungsfähige KI-Modelle verwenden, wenn sie die Qualität sinnvoll verbessern. Gleichzeitig müssen die Kosten so niedrig bleiben, dass Nutzer Forecasts wiederholt und bei Bedarf aktualisieren können. Eine einzelne Berechnung darf wirtschaftlich nicht zum Hindernis werden.

Der Anspruch ist ein alltagstaugliches Werkzeug für Finanzteams: fachlich belastbar, verständlich bedienbar und mit vertretbarem Prüfaufwand nutzbar. Konkrete Zielwerte für Kosten, Laufzeit und Ergebnisqualität werden separat festgelegt.

## 5. Durchgängiges Beispiel: Stromkosten

Das folgende Beispiel ist hypothetisch und beschreibt das gewünschte Verhalten, keine feste Rechenregel:

1. Ein Unternehmen lädt historische Ist-Kosten und alte Forecasts hoch. Aicepeak erkennt und trennt beides; der Nutzer prüft die extrahierten Positionen.
2. Aus den Unterlagen wird sichtbar, dass die Stromkosten historisch gestiegen sind. Zusammen mit dem Unternehmenskontext entsteht eine begründete Ausgangsplanung.
3. Neue, nachvollziehbar belegte Marktinformationen deuten auf steigende Strompreise in Österreich hin.
4. Aicepeak ordnet die Information dem Treiber Strompreis und der Position Stromkosten zu. Die tatsächliche Wirkung hängt von der Situation des Unternehmens ab, beispielsweise Preisbindung, Verbrauch und zeitlichem Wirksamwerden.
5. Der Nutzer prüft die Annahmen und aktualisiert den Forecast. Eine Marktpreissteigerung von beispielsweise 20 % wird nicht ungeprüft zu 20 % höheren gesamten Stromkosten oder einem pauschalen Aufschlag auf den bisherigen Trend.
6. Ergebnis, Veränderung und Begründung sind in der Finanzansicht, der Mindmap, im Chat und im Excel-Export nachvollziehbar.

Dasselbe Prinzip soll auf andere relevante Treiber und Branchen übertragbar sein.

## 6. Mögliche Erweiterung

**Board-Präsentationen:** Perspektivisch kann Aicepeak aus einem Forecast hochwertige Management- oder Board-Präsentationen erzeugen. Zahlen, Kernaussagen und Begründungen müssen auf den zugrunde liegenden Forecast zurückführbar und vor Verwendung prüfbar sein.

Diese Funktion ist ausdrücklich eine mögliche Erweiterung und noch keine verbindliche Kernanforderung.

## 7. Was dieser Nordstern bewusst offenlässt

- **Forecasting-Verfahren:** Bayesian Regression, Monte-Carlo-Simulationen und TimesFM wurden als mögliche Ansätze genannt. Keines dieser Verfahren ist hier vorgeschrieben. Entscheidend sind die fachlichen Anforderungen an Berechnung, Transparenz und Qualität.
- **Technische Umsetzung:** Technologie-Stack, KI-Anbieter, Such- und Scraping-Verfahren, Datenbanken, Schnittstellen und Softwarearchitektur werden erst anschließend definiert.
- **Umfang des ersten Releases:** Die Reihenfolge und die Aufteilung des Zielbilds in umsetzbare Schritte sind noch festzulegen.
- **Zusätzliche Produktbereiche:** Bilanz- oder Cashflow-Planung, feste ERP-Anbindungen, automatisches Zurückschreiben in Drittsysteme und Excel-Reimport sind durch diesen Input noch nicht als Anforderungen beschlossen.

Offen bedeutet nicht ausgeschlossen. Solche Entscheidungen werden fachlich getroffen und anschließend dokumentiert; sie dürfen nicht stillschweigend durch die Implementierung entstehen.

## 8. Leitplanken für die neue Entwicklung

Der Neustart erfolgt in einem neuen Repository. Die Entwicklungsdokumentation wird in GitHub geführt. **Dieser Nordstern bleibt die zentrale Definition des Produkts**; technische Dokumentation konkretisiert seine Umsetzung und ersetzt ihn nicht.

Agents sollen den größten Teil des Codes schreiben und Änderungen über Pull Requests einbringen. Mehrere Review- und Feedbackschleifen sowie menschliche Reviews gehören zum vorgesehenen Entwicklungsprozess. Die genaue Organisation der Softwarefabrik und die Architektur des eigentlichen Produkts sind getrennte, nachfolgende Entscheidungen. Ihre Einrichtung ist keine Voraussetzung dafür, diesen Nordstern festzuhalten.

Für Menschen und Coding Agents gilt:

- Arbeitspakete und Änderungen auf die relevanten AIC-Anforderungen beziehen.
- Produktanforderungen nicht aus alten Repositories oder technischen Bequemlichkeiten ableiten.
- Offene Entscheidungen als solche behandeln und bei fachlichen Lücken gezielt rückfragen.
- Änderungen am Zielbild bewusst und mit fachlicher Prüfung in diesem Dokument festhalten.
- Keine zusätzlichen Altprojekt-Kontextdateien als konkurrierende Produktwahrheit in das neue Repository übernehmen.

## 9. Woran wir das Zielbild prüfen

Der Produktkern ist erreicht, wenn ein Finanzteam den folgenden Ablauf durchgängig bewältigen kann:

1. Ein Forecast-Projekt mit Zeitraum anlegen und interne Daten sowie Unternehmenskontext bereitstellen.
2. Extrahierte Line Items prüfen und Ist-Daten eindeutig von früheren Planungen unterscheiden.
3. Relevante Marktinformationen finden und deren Quellen und Unternehmensbezug verstehen.
4. Einen quantitativ begründeten Forecast über die relevanten GuV-Positionen erstellen.
5. Die wesentlichen Ergebnisse bis zu Daten, Treibern und Annahmen zurückverfolgen und fachlich korrigieren können.
6. Mit neuen Informationen neu rechnen und die Veränderung zum vorherigen Stand verstehen.
7. Über Dashboard, Mindmap und Chat konsistente Erklärungen zum selben Forecast erhalten.
8. Das Ergebnis in Excel sinnvoll weiterbearbeiten und den Prozess zu wirtschaftlich tragbaren Kosten wiederholen.

