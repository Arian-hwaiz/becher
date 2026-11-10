"""Scraper für Interwetten (interwetten.com, ohne Login).

Die Ligaseite ist fertig gerendertes HTML: je Spiel ein ``<li class="s-event">`` mit Link
``/de/sportwetten/e/<ID>/<slug>``, den beiden Teamnamen und dem 1X2-Markt (drei
``s-outcome``-Elemente, ``data-betting`` = [ID, "1"/"X"/"2", …], Quote in ``s-outcome-odd``).
Die Anstoßzeit steht im JSON-LD (``SportsEvent.startDate``, Ortszeit Wien, ohne Zone).

Ohne Browser antwortet die Seite mit 403, im normalen Browser ohne Challenge. Deshalb lädt der
Collector die Seite über ``collectors.page_capture`` und liest das HTML. Auf der Ligaseite steht
nur 1X2; Über/Unter gibt es erst auf der Spielseite (ein Abruf je Spiel, bewusst weggelassen).
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

SOURCE = "interwetten"
BOOKMAKER_SOURCE_KEY = "interwetten"
ORIGIN = "https://www.interwetten.com"
BASE = f"{ORIGIN}/de/sportwetten/l"
LOCAL_TZ = ZoneInfo("Europe/Vienna")

LEAGUES: dict[str, tuple[str, str]] = {
    "soccer_germany_bundesliga": (f"{BASE}/1019/deutschland-bundesliga", "Bundesliga"),
    "soccer_germany_bundesliga2": (f"{BASE}/1020/deutschland-2-liga", "2. Bundesliga"),
    "soccer_epl": (f"{BASE}/1021/england-premier-league", "Premier League"),
}

_LI = re.compile(r'<li class="s-event[ "]')
_HREF = re.compile(r'class="s-event-text" href="(/de/sportwetten/e/(\d+)/[^"]*)"')
_PLAYER = re.compile(r'<strong class="s-event-player">(.*?)</strong>', re.S)
_OUTCOME = re.compile(r'data-betting="\[(\d+),&quot;([^&]*)&quot;.*?<span class="js-outcome-odd s-outcome-odd">([^<]*)</span>', re.S)
_LDJSON = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
OUTCOMES = {"1": "home", "X": "draw", "2": "away"}


def _start_times(page: str) -> dict[str, datetime]:
    """Event-ID → Anstoß (UTC-fähig) aus den JSON-LD-Blöcken."""
    out: dict[str, datetime] = {}
    for block in _LDJSON.findall(page):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict) or item.get("@type") != "SportsEvent":
                continue
            m = re.search(r"/e/(\d+)/", item.get("url", ""))
            if not m or not item.get("startDate"):
                continue
            ts = datetime.fromisoformat(item["startDate"])
            out[m.group(1)] = ts if ts.tzinfo else ts.replace(tzinfo=LOCAL_TZ)
    return out


def parse_league_page(page: str, league_key: str, league_name: str) -> list[NormalizedEvent]:
    starts = _start_times(page)
    starts_idx = [m.start() for m in _LI.finditer(page)] + [len(page)]
    events: list[NormalizedEvent] = []
    seen: set[str] = set()
    for a, b in zip(starts_idx, starts_idx[1:]):
        seg = page[a:b]
        href = _HREF.search(seg)
        players = [htmllib.unescape(p).strip() for p in _PLAYER.findall(seg)]
        if not href or len(players) != 2:
            continue                      # Langzeitwetten u. Ä.
        ev_id = href.group(2)
        if ev_id in seen or ev_id not in starts:
            continue
        seen.add(ev_id)
        quotes = []
        for _oid, label, odd in _OUTCOME.findall(seg):
            outcome = OUTCOMES.get(htmllib.unescape(label))
            try:
                price = Decimal(odd.strip().replace(",", "."))
            except InvalidOperation:
                continue
            if outcome and price > 1:
                quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, price))
        ev = NormalizedEvent(
            source=SOURCE, source_id=ev_id, league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=players[0], away_name=players[1],
            start_time=starts[ev_id],
        )
        if len({q.outcome for q in quotes}) == 3:
            ev.markets = [NormalizedMarket("h2h", None, quotes)]
        ev.links[BOOKMAKER_SOURCE_KEY] = ORIGIN + href.group(1)
        events.append(ev)
    return events


class InterwettenCollector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("interwetten: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("interwetten: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        keys = list(self.leagues)
        caps = capture_pages([self.leagues[k][0] for k in keys], wait_s=4, capture_html=True)
        events: list[NormalizedEvent] = []
        for key, cap in zip(keys, caps):
            batch = parse_league_page(cap.html, key, self.leagues[key][1])
            log.info("interwetten %s: %d Events, %d Quoten", key, len(batch), sum(e.quote_count for e in batch))
            events.extend(batch)
        return events
