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
