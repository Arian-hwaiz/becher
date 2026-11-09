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
               o.reference_age_s, o.details, b.name AS bookmaker, m.type, m.line, m.period,
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


def latest_opportunities(conn, hours: int = 24, limit: int = 500) -> pd.DataFrame:
    """Wie ``opportunities``, aber je Markt/Buchmacher/Ausgang nur der jüngste Treffer (Scanner-Feed)."""
    df = opportunities(conn, hours, limit * 5)
    if df.empty:
        return df
    key = df[["kind", "event_id", "type", "line", "bookmaker", "outcome"]].fillna("").astype(str).agg("|".join, axis=1)
    df = df.assign(_key=key).sort_values("found_at", ascending=False).drop_duplicates("_key").drop(columns="_key")
    return df.head(limit)
