"""Collector für die Betfair Exchange (Betting API-NG, JSON-RPC).

Ablauf je Lauf:
1. ``listMarketCatalogue`` für die konfigurierten Event-Typen und Markttypen (MATCH_ODDS,
   OVER_UNDER_x5, ASIAN_HANDICAP) in den nächsten ``BETFAIR_HOURS_AHEAD`` Stunden.
2. ``listMarketBook`` in Paketen zu 40 Märkten mit EX_BEST_OFFERS → beste Back-/Lay-Quote und
   verfügbare Größe je Auswahl sowie ``totalMatched`` je Markt.
3. ``parse_markets`` (reine Funktion) baut daraus NormalizedEvents. Liquidität = gematchtes
   Volumen des Marktes, damit der Scan dünne Märkte als Referenz ausschließen kann.

Zugang: App-Key (Developer-Programm, kostenloser "Delayed"-Key reicht zum Start, Quoten dann
1–180 s verzögert) plus Session-Token. Das Token kann aus dem Browser (Cookie ``ssoid``)
kommen oder per interaktivem Login mit Benutzername/Passwort geholt werden.
Alle Zugangsdaten stehen nur in ``.env``.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable

import httpx

from collectors.base import Collector
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

API_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
LOGIN_URL = "https://identitysso.betfair.com/api/login"
KEEPALIVE_URL = "https://identitysso.betfair.com/api/keepAlive"
SOURCE = "betfair"
BOOKMAKER_SOURCE_KEY = "betfair_ex"      # Schlüssel in bookmaker_source_keys (source='betfair')

EVENT_TYPE_TO_SPORT = {"1": "soccer", "2": "tennis", "7522": "basketball", "7524": "icehockey",
                       "4": "cricket", "6423": "americanfootball"}
MARKET_TYPES = ["MATCH_ODDS", "OVER_UNDER_05", "OVER_UNDER_15", "OVER_UNDER_25", "OVER_UNDER_35",
                "OVER_UNDER_45", "ASIAN_HANDICAP"]
DRAW_NAMES = {"The Draw", "Draw", "Unentschieden"}


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _best(prices: list[dict[str, Any]] | None) -> tuple[Decimal | None, Decimal | None]:
    """(beste Quote, verfügbare Größe) aus einer availableToBack/Lay-Liste."""
    if not prices:
        return None, None
    p = prices[0]
    return Decimal(str(p["price"])), Decimal(str(p.get("size", 0)))


def _market_type(cat: dict[str, Any]) -> tuple[str, Decimal | None] | None:
    mtype = (cat.get("description") or {}).get("marketType") or cat.get("marketType", "")
    if mtype == "MATCH_ODDS":
        return "h2h", None
    if mtype.startswith("OVER_UNDER_"):
        digits = mtype.rsplit("_", 1)[1]            # "25" → 2.5
        return "totals", Decimal(digits[:-1] + "." + digits[-1])
    if mtype == "ASIAN_HANDICAP":
        return "spreads", None                      # Linie steckt im Runner (handicap)
    return None


def parse_markets(catalogue: Iterable[dict[str, Any]], books: Iterable[dict[str, Any]],
                  sport_by_event_type: dict[str, str] | None = None) -> list[NormalizedEvent]:
    """Baut aus Katalog + Market-Books normalisierte Events. Reine Funktion."""
    sport_map = sport_by_event_type or EVENT_TYPE_TO_SPORT
    book_by_id = {b["marketId"]: b for b in books}
    events: dict[str, NormalizedEvent] = {}
    for cat in catalogue:
        kind = _market_type(cat)
        book = book_by_id.get(cat["marketId"])
        if kind is None or book is None:
            continue
        ev_raw = cat["event"]
        event_id = str(ev_raw["id"])
        name = ev_raw.get("name", "")
        if " v " in name:
            home, away = [x.strip() for x in name.split(" v ", 1)]
        elif " - " in name:
            home, away = [x.strip() for x in name.split(" - ", 1)]
        else:
            continue
        et = str((cat.get("eventType") or {}).get("id", ""))
        sport = sport_map.get(et, "other")
        comp = cat.get("competition") or {}
        ev = events.get(event_id)
        if ev is None:
            ev = NormalizedEvent(
                source=SOURCE, source_id=event_id,
                league_key=f"betfair_{comp.get('id', 'unknown')}",
                league_name=comp.get("name") or ev_raw.get("countryCode") or "Betfair",
                sport_key=sport, home_name=home, away_name=away,
                start_time=_ts(ev_raw.get("openDate") or (cat.get("description") or {}).get("marketTime")),
            )
            events[event_id] = ev
        mtype, line = kind
        liquidity = Decimal(str(book.get("totalMatched", 0) or 0))
        ts = _ts(book.get("lastMatchTime")) or None
        runner_names = {r["selectionId"]: r for r in cat.get("runners", [])}
        markets: dict[Decimal | None, NormalizedMarket] = {}
        for rb in book.get("runners", []):
            if rb.get("status") != "ACTIVE":
                continue
            rc = runner_names.get(rb["selectionId"])
            if rc is None:
                continue
            rname = rc.get("runnerName", "")
            ex = rb.get("ex") or {}
            back, back_size = _best(ex.get("availableToBack"))
            lay, _ = _best(ex.get("availableToLay"))
            if back is None:
                continue
            m_line = line
            if mtype == "h2h":
                if rname in DRAW_NAMES:
                    outcome = "draw"
                elif rname == home:
                    outcome = "home"
                elif rname == away:
                    outcome = "away"
                else:
                    continue
            elif mtype == "totals":
                outcome = "over" if rname.lower().startswith(("over", "über")) else "under"
            else:  # spreads: Linie aus Heimsicht
                hc = Decimal(str(rc.get("handicap", rb.get("handicap", 0)) or 0))
                if rname == home:
                    outcome, m_line = "home", hc
                elif rname == away:
                    outcome, m_line = "away", -hc
                else:
                    continue
            nm = markets.get(m_line)
            if nm is None:
                nm = NormalizedMarket(type=mtype, line=m_line)
                markets[m_line] = nm
            nm.quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, back, ts, lay_price=lay,
                                   liquidity=liquidity if liquidity else back_size))
        for nm in markets.values():
            if nm.quotes:
                ev.markets.append(nm)
    return [e for e in events.values() if e.markets]


class BetfairCollector(Collector):
    source = SOURCE

    def __init__(self, client: httpx.Client | None = None):
        if not settings.betfair_app_key:
            raise RuntimeError("BETFAIR_APP_KEY fehlt (.env)")
        self.client = client or httpx.Client(timeout=30)
        self.token = settings.betfair_session_token

    # ---- Zugang ----------------------------------------------------------

    def login(self) -> str:
        """Interaktiver Login mit Benutzername/Passwort; gibt das Session-Token zurück."""
        if not (settings.betfair_username and settings.betfair_password):
            raise RuntimeError("BETFAIR_SESSION_TOKEN oder BETFAIR_USERNAME/BETFAIR_PASSWORD fehlen (.env)")
        r = self.client.post(
            LOGIN_URL,
            data={"username": settings.betfair_username, "password": settings.betfair_password},
            headers={"X-Application": settings.betfair_app_key, "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "SUCCESS":
            raise RuntimeError(f"Betfair-Login fehlgeschlagen: {data.get('error')}")
        self.token = data["token"]
        return self.token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            self.login()
        return {"X-Application": settings.betfair_app_key, "X-Authentication": self.token,
                "Content-Type": "application/json", "Accept": "application/json"}

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        payload = {"jsonrpc": "2.0", "method": f"SportsAPING/v1.0/{method}", "params": params, "id": 1}
        r = self.client.post(API_URL, json=payload, headers=self._headers())
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            code = (data["error"].get("data") or {}).get("APINGException", {}).get("errorCode")
            if code in ("INVALID_SESSION_INFORMATION", "NO_SESSION") and settings.betfair_username:
                log.info("Betfair-Session abgelaufen, neuer Login")
                self.login()
                return self._rpc(method, params)
            raise RuntimeError(f"Betfair-Fehler bei {method}: {data['error']}")
        return data["result"]

    # ---- Daten -----------------------------------------------------------

    def list_catalogue(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        params = {
            "filter": {
                "eventTypeIds": [x.strip() for x in settings.betfair_event_types.split(",") if x.strip()],
                "marketTypeCodes": MARKET_TYPES,
                "marketStartTime": {"from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "to": (now + timedelta(hours=settings.betfair_hours_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")},
                "inPlayOnly": False,
            },
            "marketProjection": ["EVENT", "EVENT_TYPE", "COMPETITION", "RUNNER_DESCRIPTION", "MARKET_DESCRIPTION"],
            "sort": "MAXIMUM_TRADED",
            "maxResults": 1000,
        }
        return self._rpc("listMarketCatalogue", params)

    def list_books(self, market_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(market_ids), 40):
            out.extend(self._rpc("listMarketBook", {
                "marketIds": market_ids[i:i + 40],
                "priceProjection": {"priceData": ["EX_BEST_OFFERS"], "virtualise": True},
            }))
        return out

    def fetch(self) -> list[NormalizedEvent]:
        cat = self.list_catalogue()
        books = self.list_books([c["marketId"] for c in cat]) if cat else []
        events = parse_markets(cat, books)
        log.info("Betfair: %d Märkte, %d Events, %d Quoten", len(cat), len(events), sum(e.quote_count for e in events))
        return events
