"""Administration: Anbieterliste, Schalter, Collector-Schalter (nur mit BECHER_TEST_DATABASE_URL)."""
import os
from datetime import datetime, timedelta, timezone

import pytest

from common import db
from dashboard import queries as q

URL = os.environ.get("BECHER_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BECHER_TEST_DATABASE_URL nicht gesetzt")


def test_admin_bookmakers_columns_and_toggles():
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        df = q.admin_bookmakers(conn)
        assert {"id", "name", "kind", "is_active", "scraper_status", "sources", "last_seen", "quotes_24h", "data_state"} <= set(df.columns)
        assert set(df["data_state"]) <= {"frisch", "alt", "veraltet", "keine"}
        row = df[df["key"] == "tipico"].iloc[0]
        bid, was_active, was_status, was_note = int(row["id"]), bool(row["is_active"]), row["scraper_status"], row["scraper_note"]
        try:
            q.set_bookmaker_active(conn, bid, False)
            q.set_bookmaker_scraper(conn, bid, "blockiert", "Cloudflare")
            after = q.admin_bookmakers(conn).set_index("id").loc[bid]
            assert not after["is_active"] and after["scraper_status"] == "blockiert" and after["scraper_note"] == "Cloudflare"
            from engine.scan import load_bookmakers
            assert bid not in load_bookmakers(conn)          # inaktiv → vom Scan ignoriert
            with pytest.raises(ValueError):
                q.set_bookmaker_scraper(conn, bid, "quatsch", None)
        finally:
            q.set_bookmaker_active(conn, bid, was_active)
            q.set_bookmaker_scraper(conn, bid, was_status, was_note)


def test_activate_only_with_data_and_collector_switch():
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        before = {r["id"]: r["is_active"] for r in conn.execute("SELECT id, is_active FROM bookmakers").fetchall()}
        try:
            n_on, n_off = q.activate_only_with_data(conn, stale_hours=48)
            assert n_on + n_off == len(before)
            fresh = {r["bookmaker_id"] for r in conn.execute(
                "SELECT DISTINCT bookmaker_id FROM odds_snapshots WHERE observed_at > now() - interval '48 hours'").fetchall()}
            active = {r["id"] for r in conn.execute("SELECT id FROM bookmakers WHERE is_active").fetchall()}
            assert active == fresh & set(before)

            assert db.collector_enabled(conn, "test_src_admin") is True      # ohne Eintrag: an
            q.set_collector_enabled(conn, "test_src_admin", False)
            assert db.collector_enabled(conn, "test_src_admin") is False
            cols = q.admin_collectors(conn, ["odds_api", "betfair"])
            assert {"odds_api", "betfair", "test_src_admin"} <= set(cols["source"])
            assert not cols.set_index("source").loc["test_src_admin", "enabled"]
        finally:
            for bid, act in before.items():
                conn.execute("UPDATE bookmakers SET is_active=%s WHERE id=%s", (act, bid))
            conn.execute("DELETE FROM collector_settings WHERE source='test_src_admin'")


def test_events_overview_per_bookmaker():
    """Seite „Spiele“: Liste aller Spiele, gesamt und je Anbieter, mit dessen 1X2-Quoten und Direkt-Link."""
    now = datetime.now(timezone.utc)
    with db.connect(URL) as conn:
        db.apply_schema(conn)
        ids = {r["key"]: r["id"] for r in conn.execute("SELECT key, id FROM bookmakers WHERE key IN ('admiral','bwin')").fetchall()}
        sport = conn.execute("SELECT id FROM sports WHERE key='soccer'").fetchone()["id"]
        league = conn.execute("INSERT INTO leagues (sport_id, key, name) VALUES (%s, 'test_spiele', 'Testliga Spiele') "
                              "ON CONFLICT DO NOTHING RETURNING id", (sport,)).fetchone()
        league = league["id"] if league else conn.execute("SELECT id FROM leagues WHERE key='test_spiele'").fetchone()["id"]
        ev = conn.execute("INSERT INTO events (league_id, home_name, away_name, start_time) VALUES (%s,'Heim Test','Gast Test',%s) RETURNING id",
                          (league, now + timedelta(days=1))).fetchone()["id"]
        try:
            mk = conn.execute("INSERT INTO markets (event_id, type) VALUES (%s,'h2h') RETURNING id", (ev,)).fetchone()["id"]
            rows = [("admiral", "home", 2.10, 10), ("admiral", "home", 2.20, 1), ("admiral", "draw", 3.4, 1), ("admiral", "away", 3.3, 1),
                    ("bwin", "home", 2.30, 1)]
            for key, outcome, price, age in rows:
                conn.execute("INSERT INTO odds_snapshots (observed_at, market_id, bookmaker_id, outcome, price, source) VALUES (%s,%s,%s,%s,%s,'test')",
                             (now - timedelta(minutes=age), mk, ids[key], outcome, price))
            conn.execute("INSERT INTO event_links (event_id, bookmaker_id, url) VALUES (%s,%s,'https://example.test/spiel')", (ev, ids["admiral"]))

            one = q.events_overview(conn, ids["admiral"]).set_index("id").loc[ev]
            assert (one["p1"], one["px"], one["p2"]) == (2.20, 3.4, 3.3)      # jeweils die neueste Quote des Anbieters
            assert one["quotes"] == 3 and one["markets"] == 1 and one["n_bookmakers"] == 2
            assert one["link"] == "https://example.test/spiel"
            everyone = q.events_overview(conn).set_index("id").loc[ev]
            assert everyone["p1"] == 2.30 and everyone["quotes"] == 4 and everyone["bookmakers"] == "ADMIRAL, bwin"
            only_bwin = q.events_overview(conn, ids["bwin"]).set_index("id").loc[ev]
            assert only_bwin["quotes"] == 1 and only_bwin["link"] is None
            with_data = q.bookmakers_with_events(conn).set_index("id")
            assert with_data.loc[ids["admiral"], "events"] >= 1 and ids["bwin"] in with_data.index
        finally:
            conn.execute("DELETE FROM odds_snapshots WHERE source='test' AND market_id IN (SELECT id FROM markets WHERE event_id=%s)", (ev,))
            conn.execute("DELETE FROM events WHERE id=%s", (ev,))
            conn.execute("DELETE FROM leagues WHERE key='test_spiele'")
            conn.commit()
