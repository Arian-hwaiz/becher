# Recherche: Datenquellen und Technik für einen unabhängigen, lokalen Kern

Stand: 10. November 2026 · rein technisch (rechtliche und Firmenthemen auf Arians Wunsch bewusst ausgeklammert) · Grundlage für [07-gesamtplan-unabhaengiger-kern.md](../konzept/07-gesamtplan-unabhaengiger-kern.md)

Kennzeichnung: **[belegt]** = aus einer Quelle unten gelesen, **[Erfahrung]** = eigene Beobachtung beim Bau der Becher-Scraper, **[Schätzung]** = nicht gemessen, muss auf dem Gerät nachgeprüft werden.

## 1. Kernbefund in fünf Sätzen

1. Eine **scharfe Fremdreferenz gibt es für uns praktisch nicht mehr**: Pinnacle hat die öffentliche API am 23. Juli 2025 geschlossen und blockt Scraping, und die Betfair-Börse ist für Kunden mit Wohnsitz in Österreich (seit 2014) und Deutschland (seit 2012) geschlossen. **[belegt]**
2. Becher muss deshalb seine **faire Quote selbst bilden**: aus dem Konsens vieler selbst erhobener Buchmacher (wie Betburgers „Avgline“), ergänzt um ein eigenes Modell und optional um frei lesbare Prognosemärkte (Polymarket). **[Schlussfolgerung]**
3. Die meisten Buchmacher-Seiten liefern ihre Quoten **live per WebSocket**; wer die Seite offen lässt und zuhört, statt sie alle 15 Minuten neu zu laden, bekommt Live-Daten, braucht weniger Aufrufe und fällt weniger auf. **[Erfahrung: Admiral, bet-at-home, Winamax senden per WebSocket]**
4. Viele Marken teilen sich **dieselbe Quoten-Plattform**; ein Parser pro Plattform deckt dann mehrere Buchmacher ab (Betburger nennt das „Clones“: ca. 150 Buchmacher plus 600 Clones). **[belegt: Dokument 06]**
5. Alles passt auf **ein lokales Gerät** am normalen Hausanschluss: Engpass ist der Arbeitsspeicher für die Browser, nicht die CPU oder die Datenbank. **[Schätzung, Abschnitt 6]**

## 2. Referenzquellen (wer sagt uns, was die „faire“ Quote ist?)

| Quelle | Zugang ohne Fremd-API-Abo? | Für Becher | Befund |
| --- | --- | --- | --- |
| Pinnacle | Nein | entfällt | Öffentliche API seit 23.07.2025 zu, nur noch auf Antrag für ausgewählte Großkunden/Partner/Forschung; Website blockt Scraper (Cloudflare 403). **[belegt + Erfahrung]** |
| Betfair-Börse | Nein (für AT/DE) | entfällt vorerst | Börse für AT-Kunden seit 14.07.2014, für DE-Kunden seit 09.11.2012 geschlossen. Delayed-Key wäre kostenlos (1–180 s Verzögerung, nur 3 Preisstufen), braucht aber ein Börsenkonto; Live-Key 499 £. **[belegt]** Der vorhandene `collectors/betfair.py` bleibt als Option liegen. |
| Matchbook, Smarkets | Nein | entfällt | Direkter Zugang nur mit verifiziertem, eingezahltem Konto, viele Länder gesperrt. **[belegt, Herstellerblog]** |
| **Konsens der eigenen Scraper** | Ja | **Hauptreferenz** | Je mehr unabhängige Buchmacher, desto besser. Marge je Buchmacher entfernen, dann gewichtet mitteln (Abschnitt 5 im Plan). |
| **Polymarket** | Ja, Lesen ohne Schlüssel | Zusatzreferenz (optional) | Marktdaten öffentlich ohne Zugangsdaten: `gamma-api.polymarket.com` (Märkte), `clob.polymarket.com` (Orderbuch), WebSocket `ws-subscriptions-clob.polymarket.com/ws/market`, Sport-WebSocket `sports-api.polymarket.com/ws` (Spielstand). Die Ländersperre betrifft nur das Handeln (DE „close-only“, AT nicht gelistet), nicht das Lesen. Fußball-Abdeckung und Liquidität je Spiel müssen wir selbst prüfen. **[belegt]** |
| **Eigenes Modell** | Ja | Zweitmeinung | Dixon-Coles/Elo auf Ergebnisdaten, kalibriert an historischen Pinnacle-Schlussquoten (football-data.co.uk, unten). |

Ehrliche Grenze: Ein Konsens aus Soft-Buchmachern ist **weniger scharf als Pinnacle**. Er findet zuverlässig „Ausreißer“ (ein Buchmacher weicht vom Rest ab), aber nicht den Fall, dass alle Softs gemeinsam falsch liegen. Deshalb zusätzlich Modell und Polymarket, und Erfolg wird am CLV gegen den eigenen Schlusskonsens gemessen.

## 3. Buchmacher: was technisch geht

Bisherige Erfahrung aus dem Repo (`collectors/README.md`), Abruf ohne Login per Playwright:

| Buchmacher | Status | Datenweg | Notiz |
| --- | --- | --- | --- |
| ADMIRAL (admiral.at) | läuft | WebSocket der Ligaseite | h2h, alle Totals-Linien; Arian wichtig |
| bwin | läuft | JSON `widgetdata` | Entain-Plattform, dieselbe Technik vermutlich bei Schwestermarken (sportingbet, gamebookers u. a.), **prüfen** |
| bet-at-home | läuft | WebSocket (WAMP) | h2h, Totals-Hauptlinie |
| Interwetten | läuft | HTML | nur 1X2 auf der Ligaseite |
| Winamax | läuft | socket.io | nur 1X2 |
| tipp3 | angefangen | Ligaseite | Parser unfertig |
| Pinnacle, Tipico, Betano | blockiert | – | Bot-Schutz; wird nicht umgangen |

Kandidaten für die nächsten Scraper (Plattform **vermutet**, beim ersten Öffnen mit F12 prüfen):

| Kandidat | Warum interessant | Vermutete Plattform |
| --- | --- | --- |
| Unibet, LeoVegas | Kambi-Plattform: ein Parser, mehrere Marken, sehr viele Märkte | Kambi |
| win2day (Österreich) | lokaler Anbieter, eigene Linien | eigene/Lotterien-Plattform, prüfen |
| NEO.bet, Bet3000, Merkur Bets, mobilebet | deutsche/österreichische Softs | teils White-Label, prüfen |
| bet365 | wichtigster Soft-Markt | starker Bot-Schutz erwartet, nur testen |
| Betway, 22bet/1xBet-Familie | viele Märkte, viele Clones | eigene Plattformen, prüfen |

Faustregeln aus der bisherigen Arbeit **[Erfahrung]**:
- Seiten, die beim ersten normalen Aufruf von einem Hausanschluss eine Challenge zeigen, bleiben auch mit Geduld zu. Kandidaten früh testen, nicht erst Parser bauen.
- Ligaseiten sind ergiebiger als Spielseiten (ein Aufruf, viele Spiele). Spielseiten nur für Zusatzmärkte und nur für Spiele, bei denen der Scan etwas sieht.
- Der Datenweg (JSON, WebSocket, HTML) ist pro Plattform stabil; Layoutänderungen brechen HTML-Parser öfter als JSON-Parser.

## 4. Live-Daten und Ergebnisse

| Bedarf | Quelle | Befund |
| --- | --- | --- |
| Live-Quoten | dieselben Buchmacher-WebSockets, Seite bleibt offen | Grundlage für Live-Surebets; Frische < 3 s nötig (Betburger pollt Live alle 3 s). **[belegt Dok. 06 + Erfahrung]** |
| Live-Spielstand | a) Buchmacher-Livedaten (Admiral/bwin senden Stand und Minute mit), b) Polymarket Sport-WebSocket, c) OpenLigaDB | OpenLigaDB: frei, ohne Anmeldung, Community-gepflegt (bl1, bl2, bl3, pl, la1, ucl, dfb …), Lizenz ODbL. Ob Tore in Echtzeit kommen, ist nicht belegt. **[belegt]** |
| Endergebnisse (Abrechnung, Modell) | OpenLigaDB, football-data.co.uk, Ergebnisseiten der Buchmacher | Für die Abrechnung reicht „Endstand bis 30 min nach Abpfiff“. |
| Historie fürs Modell und Backtest | **football-data.co.uk** (CSV-Dateien, keine API) | Ergebnisse, Halbzeit, Schüsse, Ecken, Karten, xG; Quoten Pinnacle (PSH/PSD/PSA), Bet365, Betfair-Börse, Max/Avg, jeweils auch als **Schlussquote** (Suffix C), Über/Unter 2,5 und Asian Handicap. Ligen u. a. DE, AT, EN, ES, IT, FR. Update zweimal pro Woche. **[belegt]** |

Der football-data.co.uk-Bestand ist der wichtigste Fund für die Unabhängigkeit: Damit lässt sich einmalig messen, **wie gut unser Konsens bzw. Modell die Pinnacle-Schlussquote trifft**, ohne Pinnacle je live abzufragen.

## 5. Bausteine aus Open Source (lokal, ohne Dienst)

| Paket | Nutzen |
| --- | --- |
| `penaltyblog` (Python) | Devig-Methoden multiplikativ, additiv, Power, Shin, Differential Margin Weighting, Odds Ratio, logarithmisch; Dixon-Coles, Poisson- und Elo-Modelle. Zum Gegenprüfen unserer `engine/devig.py` und als Modellbasis. **[belegt]** |
| `rapidfuzz` | schon im Einsatz fürs Matching |
| `websockets` / `httpx` | Direktabruf, wenn ein Endpunkt ohne Browser antwortet |
| Playwright (Chromium) | schon im Einsatz; dauerhaft offene Seiten statt Neustart |
| Ollama + offenes Modell (z. B. Qwen/Llama-Klasse 7–14 B) | lokale KI für Namenszuordnung, Berichte, Fragen an die Datenbank (statt Claude-API) |

## 6. Hardware: was ein Gerät leisten muss

Messwerte **[belegt]**: ein Chromium (Playwright, headless) braucht in Ruhe ca. **700 MB** Spitze inkl. Python-Treiber; WebKit ca. 590 MB. Abschalten von Bildern/Schriften spart, kann aber auffälliger wirken.

Hochrechnung **[Schätzung]** für 10–15 Buchmacher, 5–10 Ligen, Prematch plus Live:

| Teil | RAM | CPU | Platte |
| --- | --- | --- | --- |
| 1 Chromium mit 10–20 offenen Seiten (eine pro Buchmacher-Liga) | 3–6 GB | 1–2 Kerne | – |
| Python-Prozesse (Collector, Scan, Dashboard) | 1–2 GB | 1 Kern | – |
| PostgreSQL/Timescale | 2–4 GB | gering | 1–5 GB/Monat komprimiert bei Speicherung nur der Änderungen |
| Lokales Sprachmodell 7–8 B (4-bit) | 6–8 GB | ohne Grafikkarte langsam (einige Wörter/s) | 5 GB |
| **Summe** | **ca. 16 GB ohne KI, 32 GB mit KI** | 6–8 Kerne reichen | 1 TB NVMe reichlich |

Folgerung: Ein **Mini-PC mit 8 Kernen, 32 GB RAM, 1 TB NVMe** (Größenordnung 400–700 €, 15–35 W im Dauerbetrieb) [Schätzung] trägt den ganzen Kern inklusive kleinem KI-Modell. Ein Laptop reicht zum Entwickeln, ist für 24/7 aber unpraktisch (Ruhezustand, Akku, Lüfter). Ein Raspberry Pi ist für mehrere Chromium-Instanzen zu knapp. Eine Grafikkarte lohnt erst, wenn die lokale KI größer als ~8 B sein soll.

## Quellen

- Pinnacle-API-Schließung: [TheRundown – Pinnacle API alternative](https://therundown.io/blog/pinnacle-api-alternative), [odds-api.io – Pinnacle shutdown](https://odds-api.io/blog/pinnacle-api-shutdown-alternatives) (beide Anbieter von Ersatz-APIs, verweisen auf das README von github.com/pinnacleapi)
- Betfair Application Keys: [Betfair Developer Docs](https://betfair-developer-docs.atlassian.net/wiki/spaces/1smk3cen4v3lu3yomq5qye0ni/pages/2687105/Application+Keys)
- Betfair-Börse AT/DE: [wettbasis.com – Betfair schließt Wettbörse in Österreich](https://www.wettbasis.com/sportwetten-news/betfair-schliesst-wettboerse-in-oesterreich), [InterGame – Betfair pulls out of Germany](https://www.intergameonline.com/igaming/news/betfair-pulls-out-of-germany-in-tax-row)
- Matchbook: [OddsPapi-Blog zu Matchbook](https://oddspapi.io/blog/?p=2848) (Anbieterblog)
- football-data.co.uk: [notes.txt](https://www.football-data.co.uk/notes.txt), [matches.php](https://www.football-data.co.uk/matches.php)
- OpenLigaDB: [openligadb.de](https://www.openligadb.de), [Beispiele auf GitHub](https://github.com/OpenLigaDB/OpenLigaDB-Samples)
- Polymarket: [API-Überblick](https://docs.polymarket.com/), [Geoblock](https://docs.polymarket.com/api-reference/geoblock)
- Playwright-Speicherbedarf: [datawookie.dev – Playwright Browser Footprint](https://datawookie.dev/blog/2025/06/playwright-browser-footprint/)
- penaltyblog: [Implied Odds](https://penaltyblog.readthedocs.io/en/master/implied/implied.html)
- Betburger-Mechanik: [06-betburger-technik-und-mechanik.md](../konzept/06-betburger-technik-und-mechanik.md)
