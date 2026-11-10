-- Becher: Datenbankschema (Phase 1)
-- Wird beim ersten Start des Containers automatisch eingespielt.
-- Manuell: psql "$DATABASE_URL" -f infra/schema.sql

-- TimescaleDB ist optional: ohne Erweiterung bleibt odds_snapshots eine normale Tabelle.
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS timescaledb;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'timescaledb nicht verfügbar, normale Tabelle wird verwendet';
END $$;

-- Buchmacher: sharp = scharfe Referenz, soft = normaler Buchmacher, exchange = Börse
CREATE TABLE IF NOT EXISTS bookmakers (
    id            SERIAL PRIMARY KEY,
    key           TEXT UNIQUE NOT NULL,          -- interner Schlüssel, z. B. "pinnacle"
    name          TEXT NOT NULL,
    country       TEXT,                          -- ISO-2, z. B. "DE"
    kind          TEXT NOT NULL DEFAULT 'soft' CHECK (kind IN ('sharp','soft','exchange')),
    tax_rate      NUMERIC(5,4) NOT NULL DEFAULT 0,   -- 0.053 = deutsche Wettsteuer
    tax_mode      TEXT NOT NULL DEFAULT 'none' CHECK (tax_mode IN ('none','on_stake','on_winnings')),
    commission    NUMERIC(5,4) NOT NULL DEFAULT 0,   -- Börsenkommission auf Nettogewinn
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Administration: Stand des eigenen Scrapers je Buchmacher (To-do-Liste im Dashboard)
ALTER TABLE bookmakers ADD COLUMN IF NOT EXISTS scraper_status TEXT NOT NULL DEFAULT 'offen';
ALTER TABLE bookmakers ADD COLUMN IF NOT EXISTS scraper_note TEXT;
DO $$ BEGIN
  ALTER TABLE bookmakers ADD CONSTRAINT bookmakers_scraper_status_chk
    CHECK (scraper_status IN ('offen','in_arbeit','laeuft','blockiert','nicht_moeglich','nicht_noetig'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Administration: Collector (Quellen) ein- und ausschalten; fehlt die Zeile, gilt der Collector als eingeschaltet
CREATE TABLE IF NOT EXISTS collector_settings (
    source      TEXT PRIMARY KEY,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Startseite je Buchmacher (Fallback-Link im Dashboard) und Deep-Links je Event
ALTER TABLE bookmakers ADD COLUMN IF NOT EXISTS url TEXT;
CREATE TABLE IF NOT EXISTS event_links (
    event_id      BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    bookmaker_id  INTEGER NOT NULL REFERENCES bookmakers(id),
    url           TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, bookmaker_id)
);

-- Quellen (Odds-API, Betfair, eigener Collector) und ihre Schlüssel je Buchmacher
CREATE TABLE IF NOT EXISTS bookmaker_source_keys (
    source        TEXT NOT NULL,                 -- z. B. "odds_api"
    source_key    TEXT NOT NULL,                 -- Schlüssel in dieser Quelle
    bookmaker_id  INTEGER NOT NULL REFERENCES bookmakers(id),
    PRIMARY KEY (source, source_key)
);

CREATE TABLE IF NOT EXISTS sports (
    id    SERIAL PRIMARY KEY,
    key   TEXT UNIQUE NOT NULL,                  -- "soccer", "tennis"
    name  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leagues (
    id        SERIAL PRIMARY KEY,
    sport_id  INTEGER NOT NULL REFERENCES sports(id),
    key       TEXT UNIQUE NOT NULL,              -- "soccer_germany_bundesliga"
    name      TEXT NOT NULL,
    country   TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id         SERIAL PRIMARY KEY,
    sport_id   INTEGER NOT NULL REFERENCES sports(id),
    name       TEXT NOT NULL,                    -- kanonischer Name
    UNIQUE (sport_id, name)
);

-- Alle Schreibweisen eines Teams je Quelle/Buchmacher. Wird in Phase 2 befüllt.
CREATE TABLE IF NOT EXISTS team_aliases (
    id        SERIAL PRIMARY KEY,
    team_id   INTEGER NOT NULL REFERENCES teams(id),
    source    TEXT NOT NULL,
    alias     TEXT NOT NULL,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1,  -- 1 = von Hand bestätigt
    UNIQUE (source, alias)
);

CREATE TABLE IF NOT EXISTS events (
    id            BIGSERIAL PRIMARY KEY,
    league_id     INTEGER NOT NULL REFERENCES leagues(id),
    home_team_id  INTEGER REFERENCES teams(id),
    away_team_id  INTEGER REFERENCES teams(id),
    home_name     TEXT NOT NULL,                 -- Rohname, bis Matching steht
    away_name     TEXT NOT NULL,
    start_time    TIMESTAMPTZ NOT NULL,
    status        TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','live','finished','cancelled')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ein Event kann in jeder Quelle eine eigene ID haben
CREATE TABLE IF NOT EXISTS event_source_ids (
    source     TEXT NOT NULL,
    source_id  TEXT NOT NULL,
    event_id   BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    PRIMARY KEY (source, source_id)
);
-- Quelle listet Heim/Gast vertauscht (Phase 2 Matching)
ALTER TABLE event_source_ids ADD COLUMN IF NOT EXISTS swap_teams BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS events_start_time_idx ON events(start_time);

-- Markt-Typen: 1X2, Über/Unter, Handicap. Linie z. B. 2.5 bei Totals.
CREATE TABLE IF NOT EXISTS markets (
    id         BIGSERIAL PRIMARY KEY,
    event_id   BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    type       TEXT NOT NULL CHECK (type IN ('h2h','totals','spreads')),
    line       NUMERIC(6,2),                     -- NULL bei h2h
    period     TEXT NOT NULL DEFAULT 'full_time',
    UNIQUE (event_id, type, line, period)
);

-- Quoten-Zeitreihe. Eine Zeile pro Buchmacher, Markt, Ausgang und Zeitpunkt.
CREATE TABLE IF NOT EXISTS odds_snapshots (
    observed_at   TIMESTAMPTZ NOT NULL,          -- unser Abfragezeitpunkt
    source_ts     TIMESTAMPTZ,                   -- Zeitstempel laut Quelle, falls vorhanden
    market_id     BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    bookmaker_id  INTEGER NOT NULL REFERENCES bookmakers(id),
    outcome       TEXT NOT NULL,                 -- "home","draw","away","over","under"
    price         NUMERIC(8,3) NOT NULL,         -- Dezimalquote
    source        TEXT NOT NULL
);

-- Phase 2/3: Lay-Quoten und Liquidität (Börsen), nachträglich ergänzbar
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS is_lay     BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS lay_price  NUMERIC(8,3);     -- Lay-Quote an der Börse
ALTER TABLE odds_snapshots ADD COLUMN IF NOT EXISTS liquidity  NUMERIC(12,2);    -- gematchtes Volumen in EUR

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') THEN
    PERFORM create_hypertable('odds_snapshots', 'observed_at', if_not_exists => TRUE);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS odds_market_book_idx ON odds_snapshots (market_id, bookmaker_id, observed_at DESC);

-- Schlussquoten je Markt und Buchmacher (Phase 5, CLV)
CREATE TABLE IF NOT EXISTS closing_odds (
    market_id     BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    bookmaker_id  INTEGER NOT NULL REFERENCES bookmakers(id),
    outcome       TEXT NOT NULL,
    price         NUMERIC(8,3) NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (market_id, bookmaker_id, outcome)
);

-- Gefundene Chancen (Phase 3)
CREATE TABLE IF NOT EXISTS opportunities (
    id            BIGSERIAL PRIMARY KEY,
    found_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind          TEXT NOT NULL CHECK (kind IN ('value','arb','middle')),
    market_id     BIGINT NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    bookmaker_id  INTEGER REFERENCES bookmakers(id),
    outcome       TEXT,
    price         NUMERIC(8,3),
    fair_price    NUMERIC(8,3),
    ev            NUMERIC(7,4),                  -- nach Steuer
    ev_conservative NUMERIC(7,4),
    method        TEXT,                          -- Devig-Methode
    reference_age_s INTEGER,
    details       JSONB
);
CREATE INDEX IF NOT EXISTS opportunities_found_idx ON opportunities(found_at DESC);

-- Eigene Wetten (Phase 5)
CREATE TABLE IF NOT EXISTS bets (
    id            BIGSERIAL PRIMARY KEY,
    placed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    market_id     BIGINT REFERENCES markets(id),
    bookmaker_id  INTEGER NOT NULL REFERENCES bookmakers(id),
    outcome       TEXT NOT NULL,
    stake         NUMERIC(10,2) NOT NULL,
    price         NUMERIC(8,3) NOT NULL,
    fair_price_at_bet NUMERIC(8,3),
    result        TEXT CHECK (result IN ('open','won','lost','void','half_won','half_lost')) DEFAULT 'open',
    payout        NUMERIC(10,2),
    clv           NUMERIC(7,4),                  -- wird nach Anpfiff berechnet
    note          TEXT
);

-- KI-Auswertungen (Phase 6)
CREATE TABLE IF NOT EXISTS ai_reports (
    id            BIGSERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind          TEXT NOT NULL,                 -- assessment | weekly
    model         TEXT,
    context_hours INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    content       TEXT NOT NULL                  -- JSON (assessment) oder Markdown (weekly)
);

-- Zustand der Collector für Überwachung
CREATE TABLE IF NOT EXISTS collector_runs (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    ok          BOOLEAN,
    events      INTEGER DEFAULT 0,
    snapshots   INTEGER DEFAULT 0,
    error       TEXT
);

-- Startdaten: Sportarten und bekannte Buchmacher. Steuer steht überall auf 0 (Rohquoten-Vergleich);
-- deutsche Wettsteuer 5,3 % bei Bedarf mit `python scripts/set_tax.py --country DE` einschalten.
INSERT INTO sports (key, name) VALUES ('soccer','Fußball'), ('tennis','Tennis'), ('basketball','Basketball')
ON CONFLICT (key) DO NOTHING;

INSERT INTO bookmakers (key, name, country, kind, tax_rate, tax_mode, commission) VALUES
  ('pinnacle',   'Pinnacle',   'CW', 'sharp',    0,     'none',     0),
  ('betfair_ex', 'Betfair Exchange', 'GB', 'exchange', 0, 'none',  0.05),
  ('bet365',     'Bet365',     'DE', 'soft',     0,     'none',     0),
  ('tipico',     'Tipico',     'DE', 'soft',     0,     'none',     0),
  ('bwin',       'bwin',       'DE', 'soft',     0,     'none',     0),
  ('betano',     'Betano',     'DE', 'soft',     0,     'none',     0),
  ('unibet',     'Unibet',     'DE', 'soft',     0,     'none',     0),
  ('williamhill','William Hill','GB','soft',     0,     'none',     0),
  ('betway',     'Betway',     'GB', 'soft',     0,     'none',     0),
  ('onexbet',    '1xBet',      'CY', 'soft',     0,     'none',     0),
  -- weitere Buchmacher, die die Odds-API für Region eu liefert 
  ('winamax',    'Winamax',    'DE', 'soft',     0,     'none',     0),
  ('betclic',    'Betclic',    'FR', 'soft',     0,     'none',     0),
  ('betsson',    'Betsson',    'MT', 'soft',     0,     'none',     0),
  ('codere',     'Codere',     'IT', 'soft',     0,     'none',     0),
  ('coolbet',    'Coolbet',    'EE', 'soft',     0,     'none',     0),
  ('everygame',  'Everygame',  'CW', 'soft',     0,     'none',     0),
  ('leovegas',   'LeoVegas',   'SE', 'soft',     0,     'none',     0),
  ('marathonbet','Marathonbet','GB', 'soft',     0,     'none',     0),
  ('nordicbet',  'NordicBet',  'MT', 'soft',     0,     'none',     0),
  ('pmu',        'PMU',        'FR', 'soft',     0,     'none',     0),
  ('sport888',   '888sport',   'GI', 'soft',     0,     'none',     0)
ON CONFLICT (key) DO NOTHING;

-- Startseiten (nur setzen, wenn leer)
UPDATE bookmakers b SET url = v.url FROM (VALUES
  ('pinnacle','https://www.pinnacle.com'),
  ('betfair_ex','https://www.betfair.com/exchange'),
  ('bet365','https://www.bet365.de'),
  ('tipico','https://sports.tipico.de'),
  ('bwin','https://sports.bwin.de'),
  ('betano','https://www.betano.de'),
  ('unibet','https://www.unibet.de'),
  ('williamhill','https://sports.williamhill.com'),
  ('betway','https://betway.de'),
  ('onexbet','https://1xbet.com'),
  ('winamax','https://www.winamax.de'),
  ('betclic','https://www.betclic.fr'),
  ('betsson','https://www.betsson.com'),
  ('codere','https://www.codere.it'),
  ('coolbet','https://www.coolbet.com'),
  ('everygame','https://www.everygame.eu'),
  ('leovegas','https://www.leovegas.com'),
  ('marathonbet','https://www.marathonbet.com'),
  ('nordicbet','https://www.nordicbet.com'),
  ('pmu','https://paris-sportifs.pmu.fr'),
  ('sport888','https://www.888sport.com')
) AS v(key, url) WHERE b.key = v.key AND b.url IS NULL;

-- Betfair kommt über die offizielle API: kein eigener Scraper nötig
UPDATE bookmakers SET scraper_status = 'nicht_noetig' WHERE key = 'betfair_ex' AND scraper_status = 'offen';

-- Zuordnung der Odds-API-Schlüssel zu unseren Buchmachern
INSERT INTO bookmaker_source_keys (source, source_key, bookmaker_id)
SELECT 'odds_api', v.src, b.id FROM (VALUES
  ('pinnacle','pinnacle'), ('betfair_ex_eu','betfair_ex'), ('bet365','bet365'), ('tipico_de','tipico'),
  ('bwin','bwin'), ('betano','betano'), ('unibet_eu','unibet'), ('williamhill','williamhill'),
  ('betway','betway'), ('onexbet','onexbet'),
  ('winamax_de','winamax'), ('winamax_fr','winamax'), ('betclic_fr','betclic'), ('betsson','betsson'),
  ('codere_it','codere'), ('coolbet','coolbet'), ('everygame','everygame'), ('leovegas_se','leovegas'),
  ('marathonbet','marathonbet'), ('nordicbet','nordicbet'), ('pmu_fr','pmu'), ('sport888','sport888'),
  ('unibet_fr','unibet'), ('unibet_nl','unibet'), ('unibet_se','unibet')
) AS v(src, key) JOIN bookmakers b ON b.key = v.key
ON CONFLICT DO NOTHING;

-- Betfair-Collector schreibt unter source='betfair' mit Schlüssel 'betfair_ex'
INSERT INTO bookmaker_source_keys (source, source_key, bookmaker_id)
SELECT 'betfair', 'betfair_ex', id FROM bookmakers WHERE key = 'betfair_ex'
ON CONFLICT DO NOTHING;
