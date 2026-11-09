from datetime import datetime, timedelta, timezone

import pytest

from engine import clv
from engine.notify import format_opportunity
from engine.scan import Opportunity

T0 = datetime(2026, 11, 14, 14, 30, tzinfo=timezone.utc)


def test_select_closing_takes_last_before_kickoff_only():
    snaps = [
        clv.Snap(1, "home", 1.80, T0 - timedelta(hours=3)),
        clv.Snap(1, "home", 1.85, T0 - timedelta(minutes=5)),     # Schlussquote
        clv.Snap(1, "home", 1.95, T0 + timedelta(minutes=10)),    # nach Anpfiff: ignorieren
        clv.Snap(1, "away", 4.20, T0 - timedelta(minutes=7)),
        clv.Snap(2, "home", 1.70, T0 - timedelta(hours=9)),       # zu alt
    ]
    out = {(s.bookmaker_id, s.outcome): s.price for s in clv.select_closing(snaps, T0)}
    assert out == {(1, "home"): 1.85, (1, "away"): 4.20}


def test_clv_against_fair_closing():
    # Pinnacle schließt 1.85 / 3.60 / 4.60; eigene Wette Heim @ 2.05
    fair = clv.fair_closing_price([1.85, 3.60, 4.60], 0, "multiplicative")
    assert fair > 1.85                      # Marge raus → faire Quote höher als Pinnacle-Quote
    assert clv.clv_percent(2.05, fair) > 0
    assert clv.clv_percent(1.80, fair) < 0
    assert clv.clv_percent(fair, fair) == pytest.approx(0.0)


def test_settle():
    assert clv.settle(100, 2.0, "won") == 200
    assert clv.settle(100, 2.0, "lost") == 0
    assert clv.settle(100, 2.0, "void") == 100
    assert clv.settle(100, 2.0, "half_won") == 150
    assert clv.settle(100, 2.0, "half_lost") == 50
    with pytest.raises(ValueError):
        clv.settle(1, 2.0, "unknown")


def test_format_opportunity_value_and_arb():
    names = {3: "Tipico", 4: "bwin"}
    v = Opportunity("value", 7, 3, "home", 2.45, 2.1, 0.08, 0.031, "power", 20, {"references": ["pinnacle"]})
    txt = format_opportunity(v, names, {"home_name": "A", "away_name": "B", "league": "L", "start_time": "10.11. 20:00", "market": "h2h"})
    assert "Valuebet 3.10 %" in txt and "Tipico" in txt and "home @ 2.45" in txt and "A – B" in txt
    a = Opportunity("arb", 7, None, None, None, None, 0.02, 0.02, "best_price", None,
                    {"percent": 2.0, "legs": [{"bookmaker_id": 3, "outcome": "over", "price": 2.1, "stake": 0.5},
                                              {"bookmaker_id": 4, "outcome": "under", "price": 2.1, "stake": 0.5}]})
    txt = format_opportunity(a, names)
    assert "Surebet 2.00 %" in txt and "bwin: under @ 2.1" in txt


# ---------------------------------------------------------------- Datenbank-Rundlauf (nur mit BECHER_TEST_DATABASE_URL)

import os  # noqa: E402

URL = os.environ.get("BECHER_TEST_DATABASE_URL")


@pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")
def test_closing_odds_and_clv_roundtrip():
    from common import db
    from dashboard import queries as q

    with db.connect(URL) as conn:
        db.apply_schema(conn)
        start = datetime.now(timezone.utc) - timedelta(hours=1)         # Event hat vor 1 h begonnen
        sport = conn.execute("SELECT id FROM sports WHERE key='soccer'").fetchone()["id"]
        league = conn.execute(
            "INSERT INTO leagues (sport_id, key, name) VALUES (%s, 'test_clv_league', 'Test-CLV') "
            "ON CONFLICT (key) DO UPDATE SET name=excluded.name RETURNING id", (sport,)).fetchone()["id"]
        ev = conn.execute(
            "INSERT INTO events (league_id, home_name, away_name, start_time) VALUES (%s, 'CLV Heim', 'CLV Gast', %s) RETURNING id",
            (league, start)).fetchone()["id"]
        mk = conn.execute("INSERT INTO markets (event_id, type) VALUES (%s, 'h2h') RETURNING id", (ev,)).fetchone()["id"]
        sharp = conn.execute("SELECT id FROM bookmakers WHERE kind='sharp' ORDER BY id LIMIT 1").fetchone()["id"]
        soft = conn.execute("SELECT id FROM bookmakers WHERE kind='soft' ORDER BY id LIMIT 1").fetchone()["id"]
        snaps = []
        for mins, prices in ((180, (1.90, 3.50, 4.40)), (5, (1.85, 3.60, 4.60))):
            t = start - timedelta(minutes=mins)
            for oc, p in zip(("home", "draw", "away"), prices):
                snaps.append((mk, sharp, oc, p, t, "test"))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO odds_snapshots (market_id, bookmaker_id, outcome, price, observed_at, source) VALUES (%s,%s,%s,%s,%s,%s)", snaps)
        bet_id = q.add_bet(conn, soft, "home", 10.0, 2.05, mk, None, "Test")

        assert clv.capture_closing_odds(conn) >= 3
        closing = {r["outcome"]: float(r["price"]) for r in conn.execute(
            "SELECT outcome, price FROM closing_odds WHERE market_id=%s", (mk,)).fetchall()}
        assert closing == {"home": 1.85, "draw": 3.60, "away": 4.60}       # die letzten vor Anstoß
        assert clv.update_bets_clv(conn) >= 1
        row = conn.execute("SELECT clv, result FROM bets WHERE id=%s", (bet_id,)).fetchone()
        assert row["clv"] is not None and float(row["clv"]) > 0 and row["result"] == "open"

        q.settle_bet(conn, bet_id, "won", clv.settle(10.0, 2.05, "won"))
        stats = q.bet_stats(conn)
        assert stats["n"] >= 1 and stats["n_clv"] >= 1
        assert not q.bets(conn).empty and not q.clv_by_bookmaker(conn).empty
        conn.execute("DELETE FROM bets WHERE id=%s", (bet_id,))
        conn.execute("DELETE FROM events WHERE id=%s", (ev,))   # räumt Markt, Quoten, Schlussquoten per CASCADE
