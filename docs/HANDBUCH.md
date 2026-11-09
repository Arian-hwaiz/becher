# Becher – Handbuch

Stand: 10. November 2026 (Phase 4 begonnen) · Repo: https://github.com/Arian-hwaiz/becher

Dieses Handbuch erklärt das Projekt Becher vollständig: was es ist, wie es funktioniert, wie man es installiert und bedient, wie die Teile zusammenhängen und was noch kommt. Es richtet sich an Arian als Betreiber und an jeden, der später am Code arbeitet.

---

## Inhalt

1. [Was ist Becher?](#1-was-ist-becher)
2. [Die Grundbegriffe](#2-die-grundbegriffe)
3. [Wie Becher arbeitet (Architektur)](#3-wie-becher-arbeitet-architektur)
4. [Installation Schritt für Schritt](#4-installation-schritt-für-schritt)
5. [Tägliche Bedienung](#5-tägliche-bedienung)
6. [Das Dashboard](#6-das-dashboard)
7. [Die Ordner und Module im Detail](#7-die-ordner-und-module-im-detail)
8. [Die Datenbank](#8-die-datenbank)
9. [Die Rechenlogik](#9-die-rechenlogik)
10. [Konfiguration](#10-konfiguration)
11. [Entwicklungsstand und Fahrplan](#11-entwicklungsstand-und-fahrplan)
12. [Becher im Vergleich zu Betburger](#12-becher-im-vergleich-zu-betburger)
13. [Arbeitsregeln für die Entwicklung](#13-arbeitsregeln-für-die-entwicklung)
14. [Fehlersuche](#14-fehlersuche)
15. [Glossar](#15-glossar)

---

## 1. Was ist Becher?

Becher ist ein **privater Quoten-Scanner**. Er sammelt laufend Wettquoten vieler Buchmacher, ordnet sie demselben Spiel zu, berechnet daraus faire Wahrscheinlichkeiten und zeigt, wo ein Buchmacher eine Quote anbietet, die zu hoch ist (**Valuebet**) oder wo sich Quoten mehrerer Buchmacher so kombinieren lassen, dass in jedem Ausgang ein Gewinn bleibt (**Surebet**). Vorbild ist der kommerzielle Dienst Betburger. Becher soll dasselbe können, aber ehrlicher rechnen (Steuer, Alter der Referenz, Unsicherheit), die eigenen Wetten mit der Schlussquote vergleichen (CLV) und später eine KI-Schicht bekommen, die die Daten auswertet.

**Scope-Entscheidung (9. 11. 2026):** Becher ist kein öffentliches Produkt und keine Firma. Es ist der private Kern: Datensammlung, Rechenkern, Dashboard, später KI. Alles liegt in einem Repo. Es gibt keine Anbindung an die Betburger-API; Betburger dient nur als Vorlage für Funktionen und Mechanik.

**Was Becher heute kann (Stand 10. 11. 2026):**

- Quoten von The Odds API für beliebig viele Ligen holen und als Zeitreihe speichern (Phase 1).
- Teamnamen verschiedener Quellen demselben Team und Spiel zuordnen (Phase 2).
- Faire Quoten mit fünf Devig-Methoden berechnen, Valuebets mit EV nach deutscher Wettsteuer und konservativem EV bewerten, Surebets und Middles mit Einsatzverteilung lösen, Treffer in die Datenbank schreiben (Phase 3).
- Ein Dashboard im Browser zeigen: Scanner-Feed wie bei Betburger, Überblick, Quoten je Spiel, Collector-Läufe.
- Demo-Daten erzeugen, um alles ohne API-Key auszuprobieren.

- Eigene Wetten erfassen und abrechnen, Schlussquoten automatisch sichern, CLV je Wette und je Buchmacher auswerten, Telegram-Nachricht bei neuen Treffern (Phase 5).

- Treffer von Claude einordnen und priorisieren lassen, Wochenbericht erzeugen (Phase 6).

**Was noch fehlt:** Collector direkt bei einzelnen Buchmachern (Phase 4, Rest), Feinheiten der KI-Schicht (Devig-Methode am CLV wählen, Limit-Risiko).

---

## 2. Die Grundbegriffe

**Dezimalquote.** Eine Quote von 2,50 zahlt bei Gewinn das 2,5-Fache des Einsatzes aus (Einsatz enthalten). Die **implizite Wahrscheinlichkeit** ist 1/Quote, also 40 %.

**Marge (Overround).** Addiert man die impliziten Wahrscheinlichkeiten aller Ausgänge eines Marktes, kommt bei einem Buchmacher mehr als 100 % heraus, z. B. 105 %. Die 5 % sind sein eingebauter Vorteil. Pinnacle liegt bei ca. 2 %, deutsche Buchmacher bei 5 bis 8 %, die Börse Betfair bei 0 % (dafür Kommission auf den Gewinn).

**Devig.** Die Marge aus den Quoten herausrechnen, damit die Wahrscheinlichkeiten sich zu genau 100 % addieren. Ergebnis: **faire Wahrscheinlichkeit** und **faire Quote** (1/p). Es gibt mehrere Methoden, weil Buchmacher die Marge nicht gleichmäßig verteilen (Außenseiter tragen mehr Marge). Becher kann multiplikativ, additiv, Power, Shin und Logit.

**Referenz.** Die Quelle, deren Quoten als "wahr" gelten: Pinnacle (scharfer Buchmacher mit kleiner Marge, der Gewinner nicht limitiert) und Betfair Exchange (Markt aus echten Angeboten). Becher bildet aus mehreren Referenzen einen gewichteten Konsens und wirft zu alte oder zu illiquide Referenzen heraus.

**Valuebet.** Eine Quote beim "weichen" Buchmacher (Tipico, bwin …), die über der fairen Quote liegt. Der **Erwartungswert (EV)** ist p · Quote − 1. Bei p = 0,40 und Quote 2,70 ist EV = 0,40 · 2,70 − 1 = +8 %. Wichtig: in Deutschland gilt 5,3 % Wettsteuer auf den Einsatz; eine Quote 2,70 ist effektiv nur 2,70 · 0,947 = 2,557. Becher rechnet immer mit der effektiven Quote.

**Konservativer EV.** Die faire Wahrscheinlichkeit ist eine Schätzung. Becher setzt ein Unsicherheitsband an (größer bei dünnen Märkten und alten Referenzquoten) und rechnet den EV am unteren Rand aus. Gewettet wird nur, wenn der konservative EV positiv ist.

**Surebet (Arbitrage).** Quoten verschiedener Buchmacher auf alle Ausgänge eines Marktes, deren implizite Wahrscheinlichkeiten zusammen unter 100 % liegen. Beispiel: Heim 2,10 bei A, Gast 2,10 bei B → 1/2,10 + 1/2,10 = 95,2 % → 5 % sicherer Gewinn, wenn die Einsätze proportional zu 1/Quote verteilt werden. Nach Steuer bleibt davon in Deutschland meist nichts; deshalb ist Becher valuebet-first.

**Middle.** Zwei Wetten mit verschiedenen Linien (z. B. Über 2,5 und Unter 3,5), bei denen ein Ergebnis im "Mittelfeld" (genau 3 Tore) beide gewinnen lässt. Im schlechtesten Fall kleiner Verlust oder null, im besten Fall doppelter Gewinn.

**Asian Handicap / Viertellinien.** Linien wie −0,25 oder +0,75 teilen den Einsatz auf zwei benachbarte Linien; dadurch gibt es Ausgänge mit Rückgabe, halbem Gewinn oder halbem Verlust. Becher deckt das mit einer Auszahlungsmatrix ab (siehe Abschnitt 9).

**Kelly.** Formel für die Einsatzhöhe aus Vorteil und Quote. Voll-Kelly ist zu aggressiv; Becher zeigt **Viertel-Kelly** auf Basis des konservativen EV.

**CLV (Closing Line Value).** Vergleich der eigenen Wettquote mit der Schlussquote (devigged) kurz vor Anpfiff. Wer dauerhaft bessere Quoten als die Schlusslinie bekommt, hat eine echte Kante, unabhängig vom kurzfristigen Glück. Das ist Phase 5 und das Hauptkriterium für die KI.

---

## 3. Wie Becher arbeitet (Architektur)

| Schritt | Baustein | Ergebnis |
| --- | --- | --- |
| 1 Sammeln | `collectors/` (The Odds API; Phase 4: Betfair, Buchmacher direkt) | `NormalizedEvent` je Spiel mit Märkten und Quoten |
| 2 Speichern | `common/db.Store` mit Matching (Phase 2) | Tabellen `events`, `markets`, `odds_snapshots` in PostgreSQL/TimescaleDB |
| 3 Rechnen | `engine/scan` mit `devig`, `valuebet`, `surebet` | Tabelle `opportunities` (Valuebets, Surebets) |
| 4 Anzeigen | `dashboard/` (Streamlit) | Scanner, Überblick, Quoten je Event, Collector-Läufe |

1. **Collector** holen Rohdaten und geben sie als `NormalizedEvent` zurück (Quelle, Liga, Teams, Anstoß, Märkte mit Quoten je Buchmacher). Jede Quelle hat ihren eigenen Collector; der Rest des Systems kennt nur dieses eine Format.
2. **Store** (in `common/db.py`) schreibt die Events in die Datenbank. Dabei ordnet er Teamnamen kanonischen Teams zu (Aliase, Fuzzy-Matching) und erkennt, wenn eine zweite Quelle dasselbe Spiel liefert. Jede Quote wird als Zeile in `odds_snapshots` mit Zeitstempel gespeichert, nie überschrieben: so entsteht eine Zeitreihe, aus der später Schlussquoten und Quotenbewegungen kommen.
3. **Scan** (`engine/scan.py`) nimmt für jeden Markt die jüngste Quote je Buchmacher und Ausgang, bildet aus den Referenzen die faire Wahrscheinlichkeit, bewertet jede Soft-Quote (Valuebet) und sucht die beste effektive Quote je Ausgang (Surebet). Treffer landen in `opportunities`.
4. **Dashboard** liest Datenbank und `opportunities` und zeigt sie im Browser. Es rechnet nichts Wesentliches selbst, außer dem Einsatzrechner.

Alles läuft als einfache Python-Prozesse auf einem Rechner. Es gibt keinen Server, keine Nutzerverwaltung, keine Cloud. Der Betrieb besteht aus drei Prozessen: Datenbank (Docker), Collector (Schleife), Dashboard (Streamlit). Der Scan kann in den Collector-Takt eingehängt oder per Hand gestartet werden.

---

## 4. Installation Schritt für Schritt

Voraussetzungen auf dem PC:

- **Python 3.11 oder neuer** (https://www.python.org, bei der Installation "Add to PATH" ankreuzen)
- **Docker Desktop** (https://www.docker.com/products/docker-desktop) für die Datenbank
- **Git** bzw. GitHub Desktop (ist vorhanden)
- Ein kostenloser **API-Key von The Odds API** (https://the-odds-api.com, 500 Anfragen pro Monat gratis; für Dauerbetrieb das 20-Dollar-Paket)

Schritte in PowerShell im Ordner `C:\Users\arian\Documents\GitHub\becher`:

```powershell
# 1. Virtuelle Umgebung anlegen und aktivieren
python -m venv .venv
.venv\Scripts\activate

# 2. Projekt mit allen Extras installieren (Collector, Tests, Dashboard)
pip install -e ".[dev,dashboard,ai]"

# 3. Konfiguration anlegen und API-Key eintragen
copy .env.example .env
notepad .env          # ODDS_API_KEY=... eintragen, speichern

# 4. Datenbank starten (TimescaleDB in Docker, Schema wird automatisch eingespielt)
docker compose -f infra/docker-compose.yml up -d

# 5. Testen, ob alles zusammenpasst
pytest -q             # sollte "passed" melden

# 6. Erster Collector-Lauf und Status
python -m collectors.run --once
python scripts/status.py

# 7. Scan und Dashboard
python scripts/scan.py
streamlit run dashboard/app.py      # öffnet http://localhost:8501
```

Ohne API-Key kann man alles mit Demo-Daten ausprobieren:

```powershell
python scripts/demo_data.py         # legt 6 Beispielspiele mit Quoten an und scannt
streamlit run dashboard/app.py
python scripts/demo_data.py --clear # Demo-Daten wieder löschen
```

Wenn die Datenbank schon lief, bevor das Schema geändert wurde: `python scripts/init_db.py` spielt das Schema erneut ein (idempotent, löscht nichts).

---

## 5. Tägliche Bedienung

| Aufgabe | Befehl | Was passiert |
| --- | --- | --- |
| Datenbank starten/stoppen | `make db-up` / `make db-down` oder die docker-compose-Befehle | Container `becher-db` auf Port 5432 |
| Einmal Quoten holen | `python -m collectors.run --once` | Ein Durchlauf aller aktiven Collector (`COLLECTORS` in `.env`), `--only betfair` für einen |
| Dauerbetrieb | `python -m collectors.run --scan` | Alle `COLLECT_INTERVAL_SECONDS` (Standard 300 s) ein Durchlauf, danach automatisch der Scan |
| Treffer suchen | `python scripts/scan.py` | Scan aller kommenden Spiele, schreibt `opportunities`, druckt Liste |
| Treffer nur anzeigen | `python scripts/scan.py --dry-run --method shin --min-ev 0.01` | ohne Schreiben, andere Devig-Methode, Schwelle 1 % |
| Dashboard | `streamlit run dashboard/app.py` | Browser auf http://localhost:8501 |
| Status in der Konsole | `python scripts/status.py` | letzte Läufe, Abdeckung je Buchmacher, kommende Events |
| Team-Matching prüfen | `python scripts/match_teams.py --review` | zeigt unsichere Aliase (Konfidenz < 0,95) |
| Schlussquoten + CLV | `python scripts/closing.py --report` | sichert Schlussquoten begonnener Spiele, berechnet CLV der eigenen Wetten, druckt Auswertung je Buchmacher (läuft auch automatisch im Collector mit `--scan`) |
| KI-Auswertung | `python scripts/ai_report.py --assess` / `--weekly` / `--context` | Treffer einordnen, Wochenbericht, oder nur den Kontext ohne KI anzeigen; `--out datei.md` speichert |
| Tests | `pytest -q` | 56 Tests, Datenbanktests nur mit `BECHER_TEST_DATABASE_URL` |

**Empfohlener Rhythmus:** Collector dauerhaft laufen lassen (ein PowerShell-Fenster), Scan alle paar Minuten (zweites Fenster, z. B. `while ($true) { python scripts/scan.py; Start-Sleep 120 }`), Dashboard offen. Die Odds-API liefert Prematch-Quoten mit einigen Minuten Verzögerung; für Live-Wetten ist Becher noch nicht gedacht.

**Telegram-Alarm einrichten:** In Telegram `@BotFather` öffnen, `/newbot` senden, Namen vergeben, den Token in `.env` als `TELEGRAM_BOT_TOKEN` eintragen. Dem neuen Bot eine beliebige Nachricht schicken, dann im Browser `https://api.telegram.org/bot<TOKEN>/getUpdates` aufrufen und die Zahl hinter `"chat":{"id":` als `TELEGRAM_CHAT_ID` eintragen. Ab dann meldet `python -m collectors.run --scan` jeden neuen Treffer ab `NOTIFY_MIN_PERCENT` (Standard 1 %) mit Spiel, Markt, Buchmacher, Quote, fairer Quote und EV. Jeder Treffer wird je Programmlauf nur einmal gemeldet.

**Kontingent der Odds-API:** Jeder Aufruf pro Liga und Region kostet 1 Anfrage je Markt. Mit 3 Ligen, 1 Region, 3 Märkten und 5-Minuten-Takt sind das ca. 2 600 Anfragen pro Tag. Der Collector loggt das Restkontingent (`x-requests-remaining`).

---

## 6. Das Dashboard

Start: `streamlit run dashboard/app.py`. Sechs Seiten, Auswahl links oben.

### Scanner (Hauptseite, nach dem Vorbild der Betburger-Surebet-Seite)

![Scanner](bilder/dashboard-scanner.png)

- **Filterleiste links:** Art (Valuebets, Surebets), Zeitraum, Mindest-Prozent, maximales Alter des Treffers, Sortierung (Prozent, Alter, Anstoß), Gesamteinsatz für den Rechner, Auto-Refresh alle 15 s, Sportarten, Buchmacher.
- **Trefferkarte, linke Spalte:** Prozent (bei Valuebets der konservative EV, bei Surebets die Marge nach Steuer/Kommission), Art, Sportart, Alter des Treffers.
- **Mitte:** Spiel, Liga, Anstoß, Markt, dann je Wette Buchmacher, Ausgang (Schreibweise wie bei Betburger: `1/X/2`, `TO(2.5)`/`TU(2.5)`, `AH1(-1.5)`) und Quote. Bei Valuebets zusätzlich faire Quote, roher EV, konservativer EV, Referenz, Alter der Referenz, Devig-Methode.
- **Rechts, Einsatzrechner:** Bei Surebets die Einsätze je Wette für den gewählten Gesamteinsatz (Quoten nach Steuer und Kommission) und der sichere Gewinn. Bei Valuebets die effektive Quote, der erwartete Gewinn und der Viertel-Kelly-Anteil der Bankroll.

Der Feed zeigt je Markt, Buchmacher und Ausgang nur den jüngsten Treffer, damit ein Spiel nicht zehnmal untereinander steht.

### Überblick

Kennzahlen (kommende Events, Quoten der letzten Stunde, aktive Buchmacher, Valuebets und Surebets der letzten 24 h), letzter Collector-Lauf, Quoten pro Stunde als Balkendiagramm, Buchmacher-Abdeckung, Verteilung der Treffer-Prozente, Treffer je Buchmacher.

### Quoten je Event

![Quoten je Event](bilder/dashboard-quoten.png)

Ein Spiel auswählen, dann je Markt eine Tabelle Buchmacher × Ausgang mit der jeweils besten Quote grün markiert, darunter die Auszahlung der besten Quoten (über 100 % = Surebet vor Steuer) und ein Linienchart der Quotenbewegung der letzten 72 Stunden.

### Wetten

![Wetten](bilder/dashboard-wetten.png)

Hier werden die eigenen Wetten erfasst und am Ende gemessen. Oben Kennzahlen (Anzahl, Gewinn der abgerechneten Wetten, Ø CLV, Anteil positiver CLV). Im Formular Event und Markt aus der Datenbank wählen (dann kann Becher später die Schlussquote zuordnen), Buchmacher, Ausgang, Quote, Einsatz, optional die faire Quote zum Zeitpunkt des Setzens (steht in der Trefferkarte) und eine Notiz. Darunter die Tabelle aller Wetten mit Ergebnis, Gewinn und CLV, ein Abschnitt zum Abrechnen offener Wetten (gewonnen, verloren, void, halb gewonnen/verloren; die Auszahlung rechnet Becher), ein Balkendiagramm Ø CLV je Buchmacher und der kumulierte CLV-Verlauf.

**Wie der CLV entsteht:** Nach Anpfiff sichert `scripts/closing.py` (oder der Collector mit `--scan`) je Markt, Buchmacher und Ausgang die letzte Quote vor dem Anstoß als Schlussquote (`closing_odds`, höchstens 6 h alt). Aus den Schlussquoten der scharfen Referenzen (Pinnacle & Co.) wird mit der Power-Methode die faire Schlussquote gebildet; CLV = eigene Quote ÷ faire Schlussquote − 1. Positiver CLV über viele Wetten ist der eigentliche Beleg für eine Kante, unabhängig davon, ob die einzelne Wette gewonnen hat.

### KI

![KI](bilder/dashboard-ki.png)

Die KI-Schicht (Phase 6). Zwei Knöpfe: **Treffer einordnen** lässt Claude die aktuellen Treffer priorisieren (Priorität 1 bis 5, Begründung, konkrete Risiken, Warnungen zu Daten und Collectoren, Vorschläge für Schwellen). **Wochenbericht** schreibt einen Bericht in Markdown (Gesamtbild, eigene Wetten und CLV, auffällige Treffer, Datenqualität, Empfehlungen). Der Regler bestimmt das Zeitfenster. „Kontext ansehen“ zeigt genau die Zahlen, die an Claude gehen. Alle Auswertungen werden in `ai_reports` gespeichert und unten aufgeklappt angezeigt, mit Modell und Tokenverbrauch.

Die KI rechnet nichts neu. Sie bekommt die von Becher berechneten Zahlen (EV, konservativer EV, faire Quote, Referenzen, CLV je Buchmacher und Markt, Collector-Läufe) und ordnet sie ein. Ohne `ANTHROPIC_API_KEY` sind die Knöpfe gesperrt; jede Auswertung kostet API-Guthaben (Größenordnung bei 40 Treffern und 200 Wetten: 10 000 bis 20 000 Eingabe-Tokens, also wenige Cent).

### Collector-Läufe

Anzahl Läufe, Erfolgsquote, Quoten je Lauf als Punktwolke, Tabelle aller Läufe mit Dauer und Fehlermeldung.

Das Dashboard liest alle 15 s neu (Cache). "Jetzt neu laden" erzwingt es.

---

## 7. Die Ordner und Module im Detail

```
becher/
├── README.md                 Kurzüberblick und Schnellstart
├── Makefile                  Kurzbefehle: setup, db-up, init, collect, scan, dashboard, test
├── pyproject.toml            Paketdefinition und Abhängigkeiten (extras: dev, dashboard)
├── .env.example              Vorlage für die Konfiguration (.env ist nie im Repo)
├── common/                   Gemeinsames
│   ├── config.py             Settings aus .env (pydantic-settings)
│   ├── models.py             NormalizedEvent, NormalizedMarket, Quote
│   └── db.py                 Verbindung, Schema einspielen, Store (Speichern + Matching)
├── collectors/               Quellen
│   ├── base.py               abstrakte Klasse Collector.fetch()
│   ├── odds_api.py           The Odds API v4 (parse_events ist reine Funktion)
│   ├── betfair.py            Betfair Exchange API-NG: Katalog + MarketBook → Back/Lay/Liquidität
│   ├── browser_base.py       Vorlage für Buchmacher-Collector per Playwright
│   └── run.py                Einmal-Lauf oder Schleife mit APScheduler, loggt collector_runs
├── engine/                   Rechenkern
│   ├── matching.py           normalize_name, TeamMatcher, find_event
│   ├── devig.py              5 Devig-Methoden, Reference, consensus
│   ├── valuebet.py           EV, konservativer EV, Kelly, evaluate
│   ├── surebet.py            Auszahlungsmatrix-Löser, effective_price, Handicap/Totals-Szenarien
│   └── scan.py               scan_market (rein), run_scan (Datenbank) → opportunities
├── dashboard/                Streamlit
│   ├── app.py                Seiten und Darstellung
│   └── queries.py            SQL-Abfragen als pandas-DataFrames (ohne Streamlit testbar)
├── scripts/                  Werkzeuge für die Konsole
│   ├── init_db.py            Schema einspielen
│   ├── status.py             Kurzstatus
│   ├── scan.py               Scan starten
│   ├── match_teams.py        Matching nachziehen / unsichere Aliase anzeigen
│   └── demo_data.py          Demo-Daten anlegen oder löschen
├── infra/                    Betrieb
│   ├── docker-compose.yml    TimescaleDB (Postgres 16) mit Schema-Autoimport
│   └── schema.sql            alle Tabellen (idempotent)
├── tests/                    pytest; fixtures/odds_api_sample.json
├── docs/                     Dokumentation
│   ├── HANDBUCH.md           dieses Handbuch
│   ├── konzept/01…06         Analyse, Kosten, Scraping/Server, Entwicklungsplan, Berechnungen, Betburger-Technik
│   ├── diagramme/            Architektur- und Roadmap-Grafiken
│   ├── bilder/               Screenshots
│   └── visueller-plan.html   interaktiver Gesamtplan
├── data/                     Projektdaten (Aliase, Markt-Mappings), data/raw ist ignoriert
├── ai/                       KI-Schicht (Phase 6): Prompts, Auswertungen
└── website/                  später; nicht Teil des privaten Kerns
```

### Wichtige Funktionen

- `collectors.odds_api.parse_events(payload, league_key)` wandelt die API-Antwort um; Totals bekommen die Linie, Spreads werden aus Heimsicht normiert (Gast-Linie negiert).
- `common.db.Store.save_events(events)` speichert Events, Märkte, Quoten; unbekannte Buchmacher-Schlüssel werden geloggt und übersprungen. `resolve_team` und `find_matching_event` machen das Matching. `log_run` protokolliert den Lauf.
- `engine.matching.normalize_name("1. FC Köln")` → `"koln"`; `TeamMatcher.match(source, name)` liefert `Match(team_id, confidence, method)` mit `method` ∈ alias, exact, fuzzy, none. Mehrdeutige Treffer (zwei Kandidaten ähnlich gut) werden abgelehnt.
- `engine.devig.devig(prices, method)` → faire Wahrscheinlichkeiten; `consensus(refs, method, max_age_s, min_liquidity)` → gewichteter Mittelwert.
- `engine.valuebet.evaluate(i, soft_prices, references, tax_rate=…, …)` → `Evaluation` mit `ev`, `ev_conservative`, `kelly_fraction`, `is_bet`.
- `engine.surebet.simple([2.1, 2.1])` → Einsätze 50/50, Marge 5 %; `handicap(...)`, `total(...)` bauen Szenarien inkl. Viertellinien; `effective_price(q, commission, tax_rate, tax_mode)`.
- `engine.scan.scan_market(...)` ist ohne Datenbank testbar; `run_scan(conn, cfg)` macht den Durchlauf über alle kommenden Spiele.

---

## 8. Die Datenbank

PostgreSQL 16 mit TimescaleDB (optional; ohne Erweiterung bleibt `odds_snapshots` eine normale Tabelle). Zugang im Docker-Standard: Benutzer, Passwort und Datenbank jeweils `becher`, Port 5432.

| Tabelle | Inhalt |
| --- | --- |
| `bookmakers` | Buchmacher mit `kind` (sharp/soft/exchange), Wettsteuer (`tax_rate`, `tax_mode`), Börsenkommission. 10 vorangelegt. |
| `bookmaker_source_keys` | Schlüssel des Buchmachers in jeder Quelle (z. B. `odds_api`/`tipico_de` → Tipico) |
| `sports`, `leagues` | Sportarten und Ligen (Liga-Key aus der Quelle) |
| `teams`, `team_aliases` | kanonische Teams und alle Schreibweisen je Quelle mit Konfidenz |
| `events` | ein Spiel: Liga, Teams (IDs und Rohnamen), Anstoß, Status |
| `event_source_ids` | ID des Spiels in jeder Quelle, `swap_teams` wenn die Quelle Heim/Gast vertauscht |
| `markets` | Markt je Spiel: `type` (h2h/totals/spreads), `line`, `period` |
| `odds_snapshots` | Zeitreihe: `observed_at` (unser Abruf), `source_ts` (laut Quelle), Markt, Buchmacher, Ausgang, Quote, `is_lay`, `lay_price`, `liquidity` |
| `opportunities` | Treffer: `kind` (value/arb/middle), Quote, faire Quote, `ev`, `ev_conservative`, Methode, Referenz-Alter, `details` (JSON: Einsätze, Referenzen, Kelly) |
| `closing_odds` | Schlussquoten je Markt und Buchmacher (Phase 5) |
| `bets` | eigene Wetten mit Einsatz, Quote, fairer Quote beim Setzen, Ergebnis, CLV (Phase 5) |
| `ai_reports` | gespeicherte KI-Auswertungen mit Modell und Tokenverbrauch (Phase 6) |
| `collector_runs` | jeder Lauf mit Quelle, Dauer, Events, Quoten, Fehler |

Nützliche Abfragen (z. B. mit `psql` oder DBeaver):

```sql
-- beste Valuebets der letzten 6 Stunden
SELECT found_at, b.name, o.outcome, o.price, o.fair_price, o.ev_conservative
FROM opportunities o JOIN bookmakers b ON b.id = o.bookmaker_id
WHERE kind = 'value' AND found_at > now() - interval '6 hours'
ORDER BY ev_conservative DESC LIMIT 20;

-- Quotenverlauf eines Marktes
SELECT observed_at, b.name, outcome, price FROM odds_snapshots o JOIN bookmakers b ON b.id = o.bookmaker_id
WHERE market_id = 123 ORDER BY observed_at;
```

---

## 9. Die Rechenlogik

### Faire Quote (Devig)

Gegeben Quoten q₁…qₙ eines Marktes bei der Referenz, implizite Wahrscheinlichkeiten rᵢ = 1/qᵢ, Summe S > 1.

- **Multiplikativ:** pᵢ = rᵢ / S. Einfach, so rechnet Betburger V2.
- **Additiv:** pᵢ = rᵢ − (S − 1)/n.
- **Power:** pᵢ = rᵢᵏ mit k so, dass Σpᵢ = 1. Legt mehr Marge auf Außenseiter.
- **Shin:** Modell mit Anteil z informierter Wetter; ebenfalls außenseiterlastig. Gilt als beste Methode für 1X2.
- **Logit:** alle Logits um dieselbe Konstante verschieben.

Standard im Scan ist **Power**. Welche Methode am besten ist, soll später am CLV gemessen werden (Phase 5).

### Konsens mehrerer Referenzen

Jede Referenz (Pinnacle, Betfair …) wird devigged und mit Gewicht gemittelt. Betfair-Quoten werden vorher um die Kommission bereinigt. Referenzen älter als `max_age_s` (Standard 600 s) oder Börsen mit weniger als `min_exchange_liquidity` (Standard 2 000 €) gematchtem Volumen werden ignoriert. Gibt es keine gültige Referenz, gibt es für diesen Markt keine Valuebets.

### Valuebet

effektive Quote q_eff = q · (1 − Steuer) (Deutschland: 5,3 % auf den Einsatz) bzw. 1 + (q − 1)(1 − Kommission) (Börse).
EV = p · q_eff − 1.
Unsicherheit σ = √(p(1−p)/n_eff) · √(1 + Alter/120 s), mit n_eff = 400 (dünnere Märkte: kleiner).
EV_konservativ = (p − z·σ) · q_eff − 1 mit z = 1.
Ein Treffer entsteht, wenn EV_konservativ > `min_ev` (Standard 0).
Viertel-Kelly = ¼ · (p_low · (q_eff − 1) − (1 − p_low)) / (q_eff − 1).

### Surebet und Middle

Jede Wette bekommt pro Szenario (z. B. Tordifferenz −3…+3 oder Gesamttore 0…6) einen Auszahlungsfaktor: Quote bei Gewinn, 0 bei Verlust, 1 bei Rückgabe, (Quote+1)/2 bei halbem Gewinn, ½ bei halbem Verlust. Bei so vielen Szenarien wie Wetten werden die Auszahlungen durch ein lineares Gleichungssystem exakt angeglichen (klassische Surebet). Sonst (Middles, Viertellinien) wird die schlechteste Auszahlung maximiert. Ergebnis: Einsatzanteile, garantierte Marge und beste Auszahlung. Damit sind alle 21 Formeltypen von Betburger abgedeckt, ohne sie einzeln zu programmieren.

Der Scan nimmt für Surebets die **beste effektive Quote je Ausgang** über alle Buchmacher (nach Steuer und Kommission). Die Marge ist (1/Σ(1/q_eff) − 1) · 100.

---

## 10. Konfiguration

Datei `.env` (aus `.env.example`), nie committen:

| Variable | Bedeutung | Standard |
| --- | --- | --- |
| `DATABASE_URL` | Verbindung zur Datenbank | `postgresql://becher:becher@localhost:5432/becher` |
| `ODDS_API_KEY` | Key von the-odds-api.com | leer (Collector bricht ab) |
| `ODDS_API_SPORTS` | Ligen, kommagetrennt, z. B. `soccer_germany_bundesliga,soccer_epl,basketball_nba` | Bundesliga, EPL |
| `ODDS_API_REGIONS` | `eu`, `uk`, `us` … | `eu` |
| `ODDS_API_MARKETS` | `h2h,totals,spreads` | alle drei |
| `COLLECT_INTERVAL_SECONDS` | Takt des Collectors | 300 |
| `COLLECTORS` | aktive Collector: `odds_api`, `betfair` | `odds_api` |
| `BETFAIR_APP_KEY`, `BETFAIR_SESSION_TOKEN` oder `BETFAIR_USERNAME`/`BETFAIR_PASSWORD` | Zugang zur Betfair Exchange API (Developer-Programm; Delayed-Key kostenlos) | leer |
| `BETFAIR_EVENT_TYPES`, `BETFAIR_HOURS_AHEAD` | Sportarten (1 Fußball, 2 Tennis, 7522 Basketball) und Vorlauf | `1,2,7522`, 48 |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram-Alarm bei neuen Treffern (Einrichtung: Abschnitt 5) | leer |
| `NOTIFY_MIN_PERCENT` | Telegram nur bei Treffern ab diesem konservativen Prozent | 1.0 |
| `ANTHROPIC_API_KEY` | Claude-API-Schlüssel für die KI-Schicht (console.anthropic.com) | leer |
| `AI_MODEL`, `AI_EFFORT` | Modell und Denktiefe (low, medium, high) der KI-Schicht | `claude-opus-5-5`, `medium` |

Scan-Parameter (`engine.scan.ScanConfig`, per CLI `--method`, `--min-ev`, `--max-age`): Devig-Methode, Mindest-EV, maximales Quotenalter, Mindestliquidität Börse, n_eff, z, Gewichte sharp/exchange.

Buchmacher-Eigenschaften (Steuer, Kommission, Typ) stehen in der Tabelle `bookmakers` und werden direkt dort gepflegt, z. B. `UPDATE bookmakers SET tax_rate = 0 WHERE key = 'bet365';` wenn ein Konto nicht in Deutschland geführt wird.

---

## 11. Entwicklungsstand und Fahrplan

Aus `docs/konzept/04-entwicklungsplan-kern.md`, Stand 10. 11. 2026:

| Phase | Inhalt | Stand |
| --- | --- | --- |
| 1 Fundament | Datenbank, Odds-API-Collector, Store, Scripts, Tests | ✅ fertig |
| 2 Matching | Teams/Aliase, Fuzzy-Matching, Event-Zuordnung über Quellen | ✅ fertig |
| 3 Rechenkern | Devig, Konsens, Valuebets, Surebets/Middles, Scan → opportunities | ✅ fertig (Grundversion) |
| Dashboard | Scanner-Feed, Überblick, Quoten je Event, Läufe | ✅ fertig (Grundversion) |
| 4 Eigene Collector | Betfair Exchange API (Back/Lay + Liquidität) ✅; Grundgerüst für Buchmacher-Collector per Playwright ✅; konkrete Buchmacher-Parser, Perioden und mehr Märkte ⏳ | 🔶 teilweise |
| 5 Tracking + CLV | Wetten erfassen (Dashboard-Seite „Wetten“) ✅, Schlussquoten automatisch speichern ✅, CLV je Wette ✅, Auswertung je Buchmacher ✅, Telegram-Alarm ✅; Auswertung nach Markt/Devig-Methode ⏳ | ✅ Grundversion |
| 6 KI-Schicht | Treffer erklären und priorisieren ✅, Wochenbericht ✅, Kontext aus Treffern/Wetten/CLV/Collectoren ✅; Devig-Methode je Markt am CLV wählen ⏳, Limit-Risiko je Konto ⏳ | ✅ Grundversion |

Verbesserungen, die im Konzept vorgesehen sind und noch offen stehen: Backtesting über die gespeicherte Zeitreihe, Monte-Carlo-Simulation der Strategie, Schlussquoten-Vorhersage, Account-Health (Limit-Risiko je Buchmacher).

---

## 12. Becher im Vergleich zu Betburger

Analyse des eingeloggten Betburger-Bereichs steht in `docs/konzept/01` (Funktionen) und `06` (Technik). Kurzfassung:

| Thema | Betburger | Becher |
| --- | --- | --- |
| Quellen | ~150 eigene Collector + 600 Clones, Kafka-Pipeline | Odds-API (ca. 15–40 Buchmacher je Region), Phase 4 eigene Collector |
| Aktualität | Pollt alle 5 s (Prematch) / 3 s (Live) einen vorberechneten Index | Collector alle 5 min, Scan nach Bedarf; Live nicht geplant |
| Valuebet-Prozent | 2-Weg-Marge gegen die Gegenquote der Referenz, V2 devigt multiplikativ; ohne Steuer, ohne Alter, ohne Unsicherheit | EV gegen faire Wahrscheinlichkeit (5 Devig-Methoden, Konsens), nach Steuer, konservativer EV mit Alter und Marktdünne |
| Surebets | 21 handgeschriebene Formeln | ein generischer Auszahlungsmatrix-Löser |
| Einsatzrechner | ja, mit Rundung und Kommission | ja (Steuer, Kommission, Viertel-Kelly) |
| Backtesting | nur im Abo, aggregiert | Phase 5: eigene Zeitreihe, CLV je Wette |
| Preis | 80–320 € pro Monat | Odds-API 0–20 $ pro Monat, Strom |
| Konto-Schutz | nein | Phase 6 (Limit-Risiko, Einsatzprofil) |

---

## 13. Arbeitsregeln für die Entwicklung

- **Jeder Entwicklungsschritt wird sofort committet und gepusht** (Branch `main`, Repo Arian-hwaiz/becher). Lokal reicht ein Pull in GitHub Desktop.
- **Alle Projektdateien** (Dokumente, Daten, KI, Code) liegen im Repo-Ordner `C:\Users\arian\Documents\GitHub\becher`.
- **Keine Geheimnisse im Repo:** `.env` ist ignoriert, `.env.example` enthält nur Platzhalter. API-Keys, Passwörter und Zugangsdaten zu Wettkonten gehören nie in Dateien, Chats oder Screenshots.
- **Keine Anbindung an die Betburger-API.**
- Vor jedem Push `pytest -q`. Neue Rechenlogik bekommt Tests ohne Datenbank; Datenbank-Tests laufen nur mit `BECHER_TEST_DATABASE_URL`.
- Sprache in Code-Kommentaren, Dokumenten und Oberfläche: Deutsch. Bezeichner im Code: Englisch.

---

## 14. Fehlersuche

| Symptom | Ursache / Lösung |
| --- | --- |
| `ODDS_API_KEY fehlt` | `.env` anlegen und Key eintragen |
| `connection refused` zur Datenbank | Docker Desktop läuft nicht oder Container gestoppt: `docker compose -f infra/docker-compose.yml up -d` |
| `relation "…" does not exist` | Schema nicht eingespielt: `python scripts/init_db.py` |
| Collector loggt "Unbekannte Buchmacher-Schlüssel" | Buchmacher in `bookmakers` und `bookmaker_source_keys` ergänzen (SQL in `infra/schema.sql` als Vorlage) |
| Scan findet nichts | Referenz zu alt (`source_ts` älter als 10 min) oder keine scharfe Referenz im Markt; `--max-age` erhöhen oder Ligen wählen, die Pinnacle abdeckt. Nach deutscher Steuer verschwinden kleine Kanten, das ist korrekt. |
| Dashboard: "Keine Datenbankverbindung" | wie oben; `DATABASE_URL` in `.env` prüfen |
| Dashboard zeigt alte Daten | Cache 15 s; "Jetzt neu laden" |
| `ModuleNotFoundError: common` | Projekt nicht installiert: `pip install -e ".[dev,dashboard]"` in aktivierter venv |
| API-Kontingent aufgebraucht | Ligen oder Märkte in `.env` reduzieren, Intervall vergrößern, oder Paket bei the-odds-api.com |

Logs: Collector und Scan schreiben nach stdout (`logging.INFO`); jeder Lauf steht zusätzlich in `collector_runs`.

---

## 15. Glossar

- **1X2 / h2h:** Heimsieg, Unentschieden, Auswärtssieg (Moneyline).
- **Totals (TO/TU):** Über/Unter einer Linie (Tore, Punkte).
- **Spreads / AH:** Handicap aus Heimsicht; AH1(−1,5) = Heim muss mit 2 Toren gewinnen.
- **Soft / Sharp:** Buchmacher mit hoher Marge, der Gewinner limitiert, vs. Buchmacher mit kleiner Marge, der Gewinner akzeptiert und dessen Quoten als Referenz dienen.
- **Exchange / Börse:** Markt zwischen Spielern (Betfair); Back = auf ein Ereignis wetten, Lay = dagegen; Kommission auf den Nettogewinn; Liquidität = gematchtes Volumen.
- **Avgline:** bei Betburger der Durchschnitt mehrerer Buchmacher als Referenz.
- **EV:** Erwartungswert je 1 € Einsatz.
- **CLV:** Closing Line Value, Vorteil gegenüber der Schlussquote.
- **Kelly:** optimale Einsatzgröße bei bekanntem Vorteil; Becher nutzt ein Viertel davon.
- **Devig / Vig:** Marge entfernen / die Marge selbst.
- **Snapshot:** eine gespeicherte Quote mit Zeitstempel.
- **Opportunity:** ein Treffer des Scans (Valuebet, Surebet, Middle).
