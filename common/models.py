"""Normalisierte Datentypen, die alle Collector liefern.

Ein Collector holt Rohdaten bei einer Quelle und gibt eine Liste von
NormalizedEvent zurück. Alles danach (Speichern, Rechnen) kennt nur diese Typen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

MarketType = Literal["h2h", "totals", "spreads"]
Outcome = Literal["home", "draw", "away", "over", "under"]


@dataclass(frozen=True)
class Quote:
    bookmaker_source_key: str      # Schlüssel des Buchmachers in der Quelle
    outcome: str                   # Outcome
    price: Decimal                 # Dezimalquote
    source_ts: datetime | None = None


@dataclass
class NormalizedMarket:
    type: str                      # MarketType
    line: Decimal | None           # z. B. 2.5 bei totals, Handicap bei spreads
    quotes: list[Quote] = field(default_factory=list)
    period: str = "full_time"


@dataclass
class NormalizedEvent:
    source: str                    # "odds_api"
    source_id: str
    league_key: str                # "soccer_germany_bundesliga"
    league_name: str
    sport_key: str                 # "soccer"
    home_name: str
    away_name: str
    start_time: datetime
    markets: list[NormalizedMarket] = field(default_factory=list)

    @property
    def quote_count(self) -> int:
        return sum(len(m.quotes) for m in self.markets)
