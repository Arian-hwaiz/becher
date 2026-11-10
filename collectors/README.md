# Collector

Ein Collector pro Buchmacher bzw. Odds-API. Geplante Sprache: Go.


## Collector (Stand Phase 4)

| Name | Datei | Quelle | Liefert |
| --- | --- | --- | --- |
| `odds_api` | `odds_api.py` | The Odds API v4 | h2h, totals, spreads vieler Buchmacher je Liga |
| `betfair` | `betfair.py` | Betfair Exchange API-NG | Back-/Lay-Quoten, gematchtes Volumen (Liquidität) für MATCH_ODDS, OVER_UNDER_x5, ASIAN_HANDICAP |
| `bwin` | `bwin.py` | bwin-Ligaseite per Playwright (JSON `widgetdata`, ohne Login) | h2h, totals (alle Linien), Direkt-Link zum Spiel |
| `admiral` | `admiral.py` | admiral.at-Ligaseite per Playwright (WebSocket-Daten, ohne Login) | h2h, totals (alle Linien), Direkt-Link zum Spiel |
| (Vorlage) | `browser_base.py` | Buchmacher-Website per Playwright | je Buchmacher `league_urls` + `parse_page` implementieren |

Aktive Collector stehen in `.env` unter `COLLECTORS=odds_api,betfair`. Start: `python -m collectors.run --once` (einmal), `python -m collectors.run --scan` (Schleife mit Scan nach jedem Durchlauf), `--only betfair` für einen einzelnen.

Betfair-Zugang: App-Key im Developer-Programm anlegen (https://developer.betfair.com, "Delayed"-Key kostenlos). Session-Token entweder aus dem Browser-Cookie `ssoid` nach dem Login oder per Benutzername/Passwort in `.env` (interaktiver Login, Token wird bei Ablauf erneuert).

## Eigene Scraper (bwin, ADMIRAL, …)

Gemeinsamer Unterbau: `page_capture.py`. Die Ligaseite wird in Playwright geöffnet, mitgelesen wird nur,
was die Seite selbst lädt (JSON-Antworten, WebSocket-Frames, Links). Regeln: kein Login, kein Umgehen
von Bot-Schutz (403/Cloudflare/Captcha → Abbruch mit Meldung), Pause `SCRAPE_DELAY_SECONDS` zwischen
Seiten, Mindestabstand `SCRAPE_INTERVAL_SECONDS` zwischen Läufen, Ligen über `SCRAPE_LEAGUES`.
Kostet keine Odds-API-Credits. Einmalig: `pip install -e ".[browser]"` und `python -m playwright install chromium`.

Stand der Erkundung (November 2026): Pinnacle blockiert (Cloudflare 403), Tipico blockiert (Verbindung
wird abgebrochen), bwin läuft, ADMIRAL (admiral.at) läuft. Start einzeln:
`python -m collectors.run --once --only bwin --scan` bzw. `--only admiral`; dauerhaft über `COLLECTORS=odds_api,bwin,admiral`.
