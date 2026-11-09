"""Collector für The Odds API (https://the-odds-api.com, v4).

Endpunkt: GET /v4/sports/{sport}/odds?regions=eu&markets=h2h,totals&oddsFormat=decimal&apiKey=...
Antwort: Liste von Events, je Event eine Liste von Buchmachern mit Märkten und Outcomes.
Das Kontingent steht in den Antwort-Headern x-requests-remaining / x-requests-used.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from collectors.base import Collector
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _sport_key(league_key: str) -> str:
    """'soccer_germany_bundesliga' -> 'soccer'."""
    return league_key.split("_", 1)[0]


def parse_events(payload: list[dict[str, Any]], league_key: str) -> list[NormalizedEvent]:
    """Wandelt die Odds-API-Antwort in normalisierte Events um. Reine Funktion, gut testbar."""
    events: list[NormalizedEvent] = []
    for raw in payload:
        home, away = raw["home_team"], raw["away_team"]
        ev = NormalizedEvent(
            source="odds_api",
            source_id=raw["id"],
            league_key=league_key,
            league_name=raw.get("sport_title", league_key),
            sport_key=_sport_key(league_key),
            home_name=home,
            away_name=away,
            start_time=_ts(raw["commence_time"]),
        )
        # Märkte über alle Buchmacher zusammenführen: (type, line) -> NormalizedMarket
        markets: dict[tuple[str, Decimal | None], NormalizedMarket] = {}
        for bm in raw.get("bookmakers", []):
            bm_key = bm["key"]
            bm_ts = _ts(bm.get("last_update"))
            for m in bm.get("markets", []):
                mtype = m["key"]
                if mtype not in ("h2h", "totals", "spreads"):
                    continue
                for oc in m.get("outcomes", []):
                    outcome, line = _map_outcome(mtype, oc, home, away)
                    if outcome is None:
                        continue
                    nm = markets.setdefault((mtype, line), NormalizedMarket(type=mtype, line=line))
                    nm.quotes.append(Quote(bm_key, outcome, Decimal(str(oc["price"])), bm_ts))
        ev.markets = list(markets.values())
        events.append(ev)
    return events


def _map_outcome(mtype: str, oc: dict[str, Any], home: str, away: str) -> tuple[str | None, Decimal | None]:
    name = oc["name"]
    if mtype == "h2h":
        if name == home:
            return "home", None
        if name == away:
            return "away", None
        if name == "Draw":
            return "draw", None
        return None, None
    point = oc.get("point")
    line = Decimal(str(point)) if point is not None else None
    if mtype == "totals":
        if name == "Over":
            return "over", line
        if name == "Under":
            return "under", line
        return None, None
    if mtype == "spreads":
        # Handicap: Linie aus Sicht des Heimteams speichern
        if name == home:
            return "home", line
        if name == away:
            return "away", -line if line is not None else None
        return None, None
    return None, None


class OddsApiCollector(Collector):
    source = "odds_api"

    def __init__(self, api_key: str | None = None, sports: list[str] | None = None,
                 regions: str | None = None, markets: str | None = None, client: httpx.Client | None = None):
        self.api_key = api_key or settings.odds_api_key
        self.sports = sports or settings.sports
        self.regions = regions or settings.odds_api_regions
        self.markets = markets or settings.odds_api_markets
        self.client = client or httpx.Client(timeout=20)
        self.remaining: int | None = None

    def fetch(self) -> list[NormalizedEvent]:
        if not self.api_key:
            raise RuntimeError("ODDS_API_KEY fehlt (.env)")
        events: list[NormalizedEvent] = []
        for sport in self.sports:
            r = self.client.get(
                f"{BASE_URL}/sports/{sport}/odds",
                params={"regions": self.regions, "markets": self.markets,
                        "oddsFormat": "decimal", "dateFormat": "iso", "apiKey": self.api_key},
            )
            r.raise_for_status()
            rem = r.headers.get("x-requests-remaining")
            self.remaining = int(rem) if rem and rem.isdigit() else self.remaining
            batch = parse_events(r.json(), sport)
            log.info("odds_api %s: %d Events, %d Quoten, Kontingent %s", sport, len(batch),
                     sum(e.quote_count for e in batch), self.remaining)
            events.extend(batch)
        return events
