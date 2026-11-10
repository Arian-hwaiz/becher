import random
from datetime import datetime, timedelta, timezone

from engine import account_health as ah
from engine import method_eval as me

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def _bets(n, seed=1):
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        # Referenz schließt mit 5 % Marge; „Wahrheit“ ist die multiplikativ devigged Wahrscheinlichkeit
        p_home = rnd.uniform(0.3, 0.7)
        probs = [p_home, 0.25, 1 - p_home - 0.25]
        closing = {oc: round(1 / (p * 1.05), 3) for oc, p in zip(("home", "draw", "away"), probs)}
        won = rnd.random() < p_home
        out.append(me.SettledBet("h2h", "home", closing["home"] * 1.04, "won" if won else "lost", closing))
    return out


def test_score_methods_marks_one_recommendation_with_enough_bets():
    scores = me.score_methods(_bets(200))
    assert {s.method for s in scores} == set(me.score_methods.__defaults__[0])
    assert sum(s.recommended for s in scores) == 1
    best = next(s for s in scores if s.recommended)
    assert best.market_type == "h2h" and 0 < best.brier < 0.3 and best.avg_clv > 0
    assert me.recommendations(scores) == {"h2h": best.method}


def test_no_recommendation_below_min_bets_and_void_ignored():
    few = _bets(10) + [me.SettledBet("h2h", "home", 2.0, "void", {"home": 2.0, "away": 2.0})]
    scores = me.score_methods(few)
    assert all(not s.recommended for s in scores) and all(s.n == 10 for s in scores)


def _row(bm, i, stake, price=2.0, fair=None, clv=None, result="won"):
    payout = stake * price if result == "won" else 0.0
    return ah.BetRow(bm, T0 + timedelta(hours=i), stake, price, fair, result, payout if result != "open" else None, clv)


def test_account_health_flags_arber_profile_and_calm_profile():
    arber = [_row("bwin", i, 37.42, 2.1, 1.9, clv=5.0, result="won" if i % 2 else "lost") for i in range(40)]
    calm = [_row("Tipico", i * 48, 10.0, 1.5, None, clv=0.5, result="lost") for i in range(12)]
    out = {h.bookmaker: h for h in ah.assess(arber + calm)}
    assert out["bwin"].level == "hoch" and out["bwin"].score >= 60 and out["bwin"].tips
    assert any("krumme" in r for r in out["bwin"].reasons) and any("CLV" in r for r in out["bwin"].reasons)
    assert out["Tipico"].level == "niedrig" and out["Tipico"].odd_stakes_pct == 0
    assert out["bwin"].bets_per_active_day > 8
