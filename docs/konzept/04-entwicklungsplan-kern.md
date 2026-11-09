# Entwicklungsplan: privater Kern (Datensammlung + KI)

Stand: 9. November 2026 · nur für den privaten Einsatz, keine öffentliche Plattform, keine Firma

## Ziel

Ein System, das nur für dich läuft: Es sammelt Quoten, speichert die Historie, rechnet Valuebets und Surebets aus und hat eine KI obendrauf, mit der du die Daten auswertest und befragst. Kein Login, keine Abos, keine Website für andere.

Realistischer Umfang: etwa **14 Wochen** neben dem Alltag, laufende Kosten etwa **30 bis 150 € im Monat** (Schätzung).

## Wichtigste Designentscheidung: Wer rechnet was?

Die Mathematik (Devig, EV, Surebet-Einsätze, Kelly) macht **normaler Code**, nicht die KI. Der ist exakt, schnell und kostet nichts pro Rechnung. Ein Sprachmodell würde sich bei Zahlen gelegentlich verrechnen und wäre für tausende Quoten pro Minute zu langsam und zu teuer.

Die KI kommt dort zum Einsatz, wo Code schwach ist:

| Aufgabe | Wer macht es | Warum |
| --- | --- | --- |
| Quoten abholen und speichern | Code (Collector) | Muss schnell und zuverlässig laufen |
| Devig, EV, Surebets, Kelly | Code (Rechenkern) | Exakte Mathematik, tausende Male pro Minute |
| Teamnamen zuordnen, die der Alias-Abgleich nicht schafft ("Bayern Munich" = "FC Bayern München") | KI (Sprachmodell) | Versteht Namen, Abkürzungen, Sprachen |
| Fragen in normaler Sprache ("Welche Valuebets über 3 % gibt es heute bei Tipico?") | KI mit Datenbank-Zugriff | Übersetzt Frage in Abfrage und erklärt das Ergebnis |
| Täglicher Bericht: Chancen, CLV, Auffälligkeiten | KI | Fasst zusammen und kommentiert |
| Ausreißer erklären (Fehlerquote, Verletzung, Linienbewegung) | KI | Ordnet ein |
| Eigene Prognosen (z. B. wohin sich eine Quote bewegt) | Klassisches Machine Learning (LightGBM), später | Braucht Monate an eigener Historie |

**KI-Wahl:** Für den Start die Claude-API (kein eigener Grafikkartenrechner nötig, nach meiner Schätzung wenige bis einige zehn Euro im Monat bei privater Nutzung). Optional später ein lokales Modell über Ollama, dafür braucht der Rechner aber eine starke Grafikkarte.

## Technik (bewusst einfach, eine Sprache)

| Teil | Wahl | Grund |
| --- | --- | --- |
| Sprache | Python | Eine Sprache für alles, viele Bibliotheken, gut mit KI-Hilfe zu schreiben |
| Datenbank | PostgreSQL mit TimescaleDB (in Docker) | Quoten-Historie als Zeitreihe, Standard-SQL |
| Zeitplanung | APScheduler (später Prefect, falls nötig) | Collector regelmäßig starten |
| Matching | rapidfuzz + Alias-Tabelle, KI als Ausweichlösung | Schnell und günstig, KI nur für schwierige Fälle |
| Oberfläche | Streamlit-Dashboard (lokal) | Tabellen und Grafiken ohne Web-Entwicklung |
| Benachrichtigung | Privater Telegram-Bot | Chancen aufs Handy, KI-Chat unterwegs |
| Betrieb | Docker Compose; eigener PC oder kleiner Hetzner-Server | Ein Befehl startet alles |

**Wo es läuft:** Zum Entwickeln auf deinem PC. Für den Dauerbetrieb (24/7) ein kleiner Cloud-Server, z. B. Hetzner mit 4 bis 8 GB RAM für grob 10 bis 20 € im Monat. Für Prematch und eine Handvoll Buchmacher reicht das.

## Datenmodell (Kern)

| Tabelle | Inhalt |
| --- | --- |
| `bookmakers` | Buchmacher, Land, Typ (sharp/soft/Börse), Quelle |
| `teams`, `team_aliases` | Einheitliche Teams und alle Schreibweisen je Buchmacher |
| `events` | Spiel, Liga, Startzeit, Teams |
| `markets` | Markttyp (1X2, Über/Unter, Asian Handicap), Linie, Regeln |
| `odds_snapshots` | Zeitstempel, Buchmacher, Event, Markt, Ausgang, Quote (Zeitreihe) |
| `opportunities` | Gefundene Valuebets/Surebets mit EV, fairer Quote, Methode |
| `bets` | Deine eigenen Wetten: Einsatz, Quote, Ergebnis |
| `closing_odds` | Schlussquoten je Markt für die CLV-Auswertung |

## Phasen

### Phase 1: Fundament (Woche 1–2)

- Repo-Struktur, Docker Compose mit PostgreSQL/TimescaleDB, Konfiguration über `.env`
- Datenmodell anlegen (Tabellen oben)
- Erste Quelle: eine Odds-API (z. B. The Odds API, die nach meinem Stand eine kostenlose Einstiegsstufe hat) für Fußball Prematch, 1X2 und Über/Unter
- Betfair-Entwicklerkonto: Der verzögerte App-Key ist nach meinem Stand kostenlos und reicht zum Entwickeln

**Fertig, wenn:** alle 5 Minuten neue Quoten von mindestens 10 Buchmachern in der Datenbank landen.

### Phase 2: Normalisierung und Matching (Woche 3–4)

- Alias-Tabelle für Teams und Ligen, Abgleich mit rapidfuzz plus Startzeit
- Unklare Fälle an die KI geben, Ergebnis als neuen Alias speichern (das System lernt mit)
- Märkte vereinheitlichen: 1X2, Über/Unter, Asian Handicap inklusive Viertel-Linien

**Fertig, wenn:** über 98 % der Events automatisch richtig zugeordnet werden (Stichprobe von Hand prüfen).

### Phase 3: Rechenkern (Woche 5–6)

- Devig-Methoden: multiplikativ, Power, Shin; Referenz Pinnacle bzw. Betfair
- EV-Berechnung, Surebet-Erkennung mit Einsatzverteilung, Kelly-Bruchteil
- Ausreißer-Filter (Quote zu alt, Abweichung zu groß)
- Tests mit bekannten Rechenbeispielen
- Telegram-Alarm bei Valuebets über deinem Schwellenwert

**Fertig, wenn:** die Alarme stimmen und jede Zahl gegen einen Online-Rechner nachgeprüft ist.

### Phase 4: Eigene Collector (Woche 7–8)

- 2 bis 3 Buchmacher, die die API nicht oder zu langsam liefert (siehe [03-scraping-und-server.md](03-scraping-und-server.md))
- Überwachung: Alarm, wenn ein Collector länger als X Minuten nichts liefert

**Fertig, wenn:** die eigenen Collector eine Woche ohne Eingriff laufen.

### Phase 5: Tracking und CLV (Woche 9–10)

- Eigene Wetten erfassen (Telegram-Befehl oder Dashboard)
- Schlussquote kurz vor Anpfiff automatisch speichern
- Auswertung: Gewinn, ROI, CLV pro Buchmacher, Markt und Methode im Streamlit-Dashboard

**Fertig, wenn:** jede Wette automatisch ihren CLV bekommt.

### Phase 6: KI-Schicht (Woche 11–14)

- KI-Assistent mit Werkzeugen: Datenbank lesen (nur lesend), Rechenkern aufrufen, Ergebnisse erklären
- Chat über Telegram ("Was waren gestern meine besten Wetten?", "Wie hat sich die Quote bei X bewegt?")
- Täglicher Bericht morgens: offene Chancen, CLV der letzten Woche, auffällige Linienbewegungen
- Matching-Hilfe aus Phase 2 ausbauen

**Fertig, wenn:** du die wichtigsten Fragen per Chat beantwortet bekommst und der Tagesbericht jeden Morgen kommt.

### Danach (optional)

- Nach 3 bis 6 Monaten Historie: eigenes ML-Modell (LightGBM) für Linienbewegungen bzw. eigene Wahrscheinlichkeiten, ausgewertet am CLV
- Live-Daten (Betfair-Stream, WebSocket-Collector)

## Ordner im Repo

```
becher/
├── collectors/        # ein Modul pro Quelle (odds_api.py, betfair.py, buchmacher_x.py)
├── engine/            # devig.py, value.py, arbs.py, kelly.py + Tests
├── ai/                # KI-Assistent, Prompts, Werkzeuge, später ML-Modelle
├── data/              # Alias-Listen, Markt-Mappings (große Rohdaten nicht ins Git)
├── infra/             # docker-compose.yml, Datenbank-Schema, Backups
├── website/           # später: Streamlit-Dashboard
└── docs/              # Konzepte und Pläne
```

## Laufende Kosten privat (Schätzung)

| Posten | Pro Monat |
| --- | --- |
| Server (oder eigener PC: 0 €) | 0–20 € |
| Odds-API | 0–100 € (je nach Stufe und Abfragen) |
| Claude-API | 5–30 € |
| Proxies (erst ab eigenen Collectorn) | 0–50 € |
| **Summe** | **ca. 5–200 €**, typisch 30–150 € |

Einmalig: Betfair-Live-Key, falls du Echtzeit-Daten willst (ca. 350 €, Schätzung), plus eigenes Wettkapital.

## Hinweise

- Auch privat gilt: Scraping kann gegen die AGB der Buchmacher verstoßen, und Konten können bei auffälligem Verhalten limitiert werden.
- Keine automatische Wettplatzierung bauen; das gefährdet deine Konten.
- API-Schlüssel nur in `.env`, nie ins Git.
