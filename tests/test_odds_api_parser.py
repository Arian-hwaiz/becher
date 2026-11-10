import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from collectors.odds_api import parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "odds_api_sample.json"


def load():
    return parse_events(json.loads(FIXTURE.read_text(encoding="utf-8")), "soccer_germany_bundesliga")


def test_events_and_teams():
    events = load()
    assert len(events) == 2
    ev = events[0]
    assert ev.source == "odds_api"
    assert ev.source_id == "a1b2c3d4e5f60718"
    assert ev.sport_key == "soccer"
    assert ev.home_name == "Bayern Munich" and ev.away_name == "SC Freiburg"
    assert ev.start_time == datetime(2026, 11, 14, 14, 30, tzinfo=timezone.utc)


def test_markets_are_merged_across_bookmakers():
    ev = load()[0]
    by_key = {(m.type, m.line): m for m in ev.markets}
    assert set(by_key) == {("h2h", None), ("totals", Decimal("3.5")), ("spreads", Decimal("-1.5"))}
    h2h = by_key[("h2h", None)]
    # 3 Buchmacher x 3 Ausgänge
    assert len(h2h.quotes) == 9
    pin = {q.outcome: q.price for q in h2h.quotes if q.bookmaker_source_key == "pinnacle"}
    assert pin == {"home": Decimal("1.36"), "away": Decimal("8.90"), "draw": Decimal("5.60")}


def test_totals_outcomes_and_line():
    ev = load()[0]
    tot = next(m for m in ev.markets if m.type == "totals")
    tip = {q.outcome: q.price for q in tot.quotes if q.bookmaker_source_key == "tipico_de"}
    assert tip == {"over": Decimal("1.75"), "under": Decimal("2.05")}


def test_spread_line_is_from_home_perspective():
    ev = load()[0]
    spr = next(m for m in ev.markets if m.type == "spreads")
    assert spr.line == Decimal("-1.5")
    assert {q.outcome for q in spr.quotes} == {"home", "away"}


def test_source_timestamp_parsed():
    ev = load()[0]
    q = next(q for m in ev.markets for q in m.quotes if q.bookmaker_source_key == "pinnacle")
    assert q.source_ts == datetime(2026, 11, 9, 18, 50, 12, tzinfo=timezone.utc)


def test_quote_count():
    events = load()
    assert events[0].quote_count == 9 + 4 + 2
    assert events[1].quote_count == 3


def test_collector_stops_below_credit_reserve(monkeypatch):
    import httpx

    from collectors.odds_api import OddsApiCollector
    from common.config import settings

    monkeypatch.setattr(settings, "odds_api_min_remaining", 20)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json=[], headers={"x-requests-remaining": "21"})

    c = OddsApiCollector(api_key="x", sports=["a", "b", "c"], regions="eu", markets="h2h,totals",
                         client=httpx.Client(transport=httpx.MockTransport(handler)))
    c.fetch()
    # Erste Abfrage läuft (Rest unbekannt), danach 21 − 2 < 20 → die weiteren werden übersprungen
    assert len(calls) == 1 and c.remaining == 21
