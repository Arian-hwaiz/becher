"""Welche Devig-Methode passt zu welchem Markt? Bewertung an abgerechneten Wetten.

Für jede abgerechnete Wette mit Schlussquoten einer scharfen Referenz wird je Devig-Methode die
Wahrscheinlichkeit des gesetzten Ausgangs aus der Schlusslinie berechnet und mit dem Ergebnis
verglichen (Brier-Score und Log-Loss, beides: je kleiner, desto besser kalibriert). Zusätzlich der
mittlere CLV je Methode. Die Methode mit dem kleinsten Brier-Score je Markttyp ist die Empfehlung.

Das ist bewusst einfach: bei wenigen Wetten sind die Unterschiede Rauschen (``n`` beachten,
unter 30 Wetten keine Entscheidung treffen).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from engine import devig as dv
from engine.clv import OUTCOME_ORDER, clv_percent

MIN_BETS = 30
WIN_VALUE = {"won": 1.0, "lost": 0.0, "half_won": 0.75, "half_lost": 0.25}   # Anteil „gewonnen“


@dataclass(frozen=True)
class SettledBet:
    market_type: str
    outcome: str
    price: float
    result: str                      # won | lost | half_won | half_lost (void wird vorher gefiltert)
    closing: dict[str, float]        # Schlussquoten der Referenz je Ausgang


@dataclass
class MethodScore:
    market_type: str
    method: str
    n: int
    brier: float
    logloss: float
    avg_clv: float
    recommended: bool = False


def _probability(bet: SettledBet, method: str) -> float | None:
    order = OUTCOME_ORDER.get(bet.market_type)
    if not order or bet.outcome not in order:
        return None
    present = [oc for oc in order if oc in bet.closing]
    if len(present) < 2 or bet.outcome not in present:
        return None
    probs = dv.devig([bet.closing[oc] for oc in present], method)
    return probs[present.index(bet.outcome)]


def score_methods(bets: Iterable[SettledBet], methods: Sequence[str] = tuple(dv.METHODS)) -> list[MethodScore]:
    """Brier, Log-Loss und Ø CLV je Markttyp und Methode; die beste Methode je Markttyp ist markiert."""
    bets = [b for b in bets if b.result in WIN_VALUE]
    acc: dict[tuple[str, str], list[tuple[float, float, float]]] = {}
    for b in bets:
        for m in methods:
            p = _probability(b, m)
            if p is None:
                continue
            y = WIN_VALUE[b.result]
            p_c = min(max(p, 1e-6), 1 - 1e-6)
            acc.setdefault((b.market_type, m), []).append(
                ((p - y) ** 2, -(y * math.log(p_c) + (1 - y) * math.log(1 - p_c)), clv_percent(b.price, 1 / p)))
    out: list[MethodScore] = []
    for (mt, m), rows in acc.items():
        n = len(rows)
        out.append(MethodScore(mt, m, n, sum(r[0] for r in rows) / n, sum(r[1] for r in rows) / n, sum(r[2] for r in rows) / n))
    for mt in {s.market_type for s in out}:
        group = [s for s in out if s.market_type == mt]
        best = min(group, key=lambda s: s.brier)
        if best.n >= MIN_BETS:
            best.recommended = True
    return sorted(out, key=lambda s: (s.market_type, s.brier))


def load_settled_bets(conn, reference_kinds: Sequence[str] = ("sharp",)) -> list[SettledBet]:
    rows = conn.execute(
        """SELECT b.id, b.outcome, b.price, b.result, m.type, c.bookmaker_id, c.outcome AS c_outcome, c.price AS c_price
           FROM bets b JOIN markets m ON m.id = b.market_id
           JOIN closing_odds c ON c.market_id = b.market_id JOIN bookmakers k ON k.id = c.bookmaker_id
           WHERE b.result IN ('won','lost','half_won','half_lost') AND k.kind = ANY(%s)
           ORDER BY b.id, c.bookmaker_id""",
        (list(reference_kinds),),
    ).fetchall()
    by_bet: dict[int, dict[str, Any]] = {}
    for r in rows:
        e = by_bet.setdefault(r["id"], {"outcome": r["outcome"], "price": float(r["price"]), "result": r["result"],
                                         "type": r["type"], "refs": {}})
        e["refs"].setdefault(r["bookmaker_id"], {})[r["c_outcome"]] = float(r["c_price"])
    out = []
    for e in by_bet.values():
        # erste Referenz mit vollständiger Quotenreihe, sonst die mit den meisten Ausgängen
        refs = sorted(e["refs"].values(), key=len, reverse=True)
        if refs:
            out.append(SettledBet(e["type"], e["outcome"], e["price"], e["result"], refs[0]))
    return out


def evaluate(conn) -> list[MethodScore]:
    return score_methods(load_settled_bets(conn))


def recommendations(scores: Iterable[MethodScore]) -> dict[str, str]:
    """Markttyp → empfohlene Methode (nur mit genug Wetten)."""
    return {s.market_type: s.method for s in scores if s.recommended}
