import json
from decimal import Decimal
from pathlib import Path

from collectors.betfair import parse_markets

FIX = json.loads((Path(__file__).parent / "fixtures" / "betfair_sample.json").read_text(encoding="utf-8"))


def events():
    return {e.source_id: e for e in parse_markets(FIX["catalogue"], FIX["books"])}


def test_match_odds_with_draw_and_lay():
    ev = events()["33000001"]
    assert ev.source == "betfair" and ev.sport_key == "soccer"
    assert ev.home_name == "Bayern Munich" and ev.away_name == "SC Freiburg"
    assert ev.league_name == "German Bundesliga"
    h2h = next(m for m in ev.markets if m.type == "h2h")
    by = {q.outcome: q for q in h2h.quotes}
    assert set(by) == {"home", "draw", "away"}
    assert by["home"].price == Decimal("1.37") and by["home"].lay_price == Decimal("1.38")
    assert by["home"].liquidity == Decimal("125430.5")
    assert by["home"].source_ts is not None
    assert by["home"].bookmaker_source_key == "betfair_ex"


def test_totals_line_and_outcomes():
    ev = events()["33000001"]
    tot = next(m for m in ev.markets if m.type == "totals")
    assert tot.line == Decimal("2.5")
    by = {q.outcome: q.price for q in tot.quotes}
    assert by == {"over": Decimal("1.74"), "under": Decimal("2.3")}


def test_asian_handicap_from_home_perspective():
    ev = events()["33000001"]
    sp = next(m for m in ev.markets if m.type == "spreads")
    assert sp.line == Decimal("-1.5")
    by = {q.outcome: q.price for q in sp.quotes}
    assert by == {"home": Decimal("2.02"), "away": Decimal("1.9")}
    # ohne totalMatched würde die Größe des besten Angebots als Liquidität dienen
    assert all(q.liquidity == Decimal("3100.0") for q in sp.quotes)


def test_removed_runner_and_empty_market_fallbacks():
    ev = events()["33000002"]
    h2h = ev.markets[0]
    assert [q.outcome for q in h2h.quotes] == ["home"]        # Alcaraz REMOVED
    assert h2h.quotes[0].liquidity == Decimal("20")           # totalMatched 0 → Größe des Angebots
    assert h2h.quotes[0].lay_price is None
