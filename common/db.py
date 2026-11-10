"""Datenbankzugriff: Verbindung, Schema einspielen, Events und Quoten speichern."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from common.config import settings
from common.models import NormalizedEvent
from engine.matching import EventKey, Team, TeamMatcher, find_event, normalize_name

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "infra" / "schema.sql"


@contextmanager
def connect(url: str | None = None) -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(url or settings.database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def collector_enabled(conn, source: str) -> bool:
    """Ist der Collector in der Administration eingeschaltet? Ohne Eintrag: ja."""
    row = conn.execute("SELECT enabled FROM collector_settings WHERE source=%s", (source,)).fetchone()
    return True if row is None else bool(row["enabled"])


class Store:
    """Schreibt normalisierte Events in die Datenbank. Cacht Nachschlage-IDs pro Lauf."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        self._bookmaker_by_source_key: dict[tuple[str, str], int] = {}
        self._league_ids: dict[str, int] = {}
        self._sport_ids: dict[str, int] = {}
        self._unknown_bookmakers: set[str] = set()
        self._matchers: dict[int, TeamMatcher] = {}
        self.match_tolerance = timedelta(hours=2)

    # ---- Nachschlagen ---------------------------------------------------

    def bookmaker_id(self, source: str, source_key: str) -> int | None:
        k = (source, source_key)
        if k not in self._bookmaker_by_source_key:
            row = self.conn.execute(
                "SELECT bookmaker_id FROM bookmaker_source_keys WHERE source=%s AND source_key=%s",
                k,
            ).fetchone()
            self._bookmaker_by_source_key[k] = row["bookmaker_id"] if row else None
        bid = self._bookmaker_by_source_key[k]
        if bid is None:
            self._unknown_bookmakers.add(source_key)
        return bid

    def sport_id(self, sport_key: str) -> int:
        if sport_key not in self._sport_ids:
            row = self.conn.execute(
                "INSERT INTO sports (key, name) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET name=sports.name RETURNING id",
                (sport_key, sport_key.capitalize()),
            ).fetchone()
            self._sport_ids[sport_key] = row["id"]
        return self._sport_ids[sport_key]

    def league_id(self, sport_key: str, league_key: str, league_name: str) -> int:
        if league_key not in self._league_ids:
            row = self.conn.execute(
                """INSERT INTO leagues (sport_id, key, name) VALUES (%s, %s, %s)
                   ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name RETURNING id""",
                (self.sport_id(sport_key), league_key, league_name),
            ).fetchone()
            self._league_ids[league_key] = row["id"]
        return self._league_ids[league_key]

    # ---- Team-Matching (Phase 2) ----------------------------------------

    def matcher(self, sport_id: int) -> TeamMatcher:
        """Lädt Teams und Aliase einer Sportart einmal pro Lauf in den Speicher."""
        if sport_id not in self._matchers:
            teams = [
                Team(r["id"], r["name"], normalize_name(r["name"]))
                for r in self.conn.execute("SELECT id, name FROM teams WHERE sport_id=%s", (sport_id,)).fetchall()
            ]
            aliases = {
                (r["source"], r["alias"]): r["team_id"]
                for r in self.conn.execute(
                    "SELECT a.source, a.alias, a.team_id FROM team_aliases a JOIN teams t ON t.id=a.team_id WHERE t.sport_id=%s",
                    (sport_id,),
                ).fetchall()
            }
            self._matchers[sport_id] = TeamMatcher(teams, aliases)
        return self._matchers[sport_id]

    def resolve_team(self, sport_id: int, source: str, raw_name: str) -> int:
        """Ordnet einen Rohnamen einem Team zu; legt bei Bedarf Team und Alias an."""
        m = self.matcher(sport_id)
        res = m.match(source, raw_name)
        if res.team_id is not None:
            if res.method != "alias":
                self.conn.execute(
                    """INSERT INTO team_aliases (team_id, source, alias, confidence) VALUES (%s, %s, %s, %s)
                       ON CONFLICT (source, alias) DO NOTHING""",
                    (res.team_id, source, raw_name, res.confidence),
                )
                m.add_alias(source, raw_name, res.team_id)
                if res.method == "fuzzy":
                    log.info("Fuzzy-Match %r → %r (%.2f)", raw_name, res.candidate, res.confidence)
            return res.team_id
        row = self.conn.execute(
            """INSERT INTO teams (sport_id, name) VALUES (%s, %s)
               ON CONFLICT (sport_id, name) DO UPDATE SET name=EXCLUDED.name RETURNING id""",
            (sport_id, raw_name),
        ).fetchone()
        self.conn.execute(
            """INSERT INTO team_aliases (team_id, source, alias, confidence) VALUES (%s, %s, %s, 1)
               ON CONFLICT (source, alias) DO NOTHING""",
            (row["id"], source, raw_name),
        )
        m.add_team(Team(row["id"], raw_name, normalize_name(raw_name)))
        m.add_alias(source, raw_name, row["id"])
        return row["id"]

    def find_matching_event(self, sport_id: int, home_id: int, away_id: int, start_time: datetime) -> tuple[int | None, bool]:
        """Sucht ein schon bekanntes Event (andere Quelle) mit denselben Teams nahe am Anstoß."""
        rows = self.conn.execute(
            """SELECT e.id, e.home_team_id, e.away_team_id, e.start_time
               FROM events e JOIN leagues l ON l.id=e.league_id
               WHERE l.sport_id=%s AND e.start_time BETWEEN %s AND %s
                 AND (e.home_team_id IN (%s, %s) OR e.away_team_id IN (%s, %s))""",
            (sport_id, start_time - self.match_tolerance, start_time + self.match_tolerance,
             home_id, away_id, home_id, away_id),
        ).fetchall()
        cands = [EventKey(r["id"], r["home_team_id"], r["away_team_id"], r["start_time"]) for r in rows]
        return find_event(home_id, away_id, start_time, cands, self.match_tolerance)

    # ---- Schreiben ------------------------------------------------------

    def upsert_event(self, ev: NormalizedEvent) -> int:
        row = self.conn.execute(
            "SELECT event_id FROM event_source_ids WHERE source=%s AND source_id=%s",
            (ev.source, ev.source_id),
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE events SET start_time=%s WHERE id=%s AND start_time<>%s",
                (ev.start_time, row["event_id"], ev.start_time),
            )
            return row["event_id"]
        league = self.league_id(ev.sport_key, ev.league_key, ev.league_name)
        sport = self.sport_id(ev.sport_key)
        home_id = self.resolve_team(sport, ev.source, ev.home_name)
        away_id = self.resolve_team(sport, ev.source, ev.away_name)
        existing, swapped = self.find_matching_event(sport, home_id, away_id, ev.start_time)
        if existing is not None:
            if swapped:
                log.info("Quelle %s listet Heim/Gast vertauscht: %s - %s", ev.source, ev.home_name, ev.away_name)
            self.conn.execute(
                "INSERT INTO event_source_ids (source, source_id, event_id, swap_teams) VALUES (%s, %s, %s, %s)",
                (ev.source, ev.source_id, existing, swapped),
            )
            return existing
        new = self.conn.execute(
            """INSERT INTO events (league_id, home_team_id, away_team_id, home_name, away_name, start_time)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (league, home_id, away_id, ev.home_name, ev.away_name, ev.start_time),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO event_source_ids (source, source_id, event_id) VALUES (%s, %s, %s)",
            (ev.source, ev.source_id, new["id"]),
        )
        return new["id"]

    def market_id(self, event_id: int, mtype: str, line, period: str) -> int:
        row = self.conn.execute(
            """SELECT id FROM markets WHERE event_id=%s AND type=%s AND line IS NOT DISTINCT FROM %s AND period=%s""",
            (event_id, mtype, line, period),
        ).fetchone()
        if row:
            return row["id"]
        return self.conn.execute(
            "INSERT INTO markets (event_id, type, line, period) VALUES (%s, %s, %s, %s) RETURNING id",
            (event_id, mtype, line, period),
        ).fetchone()["id"]

    def save_events(self, events: list[NormalizedEvent], observed_at: datetime | None = None) -> tuple[int, int]:
        """Speichert Events und alle Quoten. Gibt (Events, Snapshots) zurück."""
        observed_at = observed_at or datetime.now(timezone.utc)
        rows: list[tuple] = []
        for ev in events:
            event_id = self.upsert_event(ev)
            for bm_key, url in ev.links.items():
                bid = self.bookmaker_id(ev.source, bm_key)
                if bid is not None:
                    self.conn.execute(
                        """INSERT INTO event_links (event_id, bookmaker_id, url, updated_at) VALUES (%s, %s, %s, %s)
                           ON CONFLICT (event_id, bookmaker_id) DO UPDATE SET url = excluded.url, updated_at = excluded.updated_at""",
                        (event_id, bid, url, observed_at))
            for m in ev.markets:
                mid = self.market_id(event_id, m.type, m.line, m.period)
                for q in m.quotes:
                    bid = self.bookmaker_id(ev.source, q.bookmaker_source_key)
                    if bid is None:
                        continue
                    rows.append((observed_at, q.source_ts, mid, bid, q.outcome, q.price, ev.source, q.lay_price, q.liquidity))
        if rows:
            with self.conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO odds_snapshots (observed_at, source_ts, market_id, bookmaker_id, outcome, price, source, lay_price, liquidity)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    rows,
                )
        if self._unknown_bookmakers:
            log.info("Unbekannte Buchmacher-Schlüssel (nicht gespeichert): %s", sorted(self._unknown_bookmakers))
        return len(events), len(rows)

    def log_run(self, source: str, started_at: datetime, ok: bool, events: int, snapshots: int, error: str | None = None) -> None:
        self.conn.execute(
            """INSERT INTO collector_runs (source, started_at, finished_at, ok, events, snapshots, error)
               VALUES (%s, %s, now(), %s, %s, %s, %s)""",
            (source, started_at, ok, events, snapshots, error),
        )
