# Collector

Ein Collector pro Buchmacher bzw. Odds-API. Geplante Sprache: Go.


## Collector (Stand Phase 4)

| Name | Datei | Quelle | Liefert |
| --- | --- | --- | --- |
| `odds_api` | `odds_api.py` | The Odds API v4 | h2h, totals, spreads vieler Buchmacher je Liga |
| `betfair` | `betfair.py` | Betfair Exchange API-NG | Back-/Lay-Quoten, gematchtes Volumen (Liquidität) für MATCH_ODDS, OVER_UNDER_x5, ASIAN_HANDICAP |
| (Vorlage) | `browser_base.py` | Buchmacher-Website per Playwright | je Buchmacher `league_urls` + `parse_page` implementieren |

Aktive Collector stehen in `.env` unter `COLLECTORS=odds_api,betfair`. Start: `python -m collectors.run --once` (einmal), `python -m collectors.run --scan` (Schleife mit Scan nach jedem Durchlauf), `--only betfair` für einen einzelnen.

Betfair-Zugang: App-Key im Developer-Programm anlegen (https://developer.betfair.com, "Delayed"-Key kostenlos). Session-Token entweder aus dem Browser-Cookie `ssoid` nach dem Login oder per Benutzername/Passwort in `.env` (interaktiver Login, Token wird bei Ablauf erneuert).
