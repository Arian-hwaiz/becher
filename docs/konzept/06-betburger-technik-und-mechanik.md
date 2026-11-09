# 06 – Wie Betburger technisch arbeitet (Analyse des eingeloggten Bereichs)

Stand: 9. November 2026. Quelle: Netzwerkverkehr und öffentliche Frontend-Bundles der Seite im eingeloggten Zustand, die öffentliche Swagger-Dokumentation (`rest-api-pr.betburger.com/doc.html`) und die ID-Tabellen unter `/api/entity_ids`. Keine Zugangsdaten wurden verwendet oder gespeichert; API-Aufrufe mit Arians Token habe ich **nicht** selbst abgesetzt, nur mitgelesen, was die Seite ohnehin lädt.

## 1. Architektur in einem Satz

Betburger ist eine klassische **Scanner-Pipeline**: eigene Collector lesen rund 150 Buchmacher (plus 600 "Clones", also Marken mit identischem Quotenfeed), schreiben jede Quotenänderung als Event in **Kafka**, ein Matching-Dienst ordnet Buchmacher-Events einem Referenz-Event zu, ein Rechenkern bildet daraus Surebets, Valuebets und Middles, und ein Such-Index (REST-API) beantwortet Filteranfragen der Web-App in ~40–70 ms.

Belege:
- Jede Quote trägt die Felder `kafka_message_offset`, `scanned_at`, `koef_last_modified_at`, `recorded_at` → Kafka-basierter Stream, Zeitstempel pro Scan und pro Quotenänderung.
- Antwortzeit steht in der Antwort selbst (`total_time: 44–63` ms) → vorberechneter Index, keine Live-Berechnung pro Anfrage.
- Trennung in Hosts `rest-api-pr` (Prematch) und `rest-api-lv` (Live) → zwei getrennte Cluster.
- Frontend: Vue 3 + Vuex + Vite, Backend-API: Java/Spring (OpenAPI 3.1 via springdoc, Controller-Namen `arb-controller`, `valuebet-controller`, `valuebet-v-2-controller`).

## 2. Datenfluss zum Browser (so "live" ist Betburger wirklich)

- **Kein WebSocket, kein Server-Push.** Die Seite pollt per HTTP-POST `…/api/v1/arbs/pro_search` bzw. `…/api/v1/valuebets/pro_search`.
- Intervall fest im Bundle: **Prematch 5 000 ms, Live 3 000 ms** (`{live:3e3, prematch:5e3}`), Request-Limit `{live:20, prematch:600}` Treffer.
- Der Token wird regelmäßig über `api/v1/refresh_token` erneuert.
- Jeder Poll sendet den kompletten Zustand der Oberfläche als Formular: `auto_update`, `grouped`, `per_page`, `sort_by` (`percent` / `valuebet_percent`), `koef_format`, `event_arb_types[]` (1–10), `search_filter[]` (Filter-ID), `is_live`, `bk_ids[]` (alle gewählten Buchmacher einzeln), `excluded_*` (ausgeblendete Events/Quoten).
- Die Antwort ist ein JSON mit `arbs[]` (Surebets bzw. Valuebets), `bets[]` (die beteiligten Einzelquoten), `excluded`, `last_update`, `max_percent`, `total`/`total_by_filter`.

**Konsequenz für Becher:** Ein 5-Sekunden-Poll auf einen vorberechneten Index reicht für Prematch völlig. Echter Push (WebSocket) wäre ein Vorteil gegenüber Betburger, ist aber für den privaten Kern unnötig.

## 3. Datenmodell (Felder, die Betburger pro Quote speichert)

Aus `BetDto` (Swagger) und den Live-Antworten:

| Feld | Bedeutung | Für Becher |
| --- | --- | --- |
| `bookmaker_id`, `bookmaker_event_id`, `bookmaker_league_id`, `home_id`, `away_id` | IDs im System des Buchmachers | wir: `event_source_ids`, Aliase |
| `event_id`, `team_home_id`, `team_away_id`, `league_id` | Referenz-IDs nach Matching | wir: `events`, `teams`, `leagues` |
| `swap_teams` | Buchmacher listet Heim/Gast vertauscht | fehlt bei uns → aufnehmen |
| `market_and_bet_type` (+ `_param`) | Markt-Variante, z. B. 19 = Total Over(x), 20 = Total Under(x), 17/18 = Asian Handicap 1/2, 11/12/13 = 1/X/2, 1/2 = Team1/Team2 Win | wir: `markets.type` + `outcome` (gröber) |
| `period_identifier` | Periode (0 = Spiel inkl. Verlängerung, 1/2 = Halbzeiten, 10 = …, −1 = Spiel ohne OT) je Sportart eigene Liste | fehlt bei uns → `markets.period` nutzen |
| `koef`, `koef_lay`, `is_lay`, `commission` | Quote, Lay-Quote (Börse), Kommission | vorhanden (`price`), Lay fehlt |
| `market_depth` | verfügbare Liquidität an der Börse | fehlt → aufnehmen für Betfair |
| `scanned_at`, `koef_last_modified_at`, `updated_at` | Scan-Zeit vs. letzte echte Änderung | wir haben nur `observed_at` → `source_ts` konsequent füllen |
| `is_original`, `version`, `diff` | Original vs. abgeleitete Quote, Änderungszähler | optional |
| `player`, `corner`, `current_score`, `is_live` | Spieler-/Ecken-Märkte, Live-Stand | Phase 4+ |

Surebet-Objekt (`ArbsDto`): `arb_formula_id` (Formeltyp, siehe Abschnitt 5), `percent`, `bet1_id/bet2_id/bet3_id`, `arb_type` = `"<sport_id>:<outcome-typ>"` (z. B. `7:3` = Fußball/Totals), `min_koef`, `max_koef`, `initiator` (Buchmacher, dessen Quotenänderung die Surebet ausgelöst hat), `bk_ids` (Bitmaske der beteiligten Buchmacher), `created_at`/`updated_at`/`started_at`, `middle_value`, `survival_probability` (Feld vorhanden, aktuell leer), `roi`, `f` (Bitmaske Event/Sport/Outcome).

Surebet-Typen (`event_arb_types`): 1 = 1X2, 2 = Handicaps, 3 = Totals, 4 = Individual Totals, 5 = Statistics, 6 = Additionals, 7 = Game Winner, 8 = Corners, 9 = Cards, 10 = Players.

Sport-IDs (Auszug): 1 Baseball, 2 Basketball, 6 Hockey, 7 Fußball, 8 Tennis, 9 Volleyball, 10 Am. Football, 24 Cricket, 47 Counter-Strike. Vollständige Listen (Buchmacher-IDs, Sport-/Perioden-IDs, 200+ Markt-Varianten) stehen öffentlich unter `https://www.betburger.com/de/api/entity_ids`.

## 4. Wie Valuebets bei Betburger gerechnet werden (wichtigster Fund)

Betburger behandelt eine Valuebet intern **wie eine Zwei-Wege-Surebet gegen eine Referenzquote**. In der Antwort auf `valuebets/pro_search` besteht jede Valuebet aus zwei "bets":

1. die Zielquote beim Soft-Buchmacher (z. B. AdmiralAT, Over 228.5 @ 2.35),
2. die **Gegenseite** bei der Referenz (z. B. Avgline, Under 228.5 @ 1.799).

Der angezeigte Prozentwert ist exakt die Surebet-Marge: `1/2.35 + 1/1.799 = 0.981` → **1.90 %**. Ich habe das an sechs Beispielen nachgerechnet, es stimmt immer.

Referenz-IDs im Bundle: `pinnacle: 1`, `avgline: 200`, `betfair: 11`. Außerdem konstante Schwellen `twoOutcomes: 230, treeOutcomes: 235, valueBet: 165` (vermutlich maximale Auszahlungs-/Marktgrößen für die Typen).

Zwei Versionen:
- **V1 ("Erweitert")**: Referenz ist die *rohe* Gegenquote von Pinnacle/Betfair oder der **Avgline** (Durchschnitt mehrerer Buchmacher, Feld `avg_koef`). Die Marge der Referenz steckt also noch in der Quote → Valuebet-Prozent ist **systematisch zu niedrig**, dafür konservativ. Zusätzlich liefert V1 `arbs_count` (wie viele Zwei-Wege-Surebets es mit dieser Quote gibt → Signal, wie "falsch" die Quote ist).
- **V2 ("Standard")**: hat das Feld `reference_bk_margin_stripped_koef` = Referenzquote **ohne Marge**. V2 devigt also die Referenz, und zwar vermutlich mit der einfachen multiplikativen Methode (proportional). Außerdem `reference_market_depth` (Liquidität der Referenz) und `reference_bookmaker_id`.

Was Betburger **nicht** tut (unsere Chancen, siehe Dokument 05):
- keine Wahl der Devig-Methode (Power/Shin/Logit), nur eine Zahl;
- keine Unsicherheit der fairen Quote (Konfidenzband) und keine Mischung mehrerer Referenzen mit Gewichten;
- kein Alter der Referenzquote in der Bewertung (nur Anzeige "40 Sek.");
- keine Wettsteuer (5,3 % DE) im Prozentwert, nur pro Buchmacher einstellbare Kommission;
- keine CLV-Rückmeldung (Backtesting zeigt nur "Rendite erwartet/tatsächlich" aggregiert).

## 5. Surebet-Formeln und Rechner

Die Datei `arbsFormulas-*.js` enthält **21 Formeltypen** (`formula_1` … `formula_21`) mit je einer Funktion für "alle Ausgänge" und je einer pro Teil-Ausgang. Sie unterscheiden sich nur darin, **was bei jedem Spielausgang passiert**:

- Typ 1: zwei Ausgänge, Gewinner bekommt alles (Tennis, Over/Under, DNB).
- Typ 2: drei Ausgänge 1/X/2.
- Typ 3–15: Kombinationen mit **Asian Handicap / Viertellinien**, bei denen ein Ausgang den Einsatz **zurückgibt** (`+ o`), **halb zurückgibt** (`+ o/2`) oder **halb gewinnt** (`(l+1)*o/2`).
- Typ 16–20: **Middles** (zwei Wetten gewinnen gleichzeitig; `percent` = 0 für die Teilausgänge, Gewinn nur im Mittelfeld).
- Typ 21: Mischform Handicap/Total.

Das ist mathematisch alles dieselbe Idee: Einsätze so verteilen, dass der Gewinn in jedem Szenario gleich ist. Statt 21 handgeschriebener Formeln setzt Becher einen **generischen Auszahlungsmatrix-Löser** ein (`engine/surebet.py`): jede Wette liefert pro Szenario einen Auszahlungsfaktor (1 = Rückgabe, 0 = verloren, Quote = gewonnen, Quote/2 + 1/2 = halb gewonnen), daraus folgen die Einsätze und die Marge für *jede* Kombination, auch für Dreier- und Viererlinien, die Betburger nicht abdeckt.

Weitere Mechaniken aus dem Bundle:
- **Börsenkommission** wird in die Quote eingerechnet: `koef_kommissed = q·(1−k)` ("auf Wette") oder `q + (1−q)·k` ("auf Gewinn"); Modus "auto" nutzt feste Profile für vier Börsen (IDs 483 = 5 %, 728 = 7 %, 762 = 2 % mit Sonderformel, 780 = 3 % / gleitend). Unser Schema hat `commission` und `tax_mode` bereits.
- Lay-Quote: `1 + 1/(q−1)`.
- Quotenformate: decimal, american, hongkong, fractional, indonesian (Konvertierung in beide Richtungen).
- Einsatzrundung (`roundTo`), Standardeinsatz 100, Währungen über `api/v1/currencies`.
- Filter-Optionen als IDs: `hideDecimals: 2`, `hideQuarters: 5` (Viertellinien ausblenden), `onlyDiffBook: 3`, `twoOutcomes: 7`, `threeOutcomes: 8`, `hideLayBets: 11`.

## 6. Matching (Event-Zuordnung)

Direkt sichtbar ist nur das Ergebnis: pro Quote gibt es `bookmaker_event_name` (Rohname beim Buchmacher) und `canonical_event_name`/`team1_name` (Referenzname), dazu `swap_teams`. Betburger pflegt also eine **Referenz-Entität pro Team und Liga** mit Buchmacher-Aliasen – genau das, was in Phase 2 mit `teams`, `team_aliases` und `event_source_ids` gebaut wird. Spieler-Märkte haben eigene Felder (`player1_id`, `player1BookmakerName`).

## 7. Öffentliche REST-API (für Abonnenten)

- Endpunkte: `POST /api/v1/arbs/bot_pro_search`, `POST /api/v1/valuebets/bot_pro_search`, `POST /api/v2/valuebets/bot_pro_search`; Live auf `rest-api-lv`, Prematch auf `rest-api-pr`.
- Parameter: `access_token`, `search_filter[]` (Filter-ID aus dem Konto), `per_page`, `grouped`, `bookmakers2[]`, `event_id`, `event_arb_types[]`, `excluded_events[]`, `excluded_bk_events[]`, `excluded_bets[]`.
- Ohne API-Abo sind Surebets auf 1 % und Valuebets auf 2 % begrenzt; der Zugang wird pro Anfrage (bis 10 Buchmacher, Live/Prematch) individuell bepreist und innerhalb von 48 h freigeschaltet. Felder `direct_link`/`raw_id` liefern erst im API-Plan echte Werte (`available_in_api_plan`).
- Die API liefert **nur Treffer** (Surebets/Valuebets), **keine Rohquoten** – deshalb taugt sie nicht als Datenquelle für einen eigenen Rechenkern.

## 8. Was Becher daraus übernimmt

1. Schema erweitern: `swap_teams`, `period` als Pflichtfeld, `market_depth`, `is_lay`/`lay_price`, `source_ts` konsequent füllen (Scan-Zeit ≠ Änderungszeit).
2. Markt-Varianten feiner kodieren (Betburger-Liste als Vorlage in `data/markt-varianten.csv`), nicht nur h2h/totals/spreads.
3. Valuebet-Kern: Referenz devigen (mehrere Methoden), Referenz-Alter und Liquidität in die Bewertung einbeziehen, Steuer einrechnen → siehe Dokument 05.
4. Surebet/Middle-Kern: generischer Auszahlungsmatrix-Löser statt Formel-Zoo.
5. Betrieb: vorberechneter Treffer-Index, Oberfläche pollt alle 5 s – oder einfacher: Telegram-Push bei neuen Treffern (für den privaten Kern ausreichend).
