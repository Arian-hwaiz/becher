# Becher

Odds-Scanner für Valuebets und Surebets: ein besserer Nachbau von Betburger, mit Fokus auf Valuebets, CLV-Nachweis und Schutz der Wettkonten.

## Ordnerstruktur

| Ordner | Inhalt |
| --- | --- |
| `docs/konzept/` | Analyse, Produktkonzept, Kostenplan, Datenerhebung |
| `docs/diagramme/` | Architektur- und Roadmap-Grafiken |
| `docs/recherche/` | Notizen zu Wettbewerbern, Buchmachern, Odds-API-Anbietern |
| `data/` | Projektdaten: Buchmacherlisten, Team-Aliase, Markt-Mappings, Beispielquoten |
| `ai/` | KI-Daten: Prompts, Modelle, Trainings- und Auswertungsdaten (z. B. Devig, Matching) |
| `common/` | Konfiguration, Datenmodell, Datenbankzugriff |
| `collectors/` | Quoten-Collector pro Buchmacher bzw. Odds-API |
| `scripts/` | Hilfsskripte: Schema einspielen, Status |
| `tests/` | Tests (pytest) |
| `engine/` | Rechenkern: `surebet.py` (generischer Surebet/Middle-Löser, Steuer, Kommission), später Devig und Valuebets |
| `dashboard/` | Streamlit-Dashboard: Scanner-Feed wie bei Betburger, Überblick, Quoten je Event, Collector-Läufe |
| `website/` | später: öffentliche Web-App (nicht Teil des privaten Kerns) |
| `infra/` | Server, Docker, Monitoring |

## Schnellstart (Phase 1)

Voraussetzungen: Python 3.11+, Docker Desktop, ein kostenloser Key von https://the-odds-api.com.

```bash
# 1. Abhängigkeiten
python -m venv .venv
.venv\Scripts\activate          # Windows; Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"

# 2. Konfiguration
copy .env.example .env           # dann ODDS_API_KEY eintragen

# 3. Datenbank (TimescaleDB in Docker) starten; Schema wird automatisch eingespielt
docker compose -f infra/docker-compose.yml up -d

# 4. Ein Durchlauf, dann Status
python -m collectors.run --once
python scripts/status.py

# 5. Dauerbetrieb: alle 5 Minuten (COLLECT_INTERVAL_SECONDS)
python -m collectors.run

# Tests (ohne Datenbank)
pytest -q

# Dashboard (Scanner wie bei Betburger): http://localhost:8501
pip install -e ".[dashboard]"
streamlit run dashboard/app.py
```

Läuft die Datenbank schon und ist das Schema älter, spielt `python scripts/init_db.py` es erneut ein (idempotent).

**Was Phase 1 kann:** holt Quoten für die Ligen aus `ODDS_API_SPORTS` (1X2, Über/Unter, Handicap) von allen Buchmachern, die die Odds-API liefert, und speichert sie als Zeitreihe in `odds_snapshots`. Buchmacher, die in `bookmaker_source_keys` nicht zugeordnet sind, werden geloggt und übersprungen. Jeder Lauf steht in `collector_runs`.

**Was Phase 2 kann (Team-Matching):** Rohnamen der Buchmacher werden normalisiert (Akzente, Füllwörter wie FC/SC, Abkürzungen), über Aliase je Quelle oder Fuzzy-Matching (rapidfuzz) einem kanonischen Team zugeordnet und als `team_aliases` mit Konfidenz gespeichert. Ein Event einer zweiten Quelle (andere Schreibweise, Heim/Gast vertauscht, Anstoß ±2 h) landet auf demselben `events`-Eintrag. Prüfen und nachziehen: `python scripts/match_teams.py` (`--review` zeigt unsichere Aliase). Logik: `engine/matching.py`, Anbindung: `common/db.py`.

**Phase 4 (begonnen):** `collectors/betfair.py` liest die Betfair Exchange (Back-/Lay-Quoten, gematchtes Volumen) über die offizielle API-NG; damit hat der Scan eine zweite Referenz mit Liquiditätsfilter. `collectors/browser_base.py` ist die Vorlage für Buchmacher ohne API (Playwright). Aktive Collector über `COLLECTORS=odds_api,betfair` in `.env`; `python -m collectors.run --scan` sammelt und scannt in einem Takt.

**Phase 5 (Tracking + CLV):** Dashboard-Seite „Wetten“ zum Erfassen und Abrechnen eigener Wetten; `engine/clv.py` sichert nach Anpfiff die Schlussquoten (`closing_odds`) und berechnet je Wette den CLV gegen die faire Schlussquote der scharfen Referenz; `python scripts/closing.py --report` macht das von Hand und druckt die Auswertung je Buchmacher, `python -m collectors.run --scan` automatisch. `engine/notify.py` schickt neue Treffer ab `NOTIFY_MIN_PERCENT` per Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`).

**Phase 6 (KI-Schicht):** `engine/ai.py` baut aus Treffern, eigenen Wetten, CLV je Buchmacher/Markt und Collector-Zustand einen Kontext und lässt Claude (`AI_MODEL`, Standard claude-opus-5-5) die Treffer priorisieren (strukturierte Antwort mit Prioritäten, Gründen, Risiken) oder einen Wochenbericht schreiben. Dashboard-Seite „KI“ oder `python scripts/ai_report.py --assess | --weekly | --context`. Antworten landen in `ai_reports`. Braucht `ANTHROPIC_API_KEY` und `pip install -e ".[ai]"`.

**Konto-Risiko und Methodenwahl:** `engine/account_health.py` schätzt je Buchmacher die Limitgefahr aus dem eigenen Wettverhalten (Score 0–100 mit Gründen und Tipps), `engine/method_eval.py` bewertet die Devig-Methoden je Markttyp an abgerechneten Wetten (Brier/Log-Loss) und empfiehlt ab 30 Wetten die beste. Beides auf der Seite „Wetten“, in `scripts/closing.py --report` und im KI-Kontext.

**Rechenkern (Phase 3):**
- `engine/surebet.py`: Surebets und Middles generisch über eine Auszahlungsmatrix (Viertellinien, Wettsteuer, Börsenkommission). Hintergrund: Dokument 06.
- `engine/devig.py`: Marge herausrechnen mit fünf Methoden (multiplikativ, additiv, Power, Shin, Logit) und gewichteter Konsens mehrerer Referenzen mit Alters- und Liquiditätsfilter.
- `engine/valuebet.py`: EV nach Steuer/Kommission, konservativer EV mit Unsicherheitsband (wächst mit Referenz-Alter und dünnem Markt), Viertel-Kelly.
- `engine/scan.py` + `python scripts/scan.py`: sucht in den jüngsten Quoten aller kommenden Events Valuebets (gegen scharfe Referenzen/Börse) und Surebets (beste effektive Quote je Ausgang) und schreibt Treffer in `opportunities`. Optionen: `--method`, `--min-ev`, `--max-age`, `--dry-run`.

**Dashboard:** `streamlit run dashboard/app.py` öffnet die Scanner-Ansicht: links Filter (Art, Zeitraum, Mindest-Prozent, Alter, Sportarten, Buchmacher, Sortierung, Gesamteinsatz, Auto-Refresh), in der Mitte der Treffer-Feed (Prozent, Sport, Alter, Spiel, Markt, Buchmacher, Quote, faire Quote, Referenz), rechts der Einsatzrechner (Surebet-Einsätze nach Steuer/Kommission, Gewinn; bei Valuebets effektive Quote, erwarteter Gewinn, Viertel-Kelly). Weitere Seiten: Überblick, Quoten je Event (Tabelle mit Bestquoten und Verlauf), Wetten (eigene Wetten, CLV), KI (Einordnung, Wochenbericht), Collector-Läufe.

**Datenbank-Tabellen:** `bookmakers` (mit Steuer und Kommission je Anbieter), `sports`, `leagues`, `teams`, `team_aliases`, `events`, `markets`, `odds_snapshots`, `closing_odds`, `opportunities`, `bets`, `collector_runs`. Schema: `infra/schema.sql`.

## Wichtigste Dokumente

- **[Handbuch: das komplette Projekt erklärt](docs/HANDBUCH.md)**

- [Betburger-Analyse und Konzept](docs/konzept/01-betburger-analyse-und-konzept.md)
- [Kostenkonzept](docs/konzept/02-kostenkonzept.md)
- [Datenerhebung und Server](docs/konzept/03-scraping-und-server.md)
- [Entwicklungsplan privater Kern (Datensammlung + KI)](docs/konzept/04-entwicklungsplan-kern.md)
- [Verbesserungen bei Berechnungen und Profit](docs/konzept/05-berechnungen-und-profit.md)
- [Wie Betburger technisch arbeitet: API, Polling, Formeln, Valuebet-Mechanik](docs/konzept/06-betburger-technik-und-mechanik.md)

Visueller Gesamtplan: [docs/visueller-plan.html](docs/visueller-plan.html) (online: https://claude.ai/artifact/3ym8wQp3gTbdVatLbvJ5Ke)

Live-Version des Konzepts mit Kommentaren: https://claude.ai/artifact/MZwnuCqTiJhgCo9btfQJmq
