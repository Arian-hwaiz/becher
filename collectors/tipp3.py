"""Scraper für tipp3 (tipp3.at, Österreichische Lotterien, ohne Login).

Die Ligaseite ``/sport/fussball/<land>/<liga>-wetten`` ist fertig gerendertes HTML mit
Web-Components: je Spiel ein ``<ace-betting-match-entry>`` mit ``data-eventid``,
``data-expiremillis`` (Anstoß in ms), ``first-participant``/``second-participant`` (JSON) und
``href`` (Spielseite). Darin Spalten-Slots mit ``data-filterkey``:

* ``TXT_WHO_WILL_WIN``: drei Buttons label 1/X/2, Quote in ``odd`` („1,07“),
* ``TAB_GOALCOUNT``: erster Button label „Tore“ mit der Linie in ``odd`` („4,5“), danach
  „mehr“/„weniger“ mit Quoten.

``parse_league_page`` (reine Funktion, Test mit tests/fixtures/tipp3_sample.html) macht daraus
NormalizedEvents. Der Collector lädt die Seite über ``collectors.page_capture``.
"""
from __future__ import annotations

import html as htmllib
import json
import logging
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

SOURCE = "tipp3"
BOOKMAKER_SOURCE_KEY = "tipp3"
ORIGIN = "https://www.tipp3.at"

LEAGUES: dict[str, tuple[str, str]] = {
    "soccer_germany_bundesliga": (f"{ORIGIN}/sport/fussball/deutschland/bundesliga-wetten", "Bundesliga"),
    "soccer_germany_bundesliga2": (f"{ORIGIN}/sport/fussball/deutschland/2-bundesliga-wetten", "2. Bundesliga"),
    "soccer_epl": (f"{ORIGIN}/sport/fussball/england/premier-league-wetten", "Premier League"),
}

_ENTRY = re.compile(r"<ace-betting-match-entry\b(.*?)</ace-betting-match-entry>", re.S)
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_SLOT = re.compile(r'<div slot="[\w-]+" data-filterkey="([A-Z_0-9]+)"[^>]*>(.*?)</div>', re.S)
_BUTTON = re.compile(r"<ace-betting-bet-button\b([^>]*)>", re.S)
H2H = {"1": "home", "X": "draw", "2": "away"}
TOTALS = {"mehr": "over", "weniger": "under"}


def _attrs(tag: str) -> dict[str, str]:
    return {k: htmllib.unescape(v) for k, v in _ATTR.findall(tag)}


def _num(s: str) -> Decimal | None:
    try:
        return Decimal(s.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


def parse_league_page(page: str, league_key: str, league_name: str) -> list[NormalizedEvent]:
    events: list[NormalizedEvent] = []
    seen: set[str] = set()
    for body in _ENTRY.findall(page):
        head, _, inner = body.partition(">")
        a = _attrs(head)
        ev_id, millis = a.get("data-eventid"), a.get("data-expiremillis")
        if not ev_id or not millis or ev_id in seen or a.get("state", "upcoming") != "upcoming":
            continue
        try:
            home = json.loads(a.get("first-participant", "{}"))["name"]
            away = json.loads(a.get("second-participant", "{}"))["name"]
        except (ValueError, KeyError, TypeError):
            continue
        seen.add(ev_id)
        ev = NormalizedEvent(
            source=SOURCE, source_id=ev_id, league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=home, away_name=away,
            start_time=datetime.fromtimestamp(int(millis) / 1000, tz=timezone.utc),
        )
        markets: list[NormalizedMarket] = []
        for key, slot in _SLOT.findall(inner):
            buttons = [_attrs(b) for b in _BUTTON.findall(slot)]
            if key == "TXT_WHO_WILL_WIN":
                quotes = [Quote(BOOKMAKER_SOURCE_KEY, H2H[b["label"]], p) for b in buttons
                          if b.get("label") in H2H and b.get("inactive") != "true" and b.get("locked") != "true"
                          and (p := _num(b.get("odd", ""))) and p > 1]
                if len({q.outcome for q in quotes}) == 3:
                    markets.append(NormalizedMarket("h2h", None, quotes))
            elif key == "TAB_GOALCOUNT":
                line = next((_num(b.get("odd", "")) for b in buttons if b.get("label") == "Tore"), None)
                quotes = [Quote(BOOKMAKER_SOURCE_KEY, TOTALS[b["label"]], p) for b in buttons
                          if b.get("label") in TOTALS and b.get("inactive") != "true" and b.get("locked") != "true"
                          and (p := _num(b.get("odd", ""))) and p > 1]
                if line is not None and len({q.outcome for q in quotes}) == 2:
                    markets.append(NormalizedMarket("totals", line, quotes))
        ev.markets = markets
        if a.get("href"):
            ev.links[BOOKMAKER_SOURCE_KEY] = ORIGIN + a["href"].split("?", 1)[0]
        events.append(ev)
    return events


class Tipp3Collector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("tipp3: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("tipp3: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        keys = list(self.leagues)
        caps = capture_pages([self.leagues[k][0] for k in keys], wait_s=4, capture_html=True)
        events: list[NormalizedEvent] = []
        for key, cap in zip(keys, caps):
            batch = [e for e in parse_league_page(cap.html, key, self.leagues[key][1]) if e.markets]
            log.info("tipp3 %s: %d Events, %d Quoten", key, len(batch), sum(e.quote_count for e in batch))
            events.extend(batch)
        return events
