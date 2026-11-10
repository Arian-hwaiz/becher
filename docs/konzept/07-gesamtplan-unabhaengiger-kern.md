# 07 – Gesamtplan: unabhängiger Kern auf einem Gerät

Stand: 10. November 2026 · rein technisch · baut auf [04-entwicklungsplan-kern.md](04-entwicklungsplan-kern.md), [05-berechnungen-und-profit.md](05-berechnungen-und-profit.md) und [06-betburger-technik-und-mechanik.md](06-betburger-technik-und-mechanik.md) auf · Recherche dazu: [../recherche/2026-11-10-unabhaengiger-kern.md](../recherche/2026-11-10-unabhaengiger-kern.md)

## Ziel in einem Satz

Becher läuft vollständig auf **einem lokalen Gerät am Hausanschluss**, erhebt alle Quoten und Ergebnisse **selbst**, bildet seine **faire Quote selbst** und braucht keinen bezahlten oder schlüsselpflichtigen Fremddienst. Fremdquellen sind nur noch frei lesbare Zusatzsignale, die man abschalten kann, ohne dass der Kern stehen bleibt.

## Was sich gegenüber dem bisherigen Konzept ändert

| Bisher (Dok. 03/04) | Neu |
| --- | --- |
| Start mit Odds-API, eigene Scraper nur ergänzend | **Nur eigene Scraper**; Odds-API-Collector bleibt abgeschaltet im Code |
| Pinnacle bzw. Betfair als scharfe Referenz | **Eigene Referenz**: Konsens aus allen Scrapern + eigenes Modell + optional Polymarket. Pinnacle ist zu, Betfair-Börse für AT/DE geschlossen |
| Hetzner-Server und Länder-Proxies | **Lokales Gerät** am normalen Hausanschluss, kein Rechenzentrum, keine Proxies |
| Scraper öffnet die Seite, liest, schließt (alle 15 min) | **Dauerhaft offene Seiten**, die WebSocket-Updates mithören (Prematch und Live aus demselben Weg) |
| Ein Parser je Buchmacher | **Ein Parser je Plattform**, Marken als Varianten (Clones) |
| Jede Abfrage schreibt alle Quoten | Nur **Änderungen** speichern, aktueller Stand im Speicher |
| Claude-API für die KI-Schicht | **Lokales Modell** (Ollama) als Standard, Claude-API optional |
| Go für Collector (alte Notiz im collectors/README) | bleibt Python; der Engpass ist der Browser, nicht die Sprache |

## Architektur

```
                         ein Gerät (Mini-PC oder Laptop)
┌──────────────────────────────────────────────────────────────────────┐
│  Browser-Pool (1 Chromium, persistentes Profil)                      │
│   ├─ Seite ADMIRAL Bundesliga ──┐   WebSocket/JSON mithören          │
│   ├─ Seite bwin Bundesliga ─────┤                                    │
│   └─ … (eine Seite je Buchmacher × Liga, Live-Seiten getrennt)       │
│                                 ▼                                    │
│  Plattform-Parser  →  Normalisierer (Teams, Märkte, Perioden)        │
│                                 ▼                                    │
│  Quoten-Zustand im Speicher (aktueller Stand je Quote)               │
│       │ nur Änderungen                    │ jede Änderung            │
│       ▼                                   ▼                          │
│  PostgreSQL/Timescale              Rechenkern (ereignisgesteuert)    │
│  (Historie, Ergebnisse, Treffer)    Konsens → Value, Surebet, Middle │
│       ▲                                   │                          │
│  Ergebnis-Sammler                         ▼                          │
│  (Buchmacher-Live, OpenLigaDB,     Treffer-Tabelle → Dashboard,      │
│   football-data.co.uk wöchentlich)  Telegram, CLV, lokale KI         │
└──────────────────────────────────────────────────────────────────────┘
```

Alles in einem Python-Prozess-Verbund unter einem Startskript (`scripts/becher.ps1` bzw. Docker Compose), ohne Kafka oder Redis: Bei einem Gerät und einigen zehntausend Quoten reicht ein Prozess mit einer Warteschlange im Speicher. Betburger braucht Kafka für 750 Buchmacher, wir nicht.

## 1. Datenerhebung

### 1.1 Drei Abrufstufen je Quelle

1. **Direktabruf ohne Browser** (`httpx`/`websockets`): wenn ein JSON- oder WebSocket-Endpunkt ohne Browser-Token antwortet. Am sparsamsten, wenige MB RAM.
2. **Offene Browserseite** (Playwright, Standard): Ligaseite wird einmal geöffnet und bleibt offen; neue Quoten kommen per WebSocket-Frame oder wiederkehrendem XHR, die wir mitlesen. Seite alle 30–60 min neu laden (Speicher, neue Spiele).
3. **Blockiert**: Challenge, Captcha oder 403 → Quelle wird auf „blockiert“ gesetzt und nicht weiter versucht (bestehende Regel).

Umbau im Code: `collectors/page_capture.py` bekommt neben `capture_pages` (einmalig) einen **`LivePage`-Modus**, der Callbacks für jede Antwort und jedes Frame aufruft, statt am Ende eine Liste zurückzugeben. Die vorhandenen Parser (`parse_*`) bleiben, sie bekommen nur kleinere Stücke.

### 1.2 Takt und Last (damit Sperren gar nicht erst entstehen)

- Ein Browser, ein Profil, normale Fenstergröße, Sprache de-AT; nicht parallel dieselbe Seite mehrfach öffnen.
- Neuladen höchstens alle 30 min pro Seite, Spielseiten nur bei Bedarf (Treffer-Kandidat) und max. 1 pro 10 s je Buchmacher.
- Kein Neustart des Browsers bei jedem Lauf; Seiten, die offen bleiben, erzeugen weniger Aufrufe als ständiges Neuladen.
- Pro Buchmacher eine **Gesundheitsanzeige**: letzte Quote, Updates/Minute, Fehler. Fällt der Wert auf 0, Alarm im Admin-Bereich.

### 1.3 Plattformen statt Einzelseiten

Tabelle `platforms` (z. B. `entain`, `kambi`, `admiral`, `betathome`) und je Buchmacher ein Verweis darauf. Ein Parser pro Plattform, dazu je Marke nur URL-Muster und ID-Präfixe. Reihenfolge der nächsten Scraper (jeweils erst 10 min mit F12 testen, ob die Seite offen zugänglich ist):

1. tipp3 fertigstellen (angefangen, österreichisch)
2. Kambi-Marke (Unibet o. Ä.) → ein Parser, mehrere Marken, sehr viele Märkte
3. Entain-Schwestermarken von bwin (gleicher Parser, nur Konfiguration)
4. win2day, NEO.bet, Merkur Bets, mobilebet: Plattform beim Test bestimmen
5. Zusatzmärkte: Interwetten und Winamax Über/Unter über Spielseiten, nur für gefundene Kandidaten

Ziel: **mindestens 10 unabhängige Quotenquellen** für Bundesliga, 2. Bundesliga, österreichische Bundesliga und Premier League. „Unabhängig“ heißt eigene Linienstellung; Clones zählen für Surebets als eigene Konten, für den Konsens nur einmal.

## 2. Referenz ohne Pinnacle: die faire Quote selbst bilden

Für jeden Markt (z. B. Bundesliga, Spiel X, 1X2, volle Spielzeit) entsteht laufend eine faire Wahrscheinlichkeit `p_fair` mit einer Unsicherheit.

**Schritt 1 – Marge je Buchmacher entfernen.** Pro Buchmacher die eigene Marge mit der Methode entfernen, die für diesen Markt historisch am besten war (vorhanden: `engine/devig.py`, `engine/method_eval.py`). Standard: Power für 1X2, multiplikativ für Zwei-Wege-Märkte.

**Schritt 2 – gewichteter Konsens im Log-Odds-Raum.**
`logit(p_fair) = Σ w_b · logit(p_b) / Σ w_b`, nur Buchmacher mit frischer Quote (Prematch ≤ 10 min, Live ≤ 5 s alt), Clones nur einmal.
Gewicht `w_b = Schärfe_b × Frische_b`:
- *Schärfe*: wie gut hat Buchmacher b in den letzten Wochen den **eigenen Schlusskonsens** vorhergesagt (mittlerer Log-Loss bzw. Abweichung zur Schlussquote). Am Anfang alle gleich; einmalig vorkalibrieren mit football-data.co.uk (dort stehen Bet365 und die Pinnacle-Schlussquote nebeneinander, so lässt sich prüfen, wie nah ein Soft-Konsens an Pinnacle liegt).
- *Frische*: fällt exponentiell mit dem Alter der Quote.
- Ausreißer-Schutz: Buchmacher, die mehr als 3 Standardabweichungen vom Median abweichen, fließen nicht in den Konsens ein (sie sind der Kandidat, nicht die Referenz).

**Schritt 3 – Zusatzsignale (optional, abschaltbar).**
- *Polymarket*: wenn es für das Spiel einen Markt mit genug Tiefe gibt, Mittelkurs aus dem Orderbuch als weiterer „Buchmacher“ mit eigenem Gewicht. Lesen geht ohne Schlüssel.
- *Eigenes Modell*: Dixon-Coles bzw. Elo (Basis `penaltyblog`) auf Ergebnissen; liefert 1X2 und Tor-Erwartung. Gewicht klein, weil es keine Nachrichten (Verletzungen, Aufstellung) kennt; nützlich bei dünnen Märkten und als Plausibilitätsprüfung.

**Schritt 4 – Marktübergreifende Konsistenz.** Aus 1X2 und Über/Unter 2,5 lässt sich über ein Poisson-Modell die Tor-Erwartung beider Teams ableiten. Damit werden Über/Unter-Linien, die nur wenige Buchmacher anbieten (3,5; 1,5), aus den dichter besetzten Märkten gestützt.

**Ergebnis je Markt:** `p_fair`, Standardfehler, Anzahl Quellen, Alter der jüngsten/ältesten Quote. Valuebets werden nur mit `n_quellen ≥ 4` und EV am unteren Rand > Schwelle ausgewiesen (konservativer EV aus Dok. 05).

**Was Betburger hier nicht hat:** echte Unsicherheit, gelernte Gewichte, Frische in der Rechnung, Konsistenz zwischen Märkten.

## 3. Berechnungen (Rechenkern)

| Baustein | Status | Änderung |
| --- | --- | --- |
| Devig (5 Methoden) | vorhanden `engine/devig.py` | Gegen `penaltyblog` testen, Methode je Markt automatisch wählen |
| Konsens-Referenz | **neu** `engine/consensus.py` | Abschnitt 2 |
| Valuebet (EV, konservativer EV, Kelly) | vorhanden `engine/valuebet.py` | Referenz = Konsens statt Pinnacle; „Ausreißer-Value“ (ein Buchmacher gegen alle) als eigene Kategorie |
| Surebet/Middle (Auszahlungsmatrix) | vorhanden `engine/surebet.py` | ereignisgesteuert: bei jeder Quotenänderung nur betroffene Märkte neu rechnen |
| Linienbewegung | **neu** | Richtung und Tempo des Konsens über 10/30/60 min; „Steam“ = Konsens bewegt sich schnell, ein Buchmacher hängt hinterher |
| Live-Valuebet | **neu** | wie Prematch, aber Frische ≤ 5 s, Spielstand und Minute als Pflicht (Quote nach Tor ohne Stand ist wertlos) |
| CLV | vorhanden `engine/clv.py` | Schlussquote = Konsens beim Anpfiff (statt Pinnacle) |
| Modell (Dixon-Coles/Elo) | **neu** `engine/model.py` | wöchentliches Training aus Ergebnissen |
| Schärfe-Gewichte | **neu** | nächtlicher Lauf: je Buchmacher Abweichung zum Schlusskonsens der letzten 30 Tage |

Rechenlast ist klein: 10 Buchmacher × 200 Spiele × ~30 Ausgänge = ca. 60.000 Quoten. Eine Neuberechnung eines Marktes dauert Mikrosekunden; selbst ein voller Scan aller Märkte liegt unter einer Sekunde **[Schätzung]**.

## 4. Datenmodell

Bestehende Tabellen bleiben (`bookmakers`, `teams`, `team_aliases`, `events`, `markets`, `odds_snapshots`, `opportunities`, `closing_odds`, `bets`, `collector_runs` …). Ergänzungen:

| Tabelle / Feld | Inhalt | Warum |
| --- | --- | --- |
| `platforms`; `bookmakers.platform_id`, `bookmakers.clone_of` | Plattform und Clone-Beziehung | ein Parser je Plattform; Konsens zählt Clones einmal |
| `markets.type` erweitern | `h2h`, `totals`, `spreads` (AH), `btts`, `dnb`, `double_chance`, `team_totals`, `corners`, `cards` | mehr Märkte = mehr Surebets; Kodierung angelehnt an Betburgers Varianten (Dok. 06) |
| `markets.period` als Pflicht | `ft`, `ft_incl_ot`, `h1`, `h2` | Halbzeitmärkte nicht mit Spielmärkten mischen |
| `event_source_ids.swap_teams` | Buchmacher listet Heim/Gast vertauscht | Fehlerquelle beim Matching |
| `odds_snapshots` → **nur Änderungen** + `last_seen_at` | neue Zeile nur, wenn sich die Quote ändert; sonst `last_seen_at` der aktuellen Zeile hochsetzen (bzw. Tabelle `odds_current`) | 10–50× weniger Zeilen, Frische trotzdem bekannt |
| `odds_current` (UNLOGGED oder nur im Speicher) | aktueller Stand je Buchmacher/Markt/Ausgang | Rechenkern und Dashboard lesen hier, nicht in der Historie |
| `odds_snapshots.is_live`, `score`, `minute` | Live-Kennzeichen und Spielstand zum Zeitpunkt der Quote | Live-Werte nur mit Stand vergleichbar |
| `fair_prices` (Zeitreihe) | Markt, Ausgang, Zeit, `p_fair`, Standardfehler, Anzahl Quellen, Methode | Nachvollziehbarkeit, CLV, Linienbewegung |
| `event_state` | Event, Zeit, Status (geplant/live/beendet/abgesagt), Stand, Minute, Quelle | Live-Logik, Abrechnung |
| `results` | Endstand, Halbzeit, ggf. Ecken/Karten, Quelle, bestätigt ja/nein | Abrechnung, Modelltraining, Bewertung |
| `bookmaker_sharpness` | Buchmacher, Markttyp, Zeitraum, Log-Loss, Gewicht | Gewichte für den Konsens |
| `model_predictions` | Event, Modellversion, Wahrscheinlichkeiten, Tor-Erwartung | Zweitmeinung |
| `scraper_health` | Buchmacher, Seite, letzte Quote, Updates/min, Fehler | Überwachung im Admin-Bereich |
| `historical_odds` (Import) | football-data.co.uk-CSV: Ergebnisse + Quoten inkl. Pinnacle-Schluss | Kalibrierung und Backtest ohne Live-Pinnacle |

Datenmenge **[Schätzung]**: Mit Änderungs-Speicherung 0,5–3 Mio. Zeilen pro Tag in der Hochphase (Wochenende, Live), mit Timescale-Kompression nach 7 Tagen grob 1–5 GB pro Monat.

## 5. Live-Betrieb und Ergebnisse

- **Live-Quoten**: eigene Live-Seiten je Buchmacher (getrennt von Prematch), offen während laufender Spiele der gewählten Ligen. Erst nur Admiral, bwin, bet-at-home (senden bereits per WebSocket).
- **Spielstand**: zuerst aus den Buchmacher-Livedaten selbst (der Stand kommt mit den Quoten), gegengeprüft über eine zweite Quelle (OpenLigaDB oder Polymarket-Sport-WebSocket). Weichen zwei Quellen ab → Live-Treffer für dieses Spiel sperren.
- **Abrechnung**: Endstand aus mindestens zwei Quellen, dann `results.bestätigt = ja`; CLV und Modelltraining nutzen nur bestätigte Ergebnisse.
- **Historie**: football-data.co.uk wöchentlich als CSV laden (Ergebnisse, Statistiken, Schlussquoten).

## 6. Lokale KI

Wie in Dok. 04: Rechnen macht Code, die KI ordnet ein. Neu ist nur der Ort.
- **Standard lokal** über Ollama mit einem 7–8-B-Modell (4-bit): Team-Namen zuordnen, die der Alias-Abgleich nicht schafft; Tagesbericht; Fragen an die Datenbank über vorgegebene, nur lesende Abfragen.
- `engine/ai.py` bekommt einen zweiten Anbieter `ollama` neben `anthropic`, umschaltbar in `.env` (`AI_PROVIDER=ollama`).
- Ohne Grafikkarte ist das Modell langsam (Bericht dauert Minuten), das ist für nächtliche Berichte und gelegentliche Zuordnungen in Ordnung.

## 7. Hardware und Betrieb

| Einsatz | Empfehlung [Schätzung] |
| --- | --- |
| Entwickeln (jetzt, Laptop) | 16 GB RAM reichen für 3–5 Buchmacher und Datenbank; KI aus |
| Dauerbetrieb 24/7 | Mini-PC, 8 Kerne (aktuelle Ryzen- oder Intel-Core-Klasse), **32 GB RAM**, 1 TB NVMe, kabelgebundenes LAN; ca. 400–700 €, 15–35 W |
| Mit größerer lokaler KI (14 B+) | zusätzlich Grafikkarte mit 12–16 GB oder Rechner mit großem gemeinsamem Speicher |

Betrieb: alles startet unsichtbar über ein Skript (Arian will keine offenen Konsolenfenster), Autostart nach Neustart, nächtliches Backup der Datenbank (`pg_dump`) auf eine zweite Platte bzw. ins Repo-fremde Verzeichnis, Neustart des Browsers einmal täglich gegen Speicherlecks.

## 8. Etappen

| # | Etappe | Fertig, wenn |
| --- | --- | --- |
| 1 | **Dauerhafte Seiten**: `LivePage` in `page_capture.py`, Admiral und bwin darauf umstellen, `odds_current` + Änderungs-Speicherung | beide liefern 24 h ohne Neustart, Updates im Sekundenbereich sichtbar |
| 2 | **Mehr Quellen**: tipp3 fertig, Kambi-Marke, Entain-Schwestern, 2–3 weitere aus 1.3; Tabelle `platforms` | ≥ 8 unabhängige Buchmacher für Bundesliga |
| 3 | **Konsens-Referenz** `engine/consensus.py`, `fair_prices`, Scan auf Konsens umstellen | Valuebets erscheinen wieder (mit Anzahl Quellen und Unsicherheit) |
| 4 | **Historie und Kalibrierung**: football-data.co.uk-Import, Messung „Soft-Konsens vs. Pinnacle-Schluss“, Startgewichte | Bericht: Abstand Konsens ↔ Pinnacle-Schluss je Liga |
| 5 | **Ergebnisse und Live-Stand**: `event_state`, `results`, OpenLigaDB-Collector, Stand aus Buchmacher-Live | jedes beendete Spiel hat ein bestätigtes Ergebnis |
| 6 | **Live-Scan**: Live-Seiten, Live-Surebets/Valuebets mit 5-s-Frische | Live-Treffer erscheinen nur mit Spielstand |
| 7 | **Schärfe-Gewichte, Linienbewegung, CLV gegen Konsens** | nächtlicher Lauf aktualisiert Gewichte; Dashboard zeigt Steam |
| 8 | **Eigenes Modell** (Dixon-Coles/Elo) + Polymarket als Zusatzquelle | Modell-Log-Loss gegen Schlusskonsens gemessen |
| 9 | **Lokale KI** über Ollama | Tagesbericht und Namenszuordnung laufen ohne Internet-Dienst |
| 10 | **Gerät für 24/7** einrichten, Autostart, Backup | läuft eine Woche ohne Eingriff |

Etappe 1 bis 3 sind der Hebel: Danach rechnet Becher wieder Valuebets, ganz ohne Fremdreferenz. Etappe 1 und 2 brauchen echte Läufe auf Arians Gerät (die Cloud erreicht die Wettseiten nicht); Etappe 3, 4 und 8 lassen sich weitgehend in der Cloud mit gespeicherten Testdaten bauen.

## 9. Grenzen, ehrlich

- Ein Konsens aus Soft-Buchmachern ist **weniger scharf als Pinnacle**. Er erkennt Ausreißer gut, aber nicht, wenn alle Softs gemeinsam danebenliegen. Wie groß der Abstand ist, misst Etappe 4.
- Live-Surebets halten oft nur Sekunden; ein Hausanschluss und ein Browser sind dafür eher knapp. Prematch bleibt der Schwerpunkt.
- Blockierte Anbieter (Pinnacle, Tipico, Betano) bleiben draußen. Jede neue Quelle kann sich jederzeit ändern oder sperren; deshalb Gesundheitsanzeige und Plattform-Parser.
- Alle Leistungs- und Mengenangaben sind Schätzungen, bis sie auf dem Gerät gemessen sind.
