from datetime import datetime, timedelta, timezone

from engine.scan import Bookmaker, OddsRow, ScanConfig, scan_market

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
BOOKS = {
    1: Bookmaker(1, "pinnacle", "sharp"),
    2: Bookmaker(2, "betfair_ex", "exchange", commission=0.05),
    3: Bookmaker(3, "tipico", "soft", tax_rate=0.053, tax_mode="on_stake"),
    4: Bookmaker(4, "bet365", "soft", tax_rate=0.053, tax_mode="on_stake"),
}


def rows(spec, age_s=10):
    """spec: {bookmaker_id: {outcome: price}}"""
    t = NOW - timedelta(seconds=age_s)
    return [OddsRow(bid, oc, p, t, t) for bid, q in spec.items() for oc, p in q.items()]


def test_value_bet_found_against_sharp_reference():
    odds = rows({
        1: {"home": 2.05, "draw": 3.60, "away": 3.75},   # Pinnacle
        3: {"home": 2.45, "draw": 3.30, "away": 3.20},   # Tipico: Heim deutlich zu hoch
    })
    out = scan_market(7, "h2h", odds, BOOKS, NOW, ScanConfig(method="multiplicative", max_age_s=120))
    values = [o for o in out if o.kind == "value"]
    assert len(values) == 1
    v = values[0]
    assert v.bookmaker_id == 3 and v.outcome == "home" and v.price == 2.45
    assert v.ev > v.ev_conservative > 0
    assert v.reference_age_s == 10
    assert v.details["references"] == ["pinnacle"]
    # Steuer ist eingerechnet
    assert v.details["price_effective"] == round(2.45 * (1 - 0.053), 4)


def test_no_reference_no_value_but_arb_possible():
    odds = rows({
        3: {"over": 2.05, "under": 1.80},
        4: {"over": 1.75, "under": 2.05},
    })
    # ohne Steuer wäre 2.05/2.05 eine Surebet (2,4 %); mit 5,3 % Steuer nicht mehr
    out = scan_market(1, "totals", odds, BOOKS, NOW)
    assert all(o.kind != "value" for o in out)
    assert out == []
    no_tax = {3: Bookmaker(3, "a", "soft"), 4: Bookmaker(4, "b", "soft")}
    out = scan_market(1, "totals", odds, no_tax, NOW)
    arbs = [o for o in out if o.kind == "arb"]
    assert len(arbs) == 1
    legs = arbs[0].details["legs"]
    assert {l["outcome"]: l["bookmaker_id"] for l in legs} == {"over": 3, "under": 4}
    assert sum(l["stake"] for l in legs) == pytest_approx(1.0)


def pytest_approx(x):
    import pytest
    return pytest.approx(x, abs=1e-6)


def test_stale_quotes_are_ignored():
    odds = rows({1: {"home": 2.05, "draw": 3.60, "away": 3.75}}, age_s=5000) + \
        rows({3: {"home": 2.45, "draw": 3.30, "away": 3.20}}, age_s=5)
    out = scan_market(7, "h2h", odds, BOOKS, NOW, ScanConfig(max_age_s=600))
    assert out == []


def test_exchange_reference_requires_liquidity():
    t = NOW - timedelta(seconds=5)
    thin = [OddsRow(2, "home", 2.1, t, t, liquidity=100), OddsRow(2, "away", 2.0, t, t, liquidity=100)]
    soft = rows({3: {"home": 2.4, "away": 1.7}})
    assert all(o.kind != "value" for o in scan_market(3, "spreads", thin + soft, BOOKS, NOW))
    deep = [OddsRow(2, "home", 2.1, t, t, liquidity=5000), OddsRow(2, "away", 2.0, t, t, liquidity=5000)]
    out = scan_market(3, "spreads", deep + soft, BOOKS, NOW, ScanConfig(method="multiplicative"))
    assert any(o.kind == "value" and o.outcome == "home" for o in out)


def test_two_way_h2h_without_draw():
    odds = rows({1: {"home": 1.90, "away": 2.00}, 3: {"home": 2.25, "away": 1.75}})
    out = scan_market(9, "h2h", odds, BOOKS, NOW, ScanConfig(method="multiplicative"))
    assert any(o.kind == "value" and o.outcome == "home" for o in out)
