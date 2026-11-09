import pytest

from engine import devig as dv
from engine import valuebet as vb

PINNACLE_1X2 = [2.05, 3.60, 3.75]   # Overround ~ 2,2 %


@pytest.mark.parametrize("method", sorted(dv.METHODS))
def test_all_methods_sum_to_one_and_keep_order(method):
    p = dv.devig(PINNACLE_1X2, method)
    assert sum(p) == pytest.approx(1.0, abs=1e-9)
    assert p[0] > p[1] > p[2]
    assert all(0 < x < 1 for x in p)


def test_multiplicative_matches_closed_form():
    q = [1 / x for x in PINNACLE_1X2]
    s = sum(q)
    assert dv.multiplicative(PINNACLE_1X2) == pytest.approx([x / s for x in q])
    assert dv.overround(PINNACLE_1X2) == pytest.approx(s - 1)


def test_power_and_shin_favour_favourite_vs_multiplicative():
    mult = dv.multiplicative(PINNACLE_1X2)
    for m in ("power", "shin"):
        p = dv.devig(PINNACLE_1X2, m)
        # Außenseiter bekommt weniger, Favorit mehr Wahrscheinlichkeit als multiplikativ
        assert p[0] > mult[0]
        assert p[2] < mult[2]


def test_fair_market_unchanged():
    fair = [2.0, 2.0]
    for m in dv.METHODS:
        assert dv.devig(fair, m) == pytest.approx([0.5, 0.5], abs=1e-9)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        dv.devig([1.0, 2.0])
    with pytest.raises(ValueError):
        dv.devig([2.0, 2.0], "foo")


def test_consensus_weights_and_filters():
    a = dv.Reference("pinnacle", [2.0, 2.0], weight=2.0, age_s=10)
    b = dv.Reference("betfair", [1.8, 2.3], weight=1.0, age_s=5, liquidity=100)
    p = dv.consensus([a, b])
    pb = dv.multiplicative(b.prices)
    assert p[0] == pytest.approx((2 * 0.5 + 1 * pb[0]) / 3)
    # Betfair zu illiquide → nur Pinnacle
    assert dv.consensus([a, b], min_liquidity=1000) == pytest.approx([0.5, 0.5])
    # alles zu alt → Fehler
    with pytest.raises(ValueError):
        dv.consensus([a, b], max_age_s=1)


def test_evaluate_value_bet_with_german_tax():
    # Soft-Buchmacher 2.20 auf Heim, Pinnacle 2.05/3.60/3.75
    refs = [dv.Reference("pinnacle", PINNACLE_1X2, age_s=20)]
    e = vb.evaluate(0, [2.20, 3.40, 3.30], refs, method="multiplicative",
                    tax_rate=0.053, tax_mode="on_stake")
    assert e.price_effective == pytest.approx(2.20 * (1 - 0.053))
    assert e.fair_prob == pytest.approx(dv.multiplicative(PINNACLE_1X2)[0])
    assert e.ev == pytest.approx(e.fair_prob * e.price_effective - 1)
    assert e.ev_conservative < e.ev
    assert e.reference_age_s == 20
    assert e.kelly_fraction >= 0


def test_conservative_ev_grows_with_age_and_thin_market():
    refs_fresh = [dv.Reference("pinnacle", PINNACLE_1X2, age_s=0)]
    refs_old = [dv.Reference("pinnacle", PINNACLE_1X2, age_s=500)]
    fresh = vb.evaluate(0, [2.30, 3.4, 3.3], refs_fresh)
    old = vb.evaluate(0, [2.30, 3.4, 3.3], refs_old)
    assert fresh.ev == pytest.approx(old.ev)
    assert old.ev_conservative < fresh.ev_conservative
    thin = vb.evaluate(0, [2.30, 3.4, 3.3], refs_fresh, n_effective=50)
    assert thin.ev_conservative < fresh.ev_conservative


def test_no_value_gives_zero_kelly_and_not_bet():
    refs = [dv.Reference("pinnacle", PINNACLE_1X2)]
    e = vb.evaluate(0, [1.90, 3.4, 3.3], refs)
    assert e.ev < 0
    assert not e.is_bet
    assert e.kelly_fraction == 0.0


def test_betburger_style_percent_reproduces_observed_value():
    assert vb.betburger_style_percent(2.35, 1.7990887) == pytest.approx(1.898, abs=0.001)
    assert vb.betburger_style_percent(2.30, 1.901) == pytest.approx(4.078, abs=0.001)
