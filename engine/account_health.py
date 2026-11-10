"""Account-Health: Wie auffällig ist mein Wettverhalten je Buchmacher (Limit-Risiko)?

Buchmacher limitieren Konten, die systematisch gewinnen oder wie ein Arber aussehen. Typische
Signale, die aus Branchenerfahrung und der Betburger-Dokumentation bekannt sind:

* hoher CLV über viele Wetten (das Konto schlägt die Schlusslinie),
* viele Wetten auf Fehlerquoten (sehr hoher EV beim Setzen),
* krumme Einsätze (z. B. 37,42 statt 40), die nach Arbitrage-Rechner aussehen,
* Einsätze nahe am Maximum, viele Wetten pro Tag, nur auf Randmärkte/Randligen,
* kein „Freizeit“-Anteil (nie Kombi, nie Favorit, nie Live).

Hier wird daraus je Buchmacher ein Risiko-Score 0–100 mit Gründen und Tipps. Reine Heuristik, keine
Prognose: Sie soll helfen, das Verhalten zu streuen, bevor das Konto eingeschränkt wird.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class BetRow:
    bookmaker: str
    placed_at: datetime
    stake: float
    price: float
    fair_price_at_bet: float | None
    result: str
    payout: float | None
    clv: float | None


@dataclass
class Health:
    bookmaker: str
    bets: int
    score: int                         # 0 = unauffällig, 100 = akut
    level: str                         # niedrig | mittel | hoch
    avg_clv: float | None
    profit: float
    roi_pct: float | None
    odd_stakes_pct: float
    high_ev_pct: float
    bets_per_active_day: float
    reasons: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)


def _is_round(stake: float) -> bool:
    return abs(stake - round(stake)) < 1e-9 and (round(stake) % 5 == 0 or stake < 10)


def assess(rows: Iterable[BetRow], max_stake_hint: float | None = None) -> list[Health]:
    by_bm: dict[str, list[BetRow]] = {}
    for r in rows:
        by_bm.setdefault(r.bookmaker, []).append(r)
    out = []
    for bm, bets in by_bm.items():
        n = len(bets)
        settled = [b for b in bets if b.result != "open"]
        profit = sum((b.payout or 0) - b.stake for b in settled)
        stake_settled = sum(b.stake for b in settled)
        roi = profit / stake_settled * 100 if stake_settled else None
        clvs = [b.clv for b in bets if b.clv is not None]
        avg_clv = sum(clvs) / len(clvs) if clvs else None
        odd = sum(not _is_round(b.stake) for b in bets) / n * 100
        high_ev = sum(1 for b in bets if b.fair_price_at_bet and b.price / b.fair_price_at_bet - 1 >= 0.08) / n * 100
        days = {b.placed_at.date() for b in bets}
        per_day = n / len(days)
        score, reasons, tips = 0, [], []

        if avg_clv is not None and len(clvs) >= 10:
            if avg_clv >= 4:
                score += 35; reasons.append(f"Ø CLV {avg_clv:+.1f} % über {len(clvs)} Wetten: das Konto schlägt die Schlusslinie deutlich")
            elif avg_clv >= 2:
                score += 20; reasons.append(f"Ø CLV {avg_clv:+.1f} % über {len(clvs)} Wetten")
        if high_ev >= 30:
            score += 20; reasons.append(f"{high_ev:.0f} % der Wetten mit ≥ 8 % Vorteil beim Setzen (Fehlerquoten fallen auf)")
            tips.append("Fehlerquoten seltener nehmen oder mit kleinerem Einsatz; sie werden am schnellsten erkannt")
        elif high_ev >= 15:
            score += 10; reasons.append(f"{high_ev:.0f} % der Wetten mit ≥ 8 % Vorteil beim Setzen")
        if odd >= 50:
            score += 15; reasons.append(f"{odd:.0f} % krumme Einsätze (wirkt wie Surebet-Rechner)")
            tips.append("Einsätze auf 5 oder 10 runden; der Surebet-Rechner im Dashboard rundet auf Wunsch")
        elif odd >= 25:
            score += 7; reasons.append(f"{odd:.0f} % krumme Einsätze")
        if per_day >= 8:
            score += 15; reasons.append(f"{per_day:.1f} Wetten pro aktivem Tag")
            tips.append("Weniger Wetten pro Tag auf diesem Konto, Treffer auf mehrere Buchmacher verteilen")
        elif per_day >= 4:
            score += 7; reasons.append(f"{per_day:.1f} Wetten pro aktivem Tag")
        if roi is not None and len(settled) >= 20 and roi >= 8:
            score += 15; reasons.append(f"ROI {roi:+.1f} % über {len(settled)} abgerechnete Wetten")
        if max_stake_hint and any(b.stake >= 0.9 * max_stake_hint for b in bets):
            score += 10; reasons.append("Einsätze nahe am angenommenen Maximum")
            tips.append("Nicht regelmäßig das Maximum setzen")
        if n >= 20 and not tips:
            tips.append("Ab und zu eine unauffällige Wette (Favorit, Kombi, Live) dazwischen hält das Profil normal")
        score = min(score, 100)
        level = "hoch" if score >= 60 else "mittel" if score >= 30 else "niedrig"
        out.append(Health(bm, n, score, level, avg_clv, round(profit, 2), roi, round(odd, 1), round(high_ev, 1),
                          round(per_day, 2), reasons, tips))
    return sorted(out, key=lambda h: h.score, reverse=True)


def load_rows(conn) -> list[BetRow]:
    rows = conn.execute(
        """SELECT k.name AS bookmaker, b.placed_at, b.stake, b.price, b.fair_price_at_bet, b.result, b.payout, b.clv
           FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id"""
    ).fetchall()
    return [BetRow(r["bookmaker"], r["placed_at"], float(r["stake"]), float(r["price"]),
                   float(r["fair_price_at_bet"]) if r["fair_price_at_bet"] is not None else None,
                   r["result"], float(r["payout"]) if r["payout"] is not None else None,
                   float(r["clv"]) if r["clv"] is not None else None) for r in rows]


def evaluate(conn) -> list[Health]:
    return assess(load_rows(conn))
