"""Generischer Surebet- und Middle-Rechner über eine Auszahlungsmatrix.

Betburger pflegt 21 handgeschriebene Formeltypen (2-Weg, 3-Weg, Asian-Handicap mit
Rückgabe/halber Rückgabe/halbem Gewinn, Middles). Alle sind Spezialfälle derselben Aufgabe:
Einsätze so verteilen, dass der Gewinn in jedem möglichen Spielausgang (Szenario) gleich
hoch ist. Hier wird das einmal allgemein gelöst:

* Eine ``Leg`` ist eine Wette mit Dezimalquote und, je Szenario, einem Ergebnis
  (WIN, LOSE, PUSH, HALF_WIN, HALF_LOSE).
* ``solve`` berechnet Einsätze (Summe 1) und die Marge in Prozent. Bei genauso vielen
  Szenarien wie Wetten werden die Auszahlungen exakt angeglichen (klassische Surebet);
  sonst wird die schlechteste Auszahlung maximiert (Middles, Viertellinien).
* ``handicap_legs`` und ``total_legs`` bauen die Szenarien für Handicap- und Totals-Linien
  (inkl. Viertellinien wie -0.25 oder 2.75) automatisch.

Kommission und Steuer werden vorher auf die Quote angewendet, siehe ``effective_price``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from itertools import product
from typing import Iterable, Sequence


class Result(str, Enum):
    WIN = "win"
    LOSE = "lose"
    PUSH = "push"            # Einsatz zurück
    HALF_WIN = "half_win"    # halber Einsatz gewinnt, halber zurück
    HALF_LOSE = "half_lose"  # halber Einsatz verloren, halber zurück


def payout_factor(price: float, result: Result) -> float:
    """Auszahlung pro 1 Einheit Einsatz."""
    if result is Result.WIN:
        return price
    if result is Result.LOSE:
        return 0.0
    if result is Result.PUSH:
        return 1.0
    if result is Result.HALF_WIN:
        return (price + 1.0) / 2.0
    if result is Result.HALF_LOSE:
        return 0.5
    raise ValueError(result)


@dataclass(frozen=True)
class Leg:
    """Eine Wette: Quote plus Ergebnis je Szenario (gleiche Reihenfolge wie ``scenarios``)."""

    price: float
    results: tuple[Result, ...]
    label: str = ""

    def factors(self) -> list[float]:
        return [payout_factor(self.price, r) for r in self.results]


@dataclass
class Solution:
    stakes: list[float]            # Anteile, Summe 1
    payouts: list[float]           # Auszahlung je Szenario bei Gesamteinsatz 1
    percent: float                 # garantierte Marge in % (min. Auszahlung - 1) * 100
    max_percent: float             # beste Auszahlung in % (bei Middles > percent)
    equalized: bool                # True, wenn alle Szenarien gleich auszahlen
    scenarios: list[str] = field(default_factory=list)

    def stakes_for(self, total: float, round_to: float = 0.01) -> list[float]:
        """Einsätze für einen Gesamteinsatz, gerundet."""
        raw = [s * total for s in self.stakes]
        return [round(round(x / round_to) * round_to, 10) for x in raw]


# ---------------------------------------------------------------- Kommission/Steuer

def effective_price(price: float, *, commission: float = 0.0, commission_mode: str = "on_winnings",
                    tax_rate: float = 0.0, tax_mode: str = "none") -> float:
    """Quote nach Börsenkommission und Wettsteuer.

    commission_mode: "on_winnings" (Betfair: k auf Nettogewinn) oder "on_stake".
    tax_mode: "none", "on_stake" (5,3 % vom Einsatz, Gewinn wird aus Netto-Einsatz gezahlt;
    entspricht Quote * (1 - t)) oder "on_winnings" (Steuer nur auf den Gewinn).
    """
    q = float(price)
    if commission:
        if commission_mode == "on_winnings":
            q = 1.0 + (q - 1.0) * (1.0 - commission)
        elif commission_mode == "on_stake":
            q = q * (1.0 - commission)
        else:
            raise ValueError(commission_mode)
    if tax_rate and tax_mode != "none":
        if tax_mode == "on_stake":
            q = q * (1.0 - tax_rate)
        elif tax_mode == "on_winnings":
            q = 1.0 + (q - 1.0) * (1.0 - tax_rate)
        else:
            raise ValueError(tax_mode)
    return q


def lay_to_back(lay_price: float) -> float:
    """Lay-Quote an der Börse als äquivalente Back-Quote der Gegenseite."""
    return 1.0 + 1.0 / (lay_price - 1.0)


# ---------------------------------------------------------------- Löser

def _solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Gauß-Elimination mit Pivotisierung, kleine Systeme, ohne numpy."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-12:
            raise ValueError("singuläres System: Szenarien unterscheiden die Wetten nicht")
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                if f:
                    for c in range(col, n + 1):
                        m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def _maximin(factor_matrix: list[list[float]], steps: int = 2000) -> list[float]:
    """Maximiert die schlechteste Auszahlung (Simplex-Gitter + lokale Verfeinerung).

    factor_matrix[k][i] = Auszahlungsfaktor von Wette i im Szenario k. Für 2 Wetten ist das
    exakt (Schnittpunkte linearer Funktionen), für 3+ Wetten eine feine Gittersuche.
    """
    n = len(factor_matrix[0])
    if n == 1:
        return [1.0]

    def worst(st: Sequence[float]) -> float:
        return min(sum(f * s for f, s in zip(row, st)) for row in factor_matrix)

    if n == 2:
        # Kandidaten: Ränder und alle paarweisen Schnittpunkte der Szenario-Geraden
        cands = {0.0, 1.0}
        rows = factor_matrix
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                # (a_i - b_i) s + b_i = (a_j - b_j) s + b_j
                d = (rows[i][0] - rows[i][1]) - (rows[j][0] - rows[j][1])
                if abs(d) > 1e-12:
                    s = (rows[j][1] - rows[i][1]) / d
                    if 0.0 <= s <= 1.0:
                        cands.add(s)
        best = max(cands, key=lambda s: worst([s, 1 - s]))
        return [best, 1 - best]

    # n >= 3: Gittersuche über dem Simplex, danach Verfeinerung
    best_s, best_v = None, float("-inf")
    g = 60 if n == 3 else 24
    for comb in product(range(g + 1), repeat=n - 1):
        if sum(comb) > g:
            continue
        st = [c / g for c in comb] + [(g - sum(comb)) / g]
        v = worst(st)
        if v > best_v:
            best_s, best_v = st, v
    assert best_s is not None
    step = 1.0 / g
    for _ in range(12):
        step /= 2
        improved = True
        while improved:
            improved = False
            for i in range(n):
                for j in range(n):
                    if i == j:
                        continue
                    cand = best_s[:]
                    cand[i] += step
                    cand[j] -= step
                    if cand[j] < 0:
                        continue
                    v = worst(cand)
                    if v > best_v + 1e-15:
                        best_s, best_v, improved = cand, v, True
    return best_s


def solve(legs: Sequence[Leg], scenarios: Sequence[str] | None = None) -> Solution:
    """Einsatzverteilung und Marge für beliebige Wetten/Szenarien."""
    if not legs:
        raise ValueError("keine Wetten")
    m = len(legs[0].results)
    if any(len(l.results) != m for l in legs):
        raise ValueError("alle Wetten brauchen gleich viele Szenarien")
    names = list(scenarios) if scenarios is not None else [f"S{k+1}" for k in range(m)]
    factors = [[payout_factor(l.price, l.results[k]) for l in legs] for k in range(m)]  # [szenario][wette]
    n = len(legs)

    equalized = False
    stakes: list[float] | None = None
    if m == n:
        # Unbekannte: s_1..s_n, r.  Gleichungen: sum_i f_ki s_i - r = 0 (k=1..m), sum s_i = 1
        a = [row[:] + [-1.0] for row in factors] + [[1.0] * n + [0.0]]
        b = [0.0] * m + [1.0]
        try:
            sol = _solve_linear(a, b)
            cand = sol[:n]
            if all(s >= -1e-9 for s in cand):
                stakes = [max(0.0, s) for s in cand]
                equalized = True
        except ValueError:
            stakes = None
    if stakes is None:
        stakes = _maximin(factors)
        equalized = False

    payouts = [sum(f * s for f, s in zip(row, stakes)) for row in factors]
    worst, best = min(payouts), max(payouts)
    return Solution(
        stakes=stakes,
        payouts=payouts,
        percent=round((worst - 1.0) * 100.0, 4),
        max_percent=round((best - 1.0) * 100.0, 4),
        equalized=equalized or abs(best - worst) < 1e-9,
        scenarios=names,
    )


# ---------------------------------------------------------------- Komfort-Funktionen

def simple(prices: Iterable[float], labels: Sequence[str] | None = None) -> Solution:
    """Klassische n-Weg-Surebet: jede Wette gewinnt in genau einem Szenario."""
    ps = list(prices)
    n = len(ps)
    legs = [
        Leg(p, tuple(Result.WIN if k == i else Result.LOSE for k in range(n)),
            labels[i] if labels else f"W{i+1}")
        for i, p in enumerate(ps)
    ]
    return solve(legs, labels)


def margin_percent(prices: Iterable[float]) -> float:
    """Schnelle Marge einer n-Weg-Surebet: (1 / Summe(1/q) - 1) * 100. Negativ = keine Surebet."""
    inv = sum(1.0 / p for p in prices)
    return round((1.0 / inv - 1.0) * 100.0, 4)


def _line_result(diff: Fraction, line: Fraction) -> Result:
    """Ergebnis einer Wette 'diff + line > 0 gewinnt' inkl. Viertellinien."""
    q = line * 4
    if q.denominator == 1 and q.numerator % 2 == 1:
        # Viertellinie: halber Einsatz auf line-0.25, halber auf line+0.25
        lo, hi = line - Fraction(1, 4), line + Fraction(1, 4)
        r1, r2 = _line_result(diff, lo), _line_result(diff, hi)
        if r1 is r2:
            return r1
        if {r1, r2} == {Result.WIN, Result.PUSH}:
            return Result.HALF_WIN
        if {r1, r2} == {Result.LOSE, Result.PUSH}:
            return Result.HALF_LOSE
        raise AssertionError((r1, r2))
    v = diff + line
    if v > 0:
        return Result.WIN
    if v < 0:
        return Result.LOSE
    return Result.PUSH


def _scenario_range(lines: Iterable[Fraction], span: int) -> list[int]:
    vals = [abs(float(l)) for l in lines]
    hi = int(max(vals + [0.0])) + span
    return list(range(-hi, hi + 1))


def handicap_legs(price_home: float, line_home: float, price_away: float, line_away: float,
                  span: int = 3) -> tuple[list[Leg], list[str]]:
    """Asian Handicap: Wette A auf Heim mit Linie, Wette B auf Gast mit Linie (aus Gast-Sicht).

    Szenarien sind Tor-/Punktedifferenzen Heim minus Gast. Beispiel: Heim -0.5 @ 2.10 und
    Gast +0.75 @ 1.95 → Middle-Charakter bei Differenz 0 (Gast gewinnt halb, Heim verliert).
    """
    lh, la = Fraction(str(line_home)), Fraction(str(line_away))
    diffs = _scenario_range([lh, la], span)
    names = [f"diff {d:+d}" for d in diffs]
    home = Leg(price_home, tuple(_line_result(Fraction(d), lh) for d in diffs), f"Heim {line_home:+}")
    away = Leg(price_away, tuple(_line_result(Fraction(-d), la) for d in diffs), f"Gast {line_away:+}")
    return [home, away], names


def total_legs(price_over: float, line_over: float, price_under: float, line_under: float,
               span: int = 3) -> tuple[list[Leg], list[str]]:
    """Über/Unter mit (ggf. verschiedenen) Linien. Szenarien: Gesamtzahl Tore/Punkte."""
    lo, lu = Fraction(str(line_over)), Fraction(str(line_under))
    hi = int(max(float(lo), float(lu))) + span
    totals = list(range(0, hi + 1))
    names = [f"total {t}" for t in totals]
    over = Leg(price_over, tuple(_line_result(Fraction(t), -lo) for t in totals), f"Über {line_over}")
    under = Leg(price_under, tuple(_line_result(Fraction(-t), lu) for t in totals), f"Unter {line_under}")
    return [over, under], names


def handicap(price_home: float, line_home: float, price_away: float, line_away: float) -> Solution:
    legs, names = handicap_legs(price_home, line_home, price_away, line_away)
    return solve(legs, names)


def total(price_over: float, line_over: float, price_under: float, line_under: float) -> Solution:
    legs, names = total_legs(price_over, line_over, price_under, line_under)
    return solve(legs, names)
