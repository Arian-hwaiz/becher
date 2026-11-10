"""FAQ und Glossar für das Dashboard: Begriffe, Abkürzungen, Rechenwege. Reine Daten, keine Logik.

Jeder Eintrag: (Kategorie, Begriff/Frage, Antwort in Markdown). Die Seite „FAQ“ zeigt sie mit Suche an.
"""
from __future__ import annotations

FAQ: list[tuple[str, str, str]] = [
    # ------------------------------------------------------------ Grundbegriffe
    ("Grundbegriffe", "Was ist eine Valuebet?",
     "Eine Wette, bei der ein Buchmacher **mehr zahlt, als die Wahrscheinlichkeit hergibt**. Becher schätzt die echte "
     "Wahrscheinlichkeit aus den Quoten der Referenzen (Pinnacle, Betfair-Börse) und vergleicht.\n\n"
     "Beispiel: Die faire Quote für „Unter 2,5 Tore“ ist 2,00 (50 %). Ein Buchmacher bietet 2,24. "
     "Vorteil = 2,24 ÷ 2,00 − 1 = **12 %**. Eine einzelne Valuebet kann verlieren; der Vorteil zeigt sich erst über viele Wetten."),
    ("Grundbegriffe", "Was ist eine Surebet (Arbitrage, Arb)?",
     "Man setzt bei **verschiedenen Buchmachern auf alle Ausgänge** eines Spiels, und zwar so, dass in jedem Fall ein Gewinn bleibt. "
     "Das geht, wenn die besten Quoten zusammen mehr als 100 % auszahlen.\n\n"
     "Beispiel: Über 2,5 bei A zu 2,10 und Unter 2,5 bei B zu 2,10. Mit je 50 € Einsatz kommen in jedem Fall 105 € zurück, "
     "also **5 % sicherer Gewinn**. Rechnung: 1 ÷ (1/2,10 + 1/2,10) − 1 = 5 %."),
    ("Grundbegriffe", "Was ist ein Middle?",
     "Zwei Wetten mit **unterschiedlichen Linien**, die sich überlappen, zum Beispiel Über 2,5 und Unter 3,5. "
     "Fallen genau 3 Tore, gewinnen beide. In den anderen Fällen gewinnt eine und die andere verliert, oft mit kleinem Verlust. "
     "Ein Middle ist also keine sichere Sache, sondern eine Wette auf die „Mitte“."),
    ("Grundbegriffe", "Was bedeutet die Prozentzahl auf der Trefferkarte?",
     "Bei **Valuebets** der konservative Vorteil (EV) in Prozent des Einsatzes. Bei **Surebets** der sichere Gewinn in Prozent "
     "des Gesamteinsatzes, nach Steuer und Kommission, falls welche eingestellt sind."),
    ("Grundbegriffe", "Was ist eine Dezimalquote?",
     "Die Quote sagt, wie viel man **je 1 € Einsatz zurückbekommt**, Einsatz inklusive. Quote 2,50 und 10 € Einsatz: 25 € zurück, "
     "15 € Gewinn. Die in der Quote steckende Wahrscheinlichkeit ist 1 ÷ Quote, bei 2,50 also 40 %."),
    ("Grundbegriffe", "Warum findet der Scan oft keine Treffer?",
     "Bei großen Ligen und Hauptmärkten liegen die Quoten eng beieinander, echte Vorteile sind selten und kurzlebig. "
     "Mehr Treffer gibt es mit mehr Buchmachern, mehr Ligen, Nebenmärkten und kürzerem Abruftakt. "
     "Becher rechnet außerdem vorsichtig (Unsicherheit, Alter der Referenz) und zeigt lieber nichts als Scheintreffer."),

    # ------------------------------------------------------------ Rechnen
    ("Rechnen", "Faire Quote",
     "Die Quote **ohne die Marge** des Buchmachers. Sie entspricht der geschätzten echten Wahrscheinlichkeit: faire Quote = 1 ÷ Wahrscheinlichkeit. "
     "Becher berechnet sie aus den Quoten der Referenzen."),
    ("Rechnen", "Marge (Overround, Vig, Juice)",
     "Der eingebaute Verdienst des Buchmachers. Zählt man 1 ÷ Quote über alle Ausgänge zusammen, kommt mehr als 100 % heraus. "
     "Der Überschuss ist die Marge. Beispiel 1,90 / 1,90: 52,6 % + 52,6 % = 105,2 %, Marge 5,2 %."),
    ("Rechnen", "Devig (Marge herausrechnen)",
     "Das Verfahren, mit dem aus Quoten mit Marge **faire Wahrscheinlichkeiten** werden. Becher kennt fünf Methoden:\n\n"
     "- **multiplicative**: alle Wahrscheinlichkeiten gleichmäßig herunterskalieren\n"
     "- **additive**: von jeder denselben Betrag abziehen\n"
     "- **power**: Wahrscheinlichkeiten potenzieren, bis die Summe 100 % ergibt (Standard)\n"
     "- **shin**: Modell, das Insider-Wetten annimmt; korrigiert Außenseiter stärker\n"
     "- **logit**: Verschiebung auf der Logit-Skala\n\n"
     "Die Methoden unterscheiden sich vor allem bei Außenseitern."),
    ("Rechnen", "EV (Expected Value, Erwartungswert)",
     "Der **durchschnittliche Gewinn je Einsatz**, wenn man dieselbe Wette sehr oft spielen könnte. "
     "EV = Wahrscheinlichkeit × Quote − 1. Bei 50 % und Quote 2,10: 0,5 × 2,10 − 1 = +5 %."),
    ("Rechnen", "Konservativer EV",
     "Der EV, nachdem Becher die geschätzte Wahrscheinlichkeit um ein **Unsicherheitsband** nach unten korrigiert hat. "
     "Das Band wird größer, wenn die Referenzquote alt ist oder der Markt dünn. Die Trefferkarte zeigt diesen vorsichtigen Wert."),
    ("Rechnen", "Kelly und Viertel-Kelly",
     "Die Kelly-Formel sagt, welcher **Anteil der Bankroll** bei einer Valuebet langfristig am besten ist. "
     "Voller Kelly schwankt stark und setzt eine exakt bekannte Wahrscheinlichkeit voraus, deshalb zeigt Becher ein Viertel davon."),
    ("Rechnen", "Bankroll",
     "Das Geld, das insgesamt fürs Wetten vorgesehen ist. Einsätze werden als Anteil davon angegeben."),
    ("Rechnen", "Wettsteuer und Kommission",
     "In Deutschland ziehen viele Buchmacher **5,3 % Wettsteuer** vom Einsatz ab; an Börsen fällt eine **Kommission** auf den Nettogewinn an "
     "(Betfair meist 5 %). Beides senkt die effektive Quote. In Becher steht die Steuer standardmäßig auf 0 (reiner Quotenvergleich) und lässt sich mit "
     "`python scripts/set_tax.py --country DE` einschalten."),
    ("Rechnen", "Effektive Quote",
     "Die Quote **nach Abzug** von Steuer oder Kommission. Mit ihr rechnen EV und Surebet-Einsätze."),
    ("Rechnen", "Auszahlung in Prozent (Seite „Quoten je Event“)",
     "Wie viel die **besten Quoten aller Buchmacher zusammen** auszahlen. Unter 100 %: Der Markt hat insgesamt noch Marge. "
     "Über 100 %: Surebet (vor Steuer und Kommission)."),

    # ------------------------------------------------------------ Messen
    ("Messen", "CLV (Closing Line Value)",
     "Vergleich der **eigenen Wettquote mit der fairen Schlussquote**. CLV = eigene Quote ÷ faire Schlussquote − 1. "
     "Wer über viele Wetten bessere Quoten bekommt als der Markt zum Schluss, hat nachweislich einen Vorteil, "
     "unabhängig davon, ob einzelne Wetten gewonnen haben. Das ist der ehrlichste Erfolgsmaßstab."),
    ("Messen", "Schlussquote (Closing Line)",
     "Die **letzte Quote vor dem Anpfiff**. Sie gilt als beste Schätzung des Marktes, weil dann alle Informationen eingepreist sind."),
    ("Messen", "ROI (Return on Investment)",
     "Gewinn geteilt durch die Summe der Einsätze. Kurzfristig stark vom Zufall geprägt, deshalb zählt für die Beurteilung der CLV mehr."),
    ("Messen", "Brier-Score und Log-Loss",
     "Zwei Maße dafür, **wie gut vorhergesagte Wahrscheinlichkeiten zu den Ergebnissen passen**. Kleiner ist besser. "
     "Becher bewertet damit, welche Devig-Methode je Markt am besten trifft (Seite „Wetten“, ab 30 abgerechneten Wetten)."),
    ("Messen", "Konto-Risiko (Limitierung)",
     "Buchmacher **begrenzen Einsätze** von Kunden, die dauerhaft gewinnen oder wie Arbitrage-Spieler aussehen. "
     "Becher schätzt je Buchmacher einen Risiko-Score 0 bis 100 aus dem Wettverhalten (hoher CLV, krumme Einsätze, viele Wetten pro Tag)."),

    # ------------------------------------------------------------ Märkte und Abkürzungen
    ("Märkte und Abkürzungen", "1X2, 1 / X / 2 (Sieger, h2h)",
     "Der Markt auf den Spielausgang: **1** = Heimsieg, **X** = Unentschieden, **2** = Auswärtssieg. "
     "Intern heißt der Markt `h2h` (head to head), die Ausgänge `home`, `draw`, `away`."),
    ("Märkte und Abkürzungen", "Über/Unter, O/U, TO und TU (totals)",
     "Wette auf die **Gesamtzahl** der Tore oder Punkte. **TO(2.5)** = Total Over = mehr als 2,5 Tore, also mindestens 3. "
     "**TU(2.5)** = Total Under = höchstens 2. Intern `totals` mit `over` und `under`."),
    ("Märkte und Abkürzungen", "Handicap, AH1 und AH2 (spreads)",
     "Ein Team bekommt einen **Vorsprung oder Rückstand**. **AH1(-1.5)**: Heimteam mit −1,5, es muss mit mindestens 2 Toren gewinnen. "
     "**AH2(+1.5)**: Auswärtsteam mit +1,5, es darf mit einem Tor verlieren. AH steht für asiatisches Handicap. Intern `spreads`."),
    ("Märkte und Abkürzungen", "Linie (Line)",
     "Die Zahl im Markt, also 2,5 bei Über/Unter oder −1,5 beim Handicap. Verschiedene Linien sind verschiedene Märkte."),
    ("Märkte und Abkürzungen", "Halbe, ganze und Viertel-Linien",
     "**Halbe Linien** (2,5) kennen nur Gewinn oder Verlust. Bei **ganzen Linien** (2,0) gibt es bei genau 2 Toren den Einsatz zurück (Push). "
     "**Viertel-Linien** (2,25 oder 2,75) teilen den Einsatz auf die beiden Nachbarlinien, so entstehen halber Gewinn und halber Verlust."),
    ("Märkte und Abkürzungen", "Push, Void, halb gewonnen, halb verloren",
     "**Push/Void**: Einsatz zurück, kein Gewinn, kein Verlust. **Halb gewonnen**: halber Einsatz gewinnt, die andere Hälfte kommt zurück. "
     "**Halb verloren**: halber Einsatz verloren, die andere Hälfte kommt zurück."),
    ("Märkte und Abkürzungen", "DNB, DC, BTTS, HT/FT",
     "Gängige Kürzel bei Buchmachern: **DNB** = Draw No Bet (bei Unentschieden Einsatz zurück), **DC** = Double Chance / Doppelte Chance "
     "(1X, X2 oder 12), **BTTS** = Both Teams To Score (beide Teams treffen), **HT/FT** = Halbzeit/Endstand. "
     "Becher verarbeitet derzeit 1X2, Über/Unter und Handicap."),
    ("Märkte und Abkürzungen", "Prematch und Live",
     "**Prematch**: Quoten vor Spielbeginn. **Live** (In-Play): Quoten während des Spiels, sie ändern sich im Sekundentakt. "
     "Becher arbeitet mit Prematch-Quoten."),

    # ------------------------------------------------------------ Buchmacher
    ("Buchmacher und Quellen", "Referenz, Sharp und Soft",
     "**Sharp** (Referenz): Buchmacher mit kleinen Margen und hohen Limits, deren Quoten sehr genau sind, vor allem Pinnacle. "
     "**Soft**: Buchmacher für Freizeitkunden mit höheren Margen und langsamerer Quotenanpassung. Dort entstehen Valuebets."),
    ("Buchmacher und Quellen", "Wettbörse, Back und Lay",
     "An einer **Börse** (Betfair Exchange) wetten Kunden gegeneinander. **Back** = auf einen Ausgang setzen, "
     "**Lay** = dagegen setzen, also selbst den Buchmacher spielen. Die Börse nimmt Kommission auf den Gewinn."),
    ("Buchmacher und Quellen", "Liquidität",
     "Wie viel Geld an der Börse zu einer Quote **tatsächlich verfügbar** ist. Bei wenig Liquidität ist die Quote wenig aussagekräftig; "
     "Becher nutzt Börsenquoten erst ab einer Mindestliquidität als Referenz."),
    ("Buchmacher und Quellen", "Collector und Scraper",
     "Ein **Collector** holt Quoten aus einer Quelle und speichert sie. Das kann eine API sein (The Odds API, Betfair) "
     "oder ein **Scraper**, der die Quoten direkt von der Seite eines Buchmachers liest. Den Stand zeigt die Seite „Administration“."),
    ("Buchmacher und Quellen", "Credits (The Odds API)",
     "Das Kontingent der Odds-API. Ein Abruf kostet Sportarten × Regionen × Märkte Credits; der kostenlose Plan hat 500 im Monat. "
     "Eigene Scraper kosten keine Credits."),
    ("Buchmacher und Quellen", "Aktiv und inaktiv (Administration)",
     "Ein **inaktiver** Anbieter wird vom Scan ignoriert: keine Treffer bei ihm, und er dient nicht als Referenz. "
     "Seine Quoten werden weiter gesammelt, damit man sieht, ob die Quelle wieder liefert."),
    ("Buchmacher und Quellen", "Scraper-Stand: offen, in Arbeit, läuft, blockiert",
     "Die To-do-Liste der eigenen Scraper: **offen** = noch nicht gebaut, **in Arbeit**, **läuft** = liefert Quoten, "
     "**blockiert** = die Seite hat Bot-Schutz (wird nicht umgangen), **nicht möglich**, **nicht nötig** = kommt über eine offizielle API."),
    ("Buchmacher und Quellen", "Direkt-Link und Startseite",
     "Der Buchmachername auf einer Karte ist ein Link. Liefert die Quelle einen Link zum Spiel, führt er **direkt zum Spiel**, "
     "sonst zur Startseite des Buchmachers."),

    # ------------------------------------------------------------ Dashboard
    ("Dashboard", "Was zeigen die Seiten?",
     "- **Scanner**: aktuelle Valuebets und Surebets als Karten, mit Filter und Einsatzrechner\n"
     "- **Überblick**: Kennzahlen, Quoten pro Stunde, Abdeckung je Buchmacher\n"
     "- **Quoten je Event**: alle Quoten eines Spiels im Vergleich, beste Quote grün, Verlauf\n"
     "- **Wetten**: eigene Wetten erfassen, CLV, Konto-Risiko, Devig-Methoden\n"
     "- **KI**: Einordnung der Treffer und Wochenbericht durch Claude\n"
     "- **Administration**: alle Anbieter, Scraper-Stand, aktivieren und deaktivieren\n"
     "- **Collector-Läufe**: Protokoll der Abrufe"),
    ("Dashboard", "Was bedeutet „Alter“ auf der Karte und „Referenz vor … s“?",
     "**Alter**: wie lange es her ist, dass der Scan den Treffer gefunden hat. **Referenz vor … s**: wie alt die Referenzquote "
     "zum Zeitpunkt des Treffers war. Je älter, desto unsicherer ist der Vorteil."),
    ("Dashboard", "Wie liest man den Einsatzrechner?",
     "Bei **Surebets** verteilt er den gewählten Gesamteinsatz so auf die Wetten, dass in jedem Ausgang derselbe Betrag zurückkommt, "
     "und zeigt den sicheren Gewinn. Bei **Valuebets** zeigt er die effektive Quote, den erwarteten Gewinn und den Viertel-Kelly-Anteil."),
]

CATEGORIES: list[str] = list(dict.fromkeys(c for c, _, _ in FAQ))


def search(term: str) -> list[tuple[str, str, str]]:
    """Einträge, die den Suchbegriff in Titel oder Text enthalten (Groß-/Kleinschreibung egal)."""
    t = term.strip().lower()
    if not t:
        return FAQ
    return [e for e in FAQ if t in e[1].lower() or t in e[2].lower()]
