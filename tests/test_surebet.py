import math

import pytest

from engine import surebet as sb
from engine.surebet import Leg, Result


def test_two_way_margin_matches_closed_form():
    sol = sb.simple([2.10, 2.10])
    assert sol.equalized
    assert sol.stakes == pytest.approx([0.5, 0.5])
    assert sol.percent == pytest.approx(5.0, abs=1e-6)
    assert sb.margin_percent([2.10, 2.10]) == pytest.approx(5.0, abs=1e-6)


def test_three_way_1x2():
    sol = sb.simple([3.6, 3.9, 2.5], ["1", "X", "2"])
    inv = 1 / 3.6 + 1 / 3.9 + 1 / 2.5
    assert sol.percent == pytest.approx((1 / inv - 1) * 100, abs=1e-4)
    assert sum(sol.stakes) == pytest.approx(1.0)
    assert all(p == pytest.approx(sol.payouts[0]) for p in sol.payouts)


def test_no_surebet_gives_negative_percent():
    assert sb.margin_percent([1.9, 1.9]) < 0
    assert sb.simple([1.9, 1.9]).percent < 0


def test_betburger_valuebet_example_is_two_way_margin():
    # AdmiralAT Over 228.5 @ 2.35 gegen Avgline Under 228.5 @ 1.7990887 → 1.898 % bei Betburger
    assert sb.margin_percent([2.35, 1.7990887]) == pytest.approx(1.898, abs=0.001)


def test_push_scenario_draw_no_bet_vs_1x2():
    # Wette A: Heim DNB @ 1.95 (bei Remis Einsatz zurück); Wette B: Gast @ 2.6, Wette C: Remis @ 3.4
    scenarios = ["Heim", "Remis", "Gast"]
    legs = [
        Leg(1.95, (Result.WIN, Result.PUSH, Result.LOSE), "Heim DNB"),
        Leg(3.4, (Result.LOSE, Result.WIN, Result.LOSE), "Remis"),
        Leg(2.6, (Result.LOSE, Result.LOSE, Result.WIN), "Gast"),
    ]
    sol = sb.solve(legs, scenarios)
    assert sol.equalized
    assert all(p == pytest.approx(sol.payouts[0], abs=1e-9) for p in sol.payouts)
    # Rückgabe im Remis-Fall erlaubt kleineren Einsatz auf Remis als bei reinem 1X2
    plain = sb.simple([1.95, 3.4, 2.6])
    assert sol.stakes[1] < plain.stakes[1]


def test_quarter_line_handicap_half_win():
    # Heim -0.25 gewinnt bei Sieg, halber Verlust bei Remis; Gast +0.25 halber Gewinn bei Remis
    legs, names = sb.handicap_legs(2.0, -0.25, 2.0, 0.25, span=1)
    home, away = legs
    idx0 = names.index("diff +0")
    assert home.results[idx0] is Result.HALF_LOSE
    assert away.results[idx0] is Result.HALF_WIN
    sol = sb.solve(legs, names)
    # Symmetrische Quoten: 50/50 und in jedem Szenario gleich → Marge 0 %
    assert sol.stakes == pytest.approx([0.5, 0.5], abs=1e-9)
    assert sol.percent == pytest.approx(0.0, abs=1e-9)


def test_middle_total_lines_has_upside():
    # Über 2.5 @ 2.0 und Unter 3.5 @ 2.0: bei genau 3 Toren gewinnen beide (Middle)
    sol = sb.total(2.0, 2.5, 2.0, 3.5)
    assert not sol.equalized
    assert sol.percent == pytest.approx(0.0, abs=1e-9)        # schlechtester Fall: Geld zurück
    assert sol.max_percent == pytest.approx(100.0, abs=1e-6)  # 3 Tore: beide gewinnen
    assert sol.stakes == pytest.approx([0.5, 0.5], abs=1e-9)


def test_effective_price_tax_and_commission():
    # Deutsche Wettsteuer 5,3 % auf den Einsatz: Quote 2.0 → 1.894
    assert sb.effective_price(2.0, tax_rate=0.053, tax_mode="on_stake") == pytest.approx(1.894)
    # Betfair 5 % auf Nettogewinn: 2.0 → 1.95
    assert sb.effective_price(2.0, commission=0.05) == pytest.approx(1.95)
    assert sb.lay_to_back(2.0) == pytest.approx(2.0)
    assert sb.lay_to_back(1.5) == pytest.approx(3.0)


def test_stakes_for_rounding():
    sol = sb.simple([2.1, 2.1])
    assert sol.stakes_for(100) == [50.0, 50.0]
    sol = sb.simple([1.5, 3.3])
    stakes = sol.stakes_for(100, round_to=1)
    assert sum(stakes) == pytest.approx(100, abs=1.0)
    assert all(float(s).is_integer() for s in stakes)


def test_three_leg_maximin_falls_back_when_not_square():
    # 3 Wetten, 4 Szenarien: kein exakter Ausgleich, Maximin muss trotzdem laufen
    legs = [
        Leg(3.0, (Result.WIN, Result.LOSE, Result.LOSE, Result.LOSE)),
        Leg(3.0, (Result.LOSE, Result.WIN, Result.LOSE, Result.LOSE)),
        Leg(3.0, (Result.LOSE, Result.LOSE, Result.WIN, Result.PUSH)),
    ]
    sol = sb.solve(legs)
    assert math.isclose(sum(sol.stakes), 1.0, abs_tol=1e-9)
    assert sol.percent <= sol.max_percent
