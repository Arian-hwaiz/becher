"""SQL-Abfragen für das Dashboard. Jede Funktion bekommt eine offene Verbindung und liefert
pandas-DataFrames (oder ein dict für die Kennzahlen). Ohne Streamlit testbar."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd


def _df(conn, sql: str, params: tuple = ()) -> pd.DataFrame:
    rows = conn.execute(sql, params).fetchall()
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def summary(conn) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    h1, d1 = now - timedelta(hours=1), now - timedelta(days=1)
    out: dict[str, Any] = {}
    out["events_upcoming"] = conn.execute("SELECT count(*) AS n FROM events WHERE start_time > %s", (now,)).fetchone()["n"]
    out["snapshots_1h"] = conn.execute("SELECT count(*) AS n FROM odds_snapshots WHERE observed_at > %s", (h1,)).fetchone()["n"]
    out["bookmakers_1h"] = conn.execute("SELECT count(DISTINCT bookmaker_id) AS n FROM odds_snapshots WHERE observed_at > %s", (h1,)).fetchone()["n"]
    out["values_24h"] = conn.execute("SELECT count(*) AS n FROM opportunities WHERE kind='value' AND found_at > %s", (d1,)).fetchone()["n"]
    out["arbs_24h"] = conn.execute("SELECT count(*) AS n FROM opportunities WHERE kind='arb' AND found_at > %s", (d1,)).fetchone()["n"]
    out["last_run"] = conn.execute(
        "SELECT source, started_at, ok, events, snapshots, error FROM collector_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return out


def snapshots_per_hour(conn, hours: int = 48) -> pd.DataFrame:
    return _df(conn, """
        SELECT date_trunc('hour', observed_at) AS hour, source, count(*) AS n
        FROM odds_snapshots WHERE observed_at > now() - make_interval(hours => %s)
        GROUP BY 1, 2 ORDER BY 1""", (hours,))


def coverage(conn, minutes: int = 60) -> pd.DataFrame:
    return _df(conn, """
        SELECT b.name, b.kind, count(*) AS n, max(o.observed_at) AS last_seen
        FROM odds_snapshots o JOIN bookmakers b ON b.id = o.bookmaker_id
        WHERE o.observed_at > now() - make_interval(mins => %s)
        GROUP BY b.name, b.kind ORDER BY n DESC""", (minutes,))


def opportunities(conn, hours: int = 24, limit: int = 100) -> pd.DataFrame:
    return _df(conn, """
        SELECT o.found_at, o.kind, o.outcome, o.price, o.fair_price, o.ev, o.ev_conservative, o.method,
               o.reference_age_s, o.details, o.bookmaker_id, b.name AS bookmaker, m.type, m.line, m.period,
               e.id AS event_id, e.home_name, e.away_name, e.start_time, l.name AS league, s.name AS sport
        FROM opportunities o
        JOIN markets m ON m.id = o.market_id
        JOIN events e ON e.id = m.event_id
        JOIN leagues l ON l.id = e.league_id
        JOIN sports s ON s.id = l.sport_id
        LEFT JOIN bookmakers b ON b.id = o.bookmaker_id
        WHERE o.found_at > now() - make_interval(hours => %s)
        ORDER BY o.ev_conservative DESC NULLS LAST, o.found_at DESC
        LIMIT %s""", (hours, limit))


def upcoming_events(conn, limit: int = 200) -> pd.DataFrame:
    return _df(conn, """
        SELECT e.id, e.home_name, e.away_name, e.start_time, l.name AS league
        FROM events e JOIN leagues l ON l.id = e.league_id
        WHERE e.start_time > now() ORDER BY e.start_time LIMIT %s""", (limit,))


def event_markets(conn, event_id: int) -> pd.DataFrame:
    return _df(conn, "SELECT id, type, line, period FROM markets WHERE event_id=%s ORDER BY type, line", (event_id,))


def market_latest_odds(conn, market_id: int) -> pd.DataFrame:
    return _df(conn, """
        SELECT DISTINCT ON (o.bookmaker_id, o.outcome) b.name AS bookmaker, o.outcome, o.price::float AS price, o.observed_at
        FROM odds_snapshots o JOIN bookmakers b ON b.id = o.bookmaker_id
        WHERE o.market_id=%s ORDER BY o.bookmaker_id, o.outcome, o.observed_at DESC""", (market_id,))


def market_history(conn, market_id: int, hours: int = 72) -> pd.DataFrame:
    return _df(conn, """
        SELECT o.observed_at, b.name AS bookmaker, o.outcome, o.price::float AS price
        FROM odds_snapshots o JOIN bookmakers b ON b.id = o.bookmaker_id
        WHERE o.market_id=%s AND o.observed_at > now() - make_interval(hours => %s)
        ORDER BY o.observed_at""", (market_id, hours))


def runs(conn, limit: int = 200) -> pd.DataFrame:
    return _df(conn, """
        SELECT started_at, finished_at, source, ok, events, snapshots, error
        FROM collector_runs ORDER BY started_at DESC LIMIT %s""", (limit,))


def bookmaker_names(conn) -> dict[int, str]:
    return {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM bookmakers").fetchall()}


def bookmaker_urls(conn) -> dict[int, str]:
    return {r["id"]: r["url"] for r in conn.execute("SELECT id, url FROM bookmakers WHERE url IS NOT NULL").fetchall()}


def event_bookmakers(conn, event_id: int) -> list[int]:
    """Buchmacher, die für dieses Event Quoten geliefert haben."""
    return [r["bookmaker_id"] for r in conn.execute(
        """SELECT DISTINCT o.bookmaker_id FROM odds_snapshots o JOIN markets m ON m.id = o.market_id
           WHERE m.event_id=%s""", (event_id,)).fetchall()]


def event_links(conn, event_id: int) -> dict[int, str]:
    """Deep-Links je Buchmacher für ein Event (aus der Quelle, z. B. Odds-API includeLinks)."""
    return {r["bookmaker_id"]: r["url"] for r in conn.execute(
        "SELECT bookmaker_id, url FROM event_links WHERE event_id=%s", (event_id,)).fetchall()}


def latest_opportunities(conn, hours: int = 24, limit: int = 500) -> pd.DataFrame:
    """Wie ``opportunities``, aber je Markt/Buchmacher/Ausgang nur der jüngste Treffer (Scanner-Feed)."""
    df = opportunities(conn, hours, limit * 5)
    if df.empty:
        return df
    key = df[["kind", "event_id", "type", "line", "bookmaker", "outcome"]].fillna("").astype(str).agg("|".join, axis=1)
    df = df.assign(_key=key).sort_values("found_at", ascending=False).drop_duplicates("_key").drop(columns="_key")
    return df.head(limit)


# ---------------------------------------------------------------- Wetten (Phase 5)

def bets(conn, limit: int = 500) -> pd.DataFrame:
    return _df(conn, """
        SELECT b.id, b.placed_at, k.name AS bookmaker, b.outcome, b.stake, b.price, b.fair_price_at_bet,
               b.result, b.payout, b.clv, b.note, b.market_id,
               e.home_name, e.away_name, e.start_time, m.type, m.line
        FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id
        LEFT JOIN markets m ON m.id = b.market_id LEFT JOIN events e ON e.id = m.event_id
        ORDER BY b.placed_at DESC LIMIT %s""", (limit,))


def bet_stats(conn) -> dict[str, Any]:
    r = conn.execute("""
        SELECT count(*) AS n,
               count(*) FILTER (WHERE result <> 'open') AS settled,
               coalesce(sum(stake) FILTER (WHERE result <> 'open'), 0) AS stake_settled,
               coalesce(sum(coalesce(payout, 0) - stake) FILTER (WHERE result <> 'open'), 0) AS profit,
               avg(clv) AS clv, count(clv) AS n_clv,
               count(*) FILTER (WHERE clv > 0) AS clv_pos
        FROM bets""").fetchone()
    return dict(r)


def clv_by_bookmaker(conn) -> pd.DataFrame:
    return _df(conn, """
        SELECT k.name AS bookmaker, count(*) AS n, avg(b.clv) AS clv, count(b.clv) AS n_clv,
               coalesce(sum(coalesce(b.payout, 0) - b.stake) FILTER (WHERE b.result <> 'open'), 0) AS profit
        FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id GROUP BY k.name ORDER BY n DESC""")


def add_bet(conn, bookmaker_id: int, outcome: str, stake: float, price: float, market_id: int | None,
            fair_price: float | None, note: str) -> int:
    row = conn.execute(
        """INSERT INTO bets (bookmaker_id, outcome, stake, price, market_id, fair_price_at_bet, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
        (bookmaker_id, outcome, stake, price, market_id, fair_price, note or None),
    ).fetchone()
    return row["id"]


def settle_bet(conn, bet_id: int, result: str, payout: float) -> None:
    conn.execute("UPDATE bets SET result=%s, payout=%s WHERE id=%s", (result, payout, bet_id))


# ---------------------------------------------------------------- KI (Phase 6)

def ai_reports(conn, limit: int = 50) -> pd.DataFrame:
    return _df(conn, """
        SELECT id, created_at, kind, model, context_hours, input_tokens, output_tokens, content
        FROM ai_reports ORDER BY created_at DESC LIMIT %s""", (limit,))


# ---------------------------------------------------------------- Administration

SCRAPER_STATUS = {"offen": "offen", "in_arbeit": "in Arbeit", "laeuft": "läuft", "blockiert": "blockiert (Bot-Schutz)",
                  "nicht_moeglich": "nicht möglich", "nicht_noetig": "nicht nötig (API)"}


def admin_bookmakers(conn, fresh_hours: int = 6, stale_hours: int = 48) -> pd.DataFrame:
    """Alle Anbieter mit Schalter, Scraper-Stand und Datenlage (welche Quelle liefert, wann zuletzt)."""
    df = _df(conn, """
        WITH seen AS (
            SELECT bookmaker_id, max(observed_at) AS last_seen,
                   count(*) FILTER (WHERE observed_at > now() - interval '24 hours') AS quotes_24h,
                   string_agg(DISTINCT source, ', ') FILTER (WHERE observed_at > now() - interval '48 hours') AS live_sources
            FROM odds_snapshots WHERE observed_at > now() - interval '14 days' GROUP BY bookmaker_id
        ), keys AS (
            SELECT bookmaker_id, string_agg(DISTINCT source, ', ' ORDER BY source) AS sources
            FROM bookmaker_source_keys GROUP BY bookmaker_id
        )
        SELECT b.id, b.key, b.name, b.kind, b.country, b.is_active, b.tax_rate::float AS tax_rate, b.url,
               b.scraper_status, b.scraper_note, k.sources, s.live_sources, s.last_seen, coalesce(s.quotes_24h, 0) AS quotes_24h
        FROM bookmakers b LEFT JOIN seen s ON s.bookmaker_id = b.id LEFT JOIN keys k ON k.bookmaker_id = b.id
        ORDER BY b.kind, b.name""")
    if df.empty:
        df["data_state"] = []
        return df
    now = pd.Timestamp.now(tz="UTC")
    age_h = (now - pd.to_datetime(df["last_seen"], utc=True)).dt.total_seconds() / 3600
    df["age_h"] = age_h
    df["data_state"] = ["keine" if pd.isna(a) else "frisch" if a <= fresh_hours else "alt" if a <= stale_hours else "veraltet"
                        for a in age_h]
    return df


def set_bookmaker_active(conn, bookmaker_id: int, active: bool) -> None:
    conn.execute("UPDATE bookmakers SET is_active=%s WHERE id=%s", (active, bookmaker_id))


def set_bookmaker_scraper(conn, bookmaker_id: int, status: str, note: str | None) -> None:
    if status not in SCRAPER_STATUS:
        raise ValueError(status)
    note = note.strip() if isinstance(note, str) else None   # geleerte Zelle kommt als NaN/None an
    if note in ("", "NaN", "nan", "None"):
        note = None
    conn.execute("UPDATE bookmakers SET scraper_status=%s, scraper_note=%s WHERE id=%s", (status, note, bookmaker_id))


def activate_only_with_data(conn, stale_hours: int = 48) -> tuple[int, int]:
    """Lässt nur Anbieter aktiv, die in den letzten ``stale_hours`` Quoten geliefert haben. Gibt (aktiv, inaktiv) zurück."""
    conn.execute(
        """UPDATE bookmakers b SET is_active = EXISTS (
               SELECT 1 FROM odds_snapshots o WHERE o.bookmaker_id = b.id AND o.observed_at > now() - make_interval(hours => %s))""",
        (stale_hours,))
    r = conn.execute("SELECT count(*) FILTER (WHERE is_active) AS a, count(*) FILTER (WHERE NOT is_active) AS i FROM bookmakers").fetchone()
    return r["a"], r["i"]


def admin_collectors(conn, known: list[str] | None = None) -> pd.DataFrame:
    """Je Collector (Quelle): eingeschaltet, letzter Lauf, Erfolg, Fehler, Läufe der letzten 24 h."""
    df = _df(conn, """
        WITH last AS (
            SELECT DISTINCT ON (source) source, started_at, finished_at, ok, events, snapshots, error
            FROM collector_runs ORDER BY source, started_at DESC
        ), day AS (
            SELECT source, count(*) AS runs_24h, count(*) FILTER (WHERE ok) AS ok_24h
            FROM collector_runs WHERE started_at > now() - interval '24 hours' GROUP BY source
        ), names AS (
            SELECT source FROM last UNION SELECT source FROM collector_settings UNION SELECT unnest(%s::text[])
        )
        SELECT n.source, coalesce(c.enabled, TRUE) AS enabled, l.started_at AS last_run, l.ok AS last_ok,
               l.events AS last_events, l.snapshots AS last_snapshots, l.error AS last_error,
               coalesce(d.runs_24h, 0) AS runs_24h, coalesce(d.ok_24h, 0) AS ok_24h
        FROM names n LEFT JOIN last l ON l.source = n.source LEFT JOIN day d ON d.source = n.source
        LEFT JOIN collector_settings c ON c.source = n.source
        WHERE n.source <> 'demo' ORDER BY n.source""", (list(known or []),))
    return df


def set_collector_enabled(conn, source: str, enabled: bool) -> None:
    conn.execute(
        """INSERT INTO collector_settings (source, enabled, updated_at) VALUES (%s, %s, now())
           ON CONFLICT (source) DO UPDATE SET enabled = excluded.enabled, updated_at = now()""", (source, enabled))
