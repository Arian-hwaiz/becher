# Verbesserungen bei den Berechnungen und wie Profit entsteht

Stand: 9. November 2026 · ergänzt [01-betburger-analyse-und-konzept.md](01-betburger-analyse-und-konzept.md) und [04-entwicklungsplan-kern.md](04-entwicklungsplan-kern.md)

Kurz: Der Gewinn beim Value-Wetten entsteht nicht durch eine bessere Formel, sondern durch die **Summe vieler kleiner Genauigkeitsgewinne**: bessere faire Quote, richtige Kosten (Steuer!), richtige Einsatzgröße, frische Daten, die richtigen Märkte und Konten, die lange leben. Jeder Punkt unten bringt für sich nur Zehntelprozente. Zusammen entscheiden sie über plus oder minus. Nichts davon garantiert Gewinn; es verschiebt nur die Wahrscheinlichkeiten zu deinen Gunsten.

## 1. Die faire Quote besser schätzen

Das ist der Kern. Ein Fehler von 1 % in der Wahrscheinlichkeit frisst bei Quote 2,00 schon 2 % EV, also oft die ganze Kante.

| Was die üblichen Scanner machen | Was wir besser machen |
| --- | --- |
| Marge gleichmäßig herausrechnen (multiplikativ) | **Mehrere Devig-Methoden** (multiplikativ, Power, Shin, logarithmisch) und pro Markt die Methode nehmen, die am CLV gemessen historisch am besten war. Faustregel: bei Außenseitern Power/Shin, weil Buchmacher dort überproportional Marge legen (Favoriten-Außenseiter-Bias). |
| Eine Referenz (meist Pinnacle) | **Gewichteter Konsens** aus Pinnacle, Betfair-Börse (nur bei ausreichender Liquidität, z. B. > 5.000 € gematcht) und 2 bis 3 weiteren scharfen Quellen. Gewichte lernen, nicht raten: welche Quelle sagt die Schlussquote am besten voraus? |
| Quote ohne Alter | **Zeitstempel und Frische**: Referenz älter als 60 Sekunden (Prematch) bzw. 3 Sekunden (Live) ist kein Value, sondern ein Risiko. EV mit Unsicherheitsabschlag versehen, der mit dem Alter wächst. |
| Linienbewegung ignorieren | **Richtung der Bewegung einrechnen**: Bewegt sich der scharfe Markt gerade auf unsere Seite zu ("Steam"), ist die Kante echt; bewegt er sich weg, ist der Soft-Buchmacher oft nur langsam und die Kante verschwindet gleich. Richtung und Geschwindigkeit der letzten 10 bis 30 Minuten als Merkmal speichern. |
| Nur Wahrscheinlichkeit | **Konfidenzintervall statt Punktschätzung**: Bei dünnen Märkten (3. Liga, Tennis-Challenger) die Unsicherheit größer ansetzen und nur wetten, wenn der EV auch am unteren Rand positiv ist. |

Praktisch: Jede Value-Wette bekommt drei Zahlen: EV nach der Standardmethode, EV konservativ (untere Grenze), und die Frische der Referenz. Gewettet wird nur, wenn der konservative EV über der Schwelle liegt.

## 2. Die echten Kosten einrechnen (werden fast immer vergessen)

- **Deutsche Wettsteuer (5,3 % auf den Einsatz bei lizenzierten Anbietern):** Wird sie vom Gewinn abgezogen, sinkt eine Quote von 2,00 effektiv auf etwa 1,95. Das vernichtet die meisten "2-%-Valuebets". Der Scanner muss pro Buchmacher wissen, ob und wie die Steuer weitergegeben wird (vom Gewinn, vom Einsatz, gar nicht) und mit der **effektiven Quote** rechnen. Steuerfreie Anbieter (z. B. Börsen mit Kommission) separat behandeln.
- **Börsenkommission** (Betfair 2 bis 5 % auf den Nettogewinn) korrekt auf die Quote umlegen.
- **Auszahlungsobergrenzen und Mindesteinsätze** pro Buchmacher und Liga speichern; eine Kante, die man nur mit 2 € spielen darf, ist wertlos.
- **Void-Regeln:** Bei Surebets prüfen, dass beide Seiten dieselben Regeln haben (Tennis-Aufgabe, Verlängerung, Spielabbruch). Sonst ist die "sichere" Wette ein verstecktes Risiko.

## 3. Einsatzgröße: Kelly richtig anwenden

Betburger gibt einen Kelly-Rechner, aber keine Bankroll-Logik. Das Potenzial:

- **Fractional Kelly (1/4 bis 1/2)** statt Voll-Kelly. Voll-Kelly setzt voraus, dass die geschätzte Wahrscheinlichkeit stimmt; sie stimmt nie genau. Viertel-Kelly verliert wenig Wachstum, aber senkt das Risiko eines großen Einbruchs drastisch.
- **Kelly auf den konservativen EV**, nicht auf den optimistischen.
- **Bankroll über alle Konten** als eine Größe führen, nicht pro Buchmacher.
- **Korrelierte Wetten** (zwei Wetten auf dasselbe Spiel oder dieselbe Mannschaft am selben Tag) zusammen begrenzen.
- **Einsätze runden** (z. B. auf 5 oder 10 €), damit das Konto nicht nach Bot aussieht. Das kostet minimal EV, verlängert aber die Lebensdauer des Kontos enorm (siehe Punkt 6).
- **Monte-Carlo-Simulation** der eigenen Strategie: Mit den historischen Kanten 10.000 Saisons simulieren und sehen, wie groß der schlimmste Einbruch realistisch ist. Damit wählst du den Kelly-Bruchteil, mit dem du nachts schlafen kannst.

## 4. CLV als einzige ehrliche Erfolgsmessung

Gewinn und Verlust der letzten 100 Wetten sagen fast nichts; das ist Rauschen. Was zählt: Hast du im Schnitt eine bessere Quote bekommen als die Schlussquote (Closing Line Value)?

- Jede Wette automatisch mit der Pinnacle-Schlussquote (devigged) vergleichen und CLV in Prozent speichern.
- CLV aufschlüsseln nach Buchmacher, Markt, Liga, Devig-Methode, Tageszeit und Zeit bis Anpfiff. Daraus lernst du, wo deine Kante echt ist und wo nicht.
- **Faustregel:** Positiver CLV über 300 bis 500 Wetten = Strategie funktioniert, auch wenn der Kontostand gerade rot ist. Negativer CLV bei grünem Kontostand = Glück, hört auf.
- Das ist auch das Kriterium, mit dem die KI später Vorschläge bewertet: nicht "hat gewonnen", sondern "hatte CLV".

## 5. Die richtigen Märkte und Zeitpunkte

Die Kante ist nicht überall gleich groß. Daten dazu sammeln und auswerten:

- **Wo Softs schwach sind:** Nebenmärkte (Ecken, Karten, Spieler-Props), untere Ligen, Frauenfußball, kleinere Tennis-Turniere, Asian-Handicap-Viertellinien. Dort reagieren Buchmacher langsam. Nachteil: niedrigere Limits.
- **Wann:** Kurz nach Eröffnung der Linien (Buchmacher noch unsicher) und in den letzten 1 bis 2 Stunden vor Anpfiff (Aufstellungen, Steam). Dazwischen ist oft wenig zu holen.
- **Aufstellungen und Nachrichten:** Softs hängen nach Aufstellungs-Bekanntgabe oft 5 bis 15 Minuten hinterher. Ein Collector für Aufstellungen (offizielle Vereinskanäle, API-Anbieter) plus Alarm ist einer der größten Hebel überhaupt.
- **Bonusangebote mathematisch bewerten:** Einzahlungsboni, Gratiswetten und Quotenboosts haben einen berechenbaren EV. Ein Modul, das Umsatzbedingungen in erwarteten Wert umrechnet, ist bei den meisten Scannern nicht vorhanden und für Einsteiger oft der profitabelste Teil.

## 6. Konten am Leben halten (der unterschätzte Profit-Faktor)

Eine Kante nützt nichts, wenn das Konto nach vier Wochen auf 5 € limitiert ist. Ein "Account-Health"-Modul:

- Pro Konto speichern: Einsätze, Märkte, Anteil Value-Wetten, Zeitpunkt der letzten Limitierung.
- Risiko-Score: nur Nebenmärkte, nur Höchstquoten, immer krumme Einsätze, immer Minuten vor Linienbewegung = Muster, die Buchmacher erkennen.
- Gegenmaßnahmen vorschlagen: gelegentlich populäre Märkte spielen, Einsätze runden, Kombi-Wetten mit leicht negativem EV als Tarnung (kostet wenig, verlängert das Konto), Quotenboosts des Buchmachers nutzen (sieht nach normalem Kunden aus).
- Scharfe Buchmacher und Börsen limitieren nicht; sie bieten aber weniger Kante. Die Mischung macht's.

## 7. Surebets präziser

- **Echte Arbs nach Steuer und Kommission** berechnen, sonst sind viele vermeintliche 1,5-%-Arbs in Wahrheit negativ.
- **Ausführungsrisiko** einpreisen: Die Wahrscheinlichkeit, dass die zweite Seite verschwindet, bevor du sie platziert hast. Historisch messen (wie lange lebt eine Arb bei Buchmacher X im Schnitt?). Arbs mit einer Lebensdauer unter deiner Platzierungszeit gar nicht erst anzeigen.
- **Reihenfolge:** Immer zuerst die Seite beim Buchmacher mit der volatileren Quote platzieren, dann die stabile (meist Börse oder Pinnacle).
- **Hedge statt Arb:** Oft ist es besser, nur die Value-Seite zu spielen und nicht zu hedgen; der Hedge kostet Marge. Hedgen nur, wenn die Varianz für die Bankroll zu groß ist.

## 8. Eigene Modelle (erst mit Historie)

Sobald 3 bis 6 Monate Quoten-Historie da sind, kann klassisches Machine Learning (LightGBM, nicht Sprachmodelle) Mehrwert bringen:

- **Schlussquoten-Vorhersage:** Aus Eröffnungsquote, Bewegungen der ersten Stunden, Liga und Buchmacher die Schlussquote schätzen. Trifft das Modell besser als die aktuelle Referenz, hast du eine zweite, unabhängige faire Quote.
- **Lebensdauer von Kanten** vorhersagen, um Ausführungsrisiko zu steuern.
- **Nicht** versuchen, Spielausgänge direkt vorherzusagen. Da sind die scharfen Buchmacher mit vollen Teams besser. Der Vorteil liegt im Preisvergleich und im Timing, nicht in der Spielprognose.

## 9. Was sich wie stark auswirkt (grobe Einschätzung)

| Maßnahme | Wirkung auf den Profit | Aufwand |
| --- | --- | --- |
| Steuer und Kommission korrekt einrechnen | Sehr hoch (verhindert Verlustwetten) | Gering |
| CLV-Messung und Auswahl nach CLV | Sehr hoch (du lernst, wo die Kante echt ist) | Mittel |
| Fractional Kelly mit konservativem EV | Hoch (verhindert Ruin) | Gering |
| Konto-Schutz | Hoch (verlängert die Einnahmezeit) | Mittel |
| Mehrere Devig-Methoden und Konsens-Referenz | Mittel bis hoch | Mittel |
| Aufstellungs-Alarme | Hoch bei Fußball | Mittel |
| Bonus-EV-Rechner | Hoch für Einsteiger, später gering | Gering |
| Frische- und Bewegungsfilter | Mittel | Gering |
| ML-Modelle | Unsicher, erst mit Daten | Hoch |

## 10. Ehrliche Grenzen

- Realistische Kante nach Kosten für einen privaten Value-Wetter bei Soft-Buchmachern: etwa 2 bis 5 % Rendite auf den Umsatz, bevor die Limits kommen. Hohe Renditeversprechen (wie Betburgers Einkommensrechner) sind Marketing.
- Varianz ist brutal: Auch mit echter Kante sind Verlustphasen über Monate normal. Ohne Bankroll-Disziplin überlebt man sie nicht.
- Die Konten sind die knappe Ressource, nicht die Kanten. Deshalb hat Punkt 6 so viel Gewicht.
- Alles hier ist Analyse von Mathematik und Marktmechanik, keine Finanzberatung. Wetten nur mit Geld, dessen Verlust du verkraften kannst.
