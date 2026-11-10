"""Scraper für bet-at-home (sports2.bet-at-home.com, ohne Login).

Das Sportsbook lädt seine Daten über einen WAMP-WebSocket (``wss://sportsapiem.bet-at-home.com``)
als JSON-Entitäten mit ``_type``: MATCH, MARKET, OUTCOME, MARKET_OUTCOME_RELATION, BETTING_OFFER.
Der Collector öffnet die Länderseite (alle Ligen eines Landes) in Playwright, schneidet die
empfangenen Frames mit und baut daraus mit ``parse_entities`` (reine Funktion, Test mit
tests/fixtures/betathome_sample.json) NormalizedEvents:

* h2h: Markt bettingTypeId 69 (1X2), reguläre Spielzeit (eventPartId 3),
* totals: bettingTypeId 47 (Über/Unter), Linie aus ``paramFloat1``,
* Ausgang über ``headerNameKey`` (home/draw/away/over/under), Quote aus BETTING_OFFER,
* Liga über ``shortParentName`` des Matches, Direkt-Link ``/de/event/…/<Match-ID>``.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable
from urllib.parse import quote

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

SOURCE = "betathome"
BOOKMAKER_SOURCE_KEY = "betathome"
ORIGIN = "https://sports2.bet-at-home.com"
COUNTRY = f"{ORIGIN}/de/tournament-location/fu%C3%9Fball/1"

# Odds-API-Ligaschlüssel → (Länderseite, shortParentName der Liga, Anzeigename, Kürzel in der Adresse)
LEAGUES: dict[str, tuple[str, str, str, str]] = {
    "soccer_germany_bundesliga": (f"{COUNTRY}/ger/54/all/0", "Bundesliga", "Bundesliga", "ger"),
    "soccer_germany_bundesliga2": (f"{COUNTRY}/ger/54/all/0", "2. Bundesliga", "2. Bundesliga", "ger"),
    "soccer_epl": (f"{COUNTRY}/eng/77/all/0", "Premier League", "Premier League", "eng"),
}

BT_1X2, BT_TOTAL, PART_REGULAR = "69", "47", "3"
OUTCOMES = {"home", "draw", "away", "over", "under"}


def entities(frames: Iterable[str | bytes]) -> dict[str, dict[str, dict[str, Any]]]:
    """Alle Objekte mit ``_type`` und ``id`` aus den WAMP-Frames, je Typ und ID (spätere ergänzen frühere)."""
    by: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            t, i = o.get("_type"), o.get("id")
            if t and i is not None:
                by[t].setdefault(str(i), {}).update(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for fr in frames:
        try:
            walk(json.loads(fr))
        except (ValueError, TypeError):
            continue
    return by


def _slug(s: str) -> str:
    return re.sub(r"[^\w]+", "-", s.lower().replace(".", ""), flags=re.UNICODE).strip("-")


def _event_link(match: dict[str, Any], country: str, links: Iterable[str]) -> str:
    mid = str(match["id"])
    for href in links:
        if href.rstrip("/").endswith("/" + mid):
            return href
    league = _slug(match.get("shortParentName", ""))
    return (f"{ORIGIN}/de/event/1/fu%C3%9Fball/{country}/{quote(league)}/"
            f"{quote(_slug(match.get('name', '')))}/{mid}")


def parse_entities(by: dict[str, dict[str, dict[str, Any]]], league_key: str, league_short: str,
                   league_name: str, country: str, links: Iterable[str] = ()) -> list[NormalizedEvent]:
    links = list(links)
    rel: dict[str, list[str]] = defaultdict(list)
    for r in by.get("MARKET_OUTCOME_RELATION", {}).values():
        rel[str(r.get("marketId"))].append(str(r.get("outcomeId")))
    offers: dict[str, dict[str, Any]] = {}
    for o in by.get("BETTING_OFFER", {}).values():
        if o.get("isAvailable", True) and str(o.get("statusId", "1")) == "1" and not o.get("isLive"):
            offers[str(o.get("outcomeId"))] = o
    markets_by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for m in by.get("MARKET", {}).values():
        if str(m.get("eventPartId")) == PART_REGULAR and not m.get("isClosed") and m.get("isAvailable", True):
            markets_by_event[str(m.get("eventId"))].append(m)
    outcomes = by.get("OUTCOME", {})

    events: list[NormalizedEvent] = []
    for match in by.get("MATCH", {}).values():
        if match.get("shortParentName") != league_short or str(match.get("statusId", "1")) != "1":
            continue
        home, away = match.get("homeParticipantName"), match.get("awayParticipantName")
        if not home or not away or not match.get("startTime"):
            continue
        ev = NormalizedEvent(
            source=SOURCE, source_id=str(match["id"]), league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=home, away_name=away,
            start_time=datetime.fromtimestamp(int(match["startTime"]) / 1000, tz=timezone.utc),
        )
        nms: dict[tuple[str, Decimal | None], NormalizedMarket] = {}
        for m in markets_by_event.get(str(match["id"]), []):
            bt = str(m.get("bettingTypeId"))
            if bt == BT_1X2:
                key = ("h2h", None)
            elif bt == BT_TOTAL and m.get("paramFloat1") is not None:
                key = ("totals", Decimal(str(m["paramFloat1"])))
            else:
                continue
            for oid in rel.get(str(m["id"]), []):
                oc, off = outcomes.get(oid), offers.get(oid)
                outcome = (oc or {}).get("headerNameKey")
                if not off or outcome not in OUTCOMES or not off.get("odds"):
                    continue
                nm = nms.setdefault(key, NormalizedMarket(key[0], key[1]))
                nm.quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, Decimal(str(off["odds"]))))
        ev.markets = [m for m in nms.values() if len(m.quotes) >= 2]
        ev.links[BOOKMAKER_SOURCE_KEY] = _event_link(match, country, links)
        events.append(ev)
    return events


class BetAtHomeCollector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("betathome: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("betathome: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        urls = list(dict.fromkeys(v[0] for v in self.leagues.values()))   # eine Länderseite für mehrere Ligen
        caps = dict(zip(urls, capture_pages(urls, capture_ws=True, wait_s=12, link_contains="/de/event/")))
        events: list[NormalizedEvent] = []
        for key, (url, short, name, country) in self.leagues.items():
            cap = caps[url]
            batch = parse_entities(entities(cap.ws_frames), key, short, name, country, [h for h, _ in cap.links])
            batch = [e for e in batch if e.markets]
            log.info("betathome %s: %d Events, %d Quoten", key, len(batch), sum(e.quote_count for e in batch))
            events.extend(batch)
        return events
