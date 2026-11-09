"""Valuebet-Bewertung: EV nach Steuer, konservativer EV, Frische, Kelly.

Jede Value-Wette bekommt drei Zahlen (docs/konzept/05): EV nach Standardmethode, EV
konservativ (untere Grenze), Frische der Referenz. Gewettet wird nur, wenn der konservative EV
über der Schwelle liegt.

Unterschied zu Betburger: dort ist das "Valuebet-Prozent" die 2-Weg-Marge gegen die
Gegenquote der Referenz (ohne Steuer, ohne Alter, ohne Unsicherheit). Hier wird die faire
Wahrscheinlichkeit explizit geschätzt und der Erwartungswert gegen die *effektive* Quote
(nach Steuer/Kommission) berechnet.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Sequence

from engine import devig as dv
from engine.surebet import effective_price


@dataclass(frozen=True)
class Evaluation:
    outcome_index: int
    price: float                 # Quote beim Soft-Buchmacher (brutto)
    price_effective: float       # nach Steuer/Kommission
    fair_prob: float             # geschätzte faire Wahrscheinlichkeit
    fair_price: float            # 1 / fair_prob
    ev: float                    # Erwartungswert pro 1 Einsatz, z. B. 0.034 = +3,4 %
    ev_conservative: float       # EV am unteren Rand des Konfidenzbands
    reference_age_s: float
    kelly_fraction: float        # empfohlener Einsatzanteil (bereits mit Bruchteil-Kelly)
    method: str

    @property
    def is_bet(self) -> bool:
        return self.ev_conservative > 0


def expected_value(price_effective: float, fair_prob: float) -> float:
    """EV pro 1 Einheit Einsatz: p·q_eff − 1."""
    return fair_prob * price_effective - 1.0


def kelly(price_effective: float, fair_prob: float, fraction: float = 0.25) -> float:
    """Bruchteil-Kelly. Gibt 0 zurück, wenn kein Vorteil."""
    b = price_effective - 1.0
    if b <= 0:
        return 0.0
    f = (fair_prob * b - (1.0 - fair_prob)) / b
    return max(0.0, f * fraction)


def probability_uncertainty(fair_prob: float, n_effective: float = 400.0,
                            reference_age_s: float = 0.0, half_life_s: float = 120.0) -> float:
    """Standardabweichung der fairen Wahrscheinlichkeit.

    Grundunsicherheit wie bei einer Stichprobe von ``n_effective`` Beobachtungen (dünne Märkte:
    kleineres n), vergrößert um das Alter der Referenz: pro ``half_life_s`` Sekunden wächst die
    Unsicherheit um den Faktor sqrt(2).
    """
    base = sqrt(fair_prob * (1.0 - fair_prob) / max(n_effective, 1.0))
    age_factor = sqrt(1.0 + reference_age_s / max(half_life_s, 1.0))
    return base * age_factor


def evaluate(outcome_index: int, soft_prices: Sequence[float], references: Sequence[dv.Reference], *,
             method: str = "power", tax_rate: float = 0.0, tax_mode: str = "none",
             commission: float = 0.0, commission_mode: str = "on_winnings",
             n_effective: float = 400.0, z: float = 1.0, kelly_fraction: float = 0.25,
             max_reference_age_s: float | None = 600.0, min_liquidity: float | None = None) -> Evaluation:
    """Bewertet den Ausgang ``outcome_index`` eines Marktes beim Soft-Buchmacher.

    ``soft_prices`` sind die Quoten des Soft-Buchmachers für alle Ausgänge (nur der gewählte
    Ausgang wird bewertet), ``references`` die Referenzquellen (vollständige Märkte).
    ``z`` = 1.0 heißt: konservativer EV bei einer Standardabweichung unter dem Schätzwert.
    """
    fair = dv.consensus(references, method=method, max_age_s=max_reference_age_s, min_liquidity=min_liquidity)
    p = fair[outcome_index]
    price = float(soft_prices[outcome_index])
    q_eff = effective_price(price, commission=commission, commission_mode=commission_mode,
                            tax_rate=tax_rate, tax_mode=tax_mode)
    age = min((r.age_s for r in references), default=0.0)
    sd = probability_uncertainty(p, n_effective=n_effective, reference_age_s=age)
    p_low = max(0.0, p - z * sd)
    ev = expected_value(q_eff, p)
    ev_low = expected_value(q_eff, p_low)
    return Evaluation(
        outcome_index=outcome_index,
        price=price,
        price_effective=q_eff,
        fair_prob=p,
        fair_price=1.0 / p,
        ev=ev,
        ev_conservative=ev_low,
        reference_age_s=age,
        kelly_fraction=kelly(q_eff, p_low, kelly_fraction),
        method=method,
    )


def betburger_style_percent(soft_price: float, reference_opposite_price: float) -> float:
    """Zum Vergleich: so rechnet Betburger das 'Valuebet-Prozent' (2-Weg-Marge gegen die Gegenquote)."""
    return (1.0 / (1.0 / soft_price + 1.0 / reference_opposite_price) - 1.0) * 100.0
