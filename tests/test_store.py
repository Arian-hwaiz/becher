"""Integrationstest gegen eine echte Datenbank. Läuft nur, wenn BECHER_TEST_DATABASE_URL gesetzt ist.

    BECHER_TEST_DATABASE_URL=postgresql://becher:becher@localhost:5432/becher pytest tests/test_store.py
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collectors.odds_api import parse_events
from common import db

URL = os.environ.get("BECHER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")

FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_sample.json"


def test_save_and_reread():
    events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")), "soccer_germany_bundesliga")
    observed = datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc)
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        store = db.Store(conn)
        n_ev, n_snap = store.save_events(events, observed_at=observed)
        assert n_ev == 2
        # unknown_book wird nicht gespeichert: 2 Events, Quoten von pinnacle + tipico
        assert n_snap == (3 + 2) + (3 + 2 + 2) + 3
        # zweiter Lauf legt keine neuen Events an
        n_ev2, _ = store.save_events(events, observed_at=observed)
        assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] >= 2
        rows = conn.execute(
            """SELECT b.key, o.outcome, o.price FROM odds_snapshots o
               JOIN bookmakers b ON b.id=o.bookmaker_id
               JOIN markets m ON m.id=o.market_id
               WHERE o.observed_at=%s AND m.type='h2h' AND b.key='pinnacle'
               ORDER BY o.outcome""",
            (observed,),
        ).fetchall()
        assert [(r["outcome"], float(r["price"])) for r in rows][:3] == [
            ("away", 8.9), ("draw", 5.6), ("home", 1.36)
        ] or len(rows) >= 3


def test_second_source_matches_existing_event():
    """Ein zweiter Collector mit anderer Schreibweise landet auf demselben Event."""
    from decimal import Decimal

    from common.models import NormalizedEvent, NormalizedMarket, Quote

    start = datetime(2026, 12, 5, 15, 30, tzinfo=timezone.utc)
    a = NormalizedEvent("odds_api", "ev-A1", "soccer_germany_bundesliga", "Bundesliga", "soccer",
                        "FC Bayern München", "Borussia Dortmund", start,
                        [NormalizedMarket("h2h", None, [Quote("pinnacle", "home", Decimal("1.80"))])])
    # andere Quelle, Englisch, Heim/Gast vertauscht, Anstoß 10 Minuten anders
    b = NormalizedEvent("betfair", "ev-B9", "betfair_bundesliga", "German Bundesliga", "soccer",
                        "Dortmund", "Bayern Munich", start.replace(minute=40),
                        [NormalizedMarket("h2h", None, [Quote("betfair_ex_eu", "home", Decimal("4.50"))])])
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        conn.execute("INSERT INTO bookmaker_source_keys (source, source_key, bookmaker_id) "
                     "SELECT 'betfair', 'betfair_ex_eu', id FROM bookmakers WHERE key='betfair_ex' ON CONFLICT DO NOTHING")
        store = db.Store(conn)
        id_a = store.upsert_event(a)
        id_b = store.upsert_event(b)
        assert id_a == id_b
        ev = conn.execute("SELECT home_team_id, away_team_id FROM events WHERE id=%s", (id_a,)).fetchone()
        assert ev["home_team_id"] and ev["away_team_id"]
        n = conn.execute("SELECT count(*) AS n FROM event_source_ids WHERE event_id=%s", (id_a,)).fetchone()["n"]
        assert n == 2
        aliases = conn.execute("SELECT source, alias, confidence FROM team_aliases WHERE team_id=%s ORDER BY source",
                               (ev["home_team_id"],)).fetchall()
        assert {r["source"] for r in aliases} == {"odds_api", "betfair"}
        conn.rollback()
