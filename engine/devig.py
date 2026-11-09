"""Devig: aus Buchmacherquoten die Marge herausrechnen und faire Wahrscheinlichkeiten schätzen.

Alle Funktionen nehmen Dezimalquoten eines vollständigen Marktes (alle Ausgänge) und geben
faire Wahrscheinlichkeiten zurück, die sich zu 1 summieren.

Methoden (siehe docs/konzept/05):
* ``multiplicative``  – jede implizite Wahrscheinlichkeit durch die Summe teilen (Standard, so
  rechnet Betburger V2).
* ``additive``        – gleiche Marge von jedem Ausgang abziehen.
* ``power``           – p_i = q_i^k, k so dass Summe 1; legt mehr Marge auf Außenseiter
  (Favoriten-Außenseiter-Bias).
* ``shin``            – Shin-Modell (Insider-Anteil z), ebenfalls außenseiterlastig; Lösung per
  Bisektion.
* ``logit``           – logistische Verschiebung aller Logits um eine Konstante.
``consensus`` mischt mehrere Referenzquellen gewichtet.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, log
from typing import Callable, Iterable, Sequence

Method = Callable[[Sequence[float]], list[float]]


def implied(prices: Sequence[float]) -> list[float]:
    return [1.0 / p for p in prices]


def overround(prices: Sequence[float]) -> float:
    """Buchmachermarge als Anteil, z. B. 0.05 = 5 %."""
    return sum(implied(prices)) - 1.0


def _check(prices: Sequence[float]) -> None:
    if len(prices) < 2:
        raise ValueError("ein Markt braucht mindestens zwei Ausgänge")
    if any(p <= 1.0 for p in prices):
        raise ValueError("Quoten müssen > 1 sein")


def multiplicative(prices: Sequence[float]) -> list[float]:
    _check(prices)
    q = implied(prices)
    s = sum(q)
    return [x / s for x in q]


def additive(prices: Sequence[float]) -> list[float]:
    _check(prices)
    q = implied(prices)
    m = (sum(q) - 1.0) / len(q)
    out = [x - m for x in q]
    if min(out) <= 0:  # bei extremen Außenseitern unbrauchbar → multiplikativ
        return multiplicative(prices)
    return out


def _bisect(f: Callable[[float], float], lo: float, hi: float, tol: float = 1e-12, it: int = 200) -> float:
    flo = f(lo)
    for _ in range(it):
        mid = (lo + hi) / 2.0
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if (flo < 0) == (fm < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2.0


def power(prices: Sequence[float]) -> list[float]:
    _check(prices)
    q = implied(prices)
    # Summe q_i^k = 1, k > 1 bei Overround
    f = lambda k: sum(x ** k for x in q) - 1.0
    k = _bisect(f, 1.0, 10.0) if f(1.0) > 0 else _bisect(f, 0.1, 1.0)
    out = [x ** k for x in q]
    s = sum(out)
    return [x / s for x in out]


def shin(prices: Sequence[float]) -> list[float]:
    """Shin (1993): Anteil z informierter Wetter; p_i = (sqrt(z² + 4(1−z) q_i²/Σq) − z) / (2(1−z))."""
    _check(prices)
    q = implied(prices)
    s = sum(q)
    if s <= 1.0:
        return multiplicative(prices)

    def probs(z: float) -> list[float]:
        return [((z * z + 4.0 * (1.0 - z) * x * x / s) ** 0.5 - z) / (2.0 * (1.0 - z)) for x in q]

    z = _bisect(lambda z: sum(probs(z)) - 1.0, 0.0, 0.5)
    out = probs(z)
    t = sum(out)
    return [x / t for x in out]


def logit(prices: Sequence[float]) -> list[float]:
    _check(prices)
    q = implied(prices)
    lg = [log(x / (1.0 - x)) for x in q]

    def total(c: float) -> float:
        return sum(1.0 / (1.0 + exp(-(l - c))) for l in lg) - 1.0

    c = _bisect(total, -5.0, 5.0)
    out = [1.0 / (1.0 + exp(-(l - c))) for l in lg]
    s = sum(out)
    return [x / s for x in out]


METHODS: dict[str, Method] = {
    "multiplicative": multiplicative,
    "additive": additive,
    "power": power,
    "shin": shin,
    "logit": logit,
}


def devig(prices: Sequence[float], method: str = "multiplicative") -> list[float]:
    try:
        fn = METHODS[method]
    except KeyError:
        raise ValueError(f"unbekannte Devig-Methode {method!r}; bekannt: {sorted(METHODS)}") from None
    return fn(prices)


def fair_prices(prices: Sequence[float], method: str = "multiplicative") -> list[float]:
    """Faire Quoten (1/p) nach Devig."""
    return [1.0 / p for p in devig(prices, method)]


@dataclass(frozen=True)
class Reference:
    """Eine Referenzquelle für einen Markt: vollständige Quoten plus Gewicht und Alter."""

    name: str
    prices: Sequence[float]
    weight: float = 1.0
    age_s: float = 0.0          # Alter der Quote in Sekunden
    liquidity: float | None = None  # gematchtes Volumen (Börse), None = unbekannt


def consensus(refs: Iterable[Reference], method: str = "multiplicative",
              max_age_s: float | None = None, min_liquidity: float | None = None) -> list[float]:
    """Gewichteter Durchschnitt fairer Wahrscheinlichkeiten mehrerer Referenzen.

    Referenzen, die zu alt oder zu illiquide sind, werden ausgelassen. Bleibt keine übrig,
    wird ValueError geworfen (dann gibt es schlicht keine verlässliche faire Quote).
    """
    acc: list[float] | None = None
    wsum = 0.0
    for r in refs:
        if max_age_s is not None and r.age_s > max_age_s:
            continue
        if min_liquidity is not None and r.liquidity is not None and r.liquidity < min_liquidity:
            continue
        p = devig(r.prices, method)
        if acc is None:
            acc = [0.0] * len(p)
        if len(p) != len(acc):
            raise ValueError("Referenzen haben unterschiedlich viele Ausgänge")
        acc = [a + r.weight * x for a, x in zip(acc, p)]
        wsum += r.weight
    if acc is None or wsum <= 0:
        raise ValueError("keine verwertbare Referenz")
    return [a / wsum for a in acc]
