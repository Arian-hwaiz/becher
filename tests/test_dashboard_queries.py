"""Dashboard-Abfragen gegen eine echte Datenbank (nur mit BECHER_TEST_DATABASE_URL)."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from collectors.odds_api import parse_events
from common import db
from dashboard import queries as q
from engine.scan import run_scan

URL = os.environ.get("BECHER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")
FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_sample.json"


def test_queries_run_and_have_expected_columns():
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        store = db.Store(conn)
        now = datetime.now(timezone.utc)
        events = parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")), "soccer_germany_bundesliga")
        store.save_events(events, observed_at=now)
        store.log_run("odds_api", now, True, len(events), 10)
        run_scan(conn, now=now)

        s = q.summary(conn)
        assert s["events_upcoming"] >= 2 and s["snapshots_1h"] > 0 and s["last_run"]["source"] == "odds_api"
        assert set(q.snapshots_per_hour(conn).columns) == {"hour", "source", "n"}
        cov = q.coverage(conn)
        assert {"name", "kind", "n", "last_seen"} <= set(cov.columns)
        ev = q.upcoming_events(conn)
        assert {"id", "home_name", "away_name", "start_time", "league"} <= set(ev.columns)
        mk = q.event_markets(conn, int(ev.iloc[0]["id"]))
        assert not mk.empty
        odds = q.market_latest_odds(conn, int(mk.iloc[0]["id"]))
        assert {"bookmaker", "outcome", "price"} <= set(odds.columns)
        assert not q.market_history(conn, int(mk.iloc[0]["id"])).empty
        assert not q.runs(conn).empty
        opps = q.opportunities(conn)
        assert opps.empty or {"kind", "ev_conservative", "home_name"} <= set(opps.columns)
        conn.rollback()
