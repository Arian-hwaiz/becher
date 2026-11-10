"""Scraper für bwin (ohne Login).

Die Ligaseite von bwin lädt ihre Spiele selbst als JSON
(``/sports/api/widget/widgetdata?page=CompetitionLobby…``). Ohne Browser-Sitzung liefert dieselbe
Adresse nur HTML, deshalb öffnet der Collector die Ligaseite in Playwright
(``collectors.page_capture``) und liest die Antwort mit, die die Seite ohnehin lädt.

``parse_fixtures`` (reine Funktion, Test mit tests/fixtures/bwin_sample.json) macht daraus
NormalizedEvents:

* h2h: Markt „Spielresultat“ (isMain), Ausgänge über ``fixtureParticipant`` bzw. „X“,
* totals: Markt „Gesamtanzahl Tore“, Linie aus ``attr`` („2,5“ → 2.5), Ausgänge Over/Under,
* Direkt-Link: Link der Ligaseite auf ``/sports/events/…-<Fixture-ID>``.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import quote

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

SOURCE = "bwin"
BOOKMAKER_SOURCE_KEY = "bwin"
BASE = "https://www.bwin.de/de/sports/fu%C3%9Fball-4/wetten"

# Odds-API-Ligaschlüssel → (Ligaseite bei bwin, Anzeigename)
LEAGUES: dict[str, tuple[str, str]] = {
    "soccer_germany_bundesliga": (f"{BASE}/deutschland-17/bundesliga-102842", "Bundesliga"),
    "soccer_germany_bundesliga2": (f"{BASE}/deutschland-17/2-bundesliga-102845", "2. Bundesliga"),
    "soccer_epl": (f"{BASE}/england-14/premier-league-102841", "Premier League"),
}

H2H_NAMES = {"Spielresultat", "Ergebnis", "1X2"}
TOTALS_NAMES = {"Gesamtanzahl Tore", "Tore Über/Unter", "Über/Unter"}


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _text(v: Any) -> str:
    return (v or {}).get("value", "") if isinstance(v, dict) else str(v or "")


def _line(attr: Any) -> Decimal | None:
    try:
        return Decimal(str(attr).replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        return None


def find_fixtures(payload: Any) -> list[dict[str, Any]]:
    """Sucht alle Fixture-Listen in der widgetdata-Antwort (Aufbau kann je Seite leicht variieren)."""
    found: dict[str, dict[str, Any]] = {}

    def walk(o: Any, depth: int = 0) -> None:
        if depth > 14:
            return
        if isinstance(o, dict):
            fx = o.get("fixtures")
            if isinstance(fx, list) and fx and isinstance(fx[0], dict) and "participants" in fx[0]:
                for f in fx:
                    found.setdefault(str(f.get("id")), f)
            for v in o.values():
                walk(v, depth + 1)
        elif isinstance(o, list):
            for v in o:
                walk(v, depth + 1)

    walk(payload)
    return list(found.values())


def _slug(home: str, away: str) -> str:
    s = f"{home} {away}".lower().replace(".", "")
    return re.sub(r"[^\w]+", "-", s, flags=re.UNICODE).strip("-")


def _event_link(fixture_id: str, home: str, away: str, links: Iterable[str]) -> str:
    """Link von der Ligaseite, sonst nach demselben Muster gebaut (bwin löst über die Fixture-ID auf)."""
    num = fixture_id.split(":")[-1]
    pat = re.compile(rf"/sports/events/[^?#]*-(?:\d+:)?{re.escape(num)}(?:[?#/]|$)")
    for href in links:
        if pat.search(href):
            return href
    return f"https://www.bwin.de/de/sports/events/{quote(_slug(home, away))}-{quote(fixture_id, safe=':')}"


def parse_fixtures(payload: Any, league_key: str, league_name: str,
                   links: Iterable[str] = ()) -> list[NormalizedEvent]:
    links = list(links)
    events: list[NormalizedEvent] = []
    for f in find_fixtures(payload):
        if f.get("stage") not in (None, "PreMatch") or not f.get("isOpenForBetting", True):
            continue
        parts = {(p.get("properties") or {}).get("type"): p for p in f.get("participants", [])}
        home, away = parts.get("HomeTeam"), parts.get("AwayTeam")
        if not home or not away:
            continue
        ev = NormalizedEvent(
            source=SOURCE, source_id=str(f["id"]), league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=_text(home["name"]), away_name=_text(away["name"]),
            start_time=_ts(f["startDate"]),
        )
        markets: dict[tuple[str, Decimal | None], NormalizedMarket] = {}
        for m in f.get("optionMarkets", []):
            name = _text(m.get("name"))
            opts = [o for o in m.get("options", []) if o.get("status", "Visible") == "Visible"]
            if name in H2H_NAMES and m.get("isMain", True):
                for o in opts:
                    pid = (o.get("parameters") or {}).get("fixtureParticipant")
                    if pid == home["id"]:
                        outcome = "home"
                    elif pid == away["id"]:
                        outcome = "away"
                    elif _text(o.get("name")) == "X" or _text(o.get("sourceName")) == "X":
                        outcome = "draw"
                    else:
                        continue
                    nm = markets.setdefault(("h2h", None), NormalizedMarket("h2h", None))
                    nm.quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, Decimal(str(o["price"]["odds"]))))
            elif name in TOTALS_NAMES:
                line = _line(m.get("attr"))
                if line is None:
                    continue
                for o in opts:
                    types = (o.get("parameters") or {}).get("optionTypes") or []
                    outcome = "over" if "Over" in types else "under" if "Under" in types else None
                    if outcome is None:
                        continue
                    nm = markets.setdefault(("totals", line), NormalizedMarket("totals", line))
                    nm.quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, Decimal(str(o["price"]["odds"]))))
        ev.markets = [m for m in markets.values() if len(m.quotes) >= 2]
        ev.links[BOOKMAKER_SOURCE_KEY] = _event_link(ev.source_id, ev.home_name, ev.away_name, links)
        events.append(ev)
    return events


class BwinCollector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("bwin: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("bwin: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        keys = list(self.leagues)
        caps = capture_pages([self.leagues[k][0] for k in keys],
                             want_response=lambda u: "widgetdata" in u and "CompetitionLobby" in u,
                             link_contains="/sports/events/")
        events: list[NormalizedEvent] = []
        for key, cap in zip(keys, caps):
            batch: dict[str, NormalizedEvent] = {}
            for _url, body in cap.responses:
                try:
                    payload = json.loads(body)
                except ValueError:
                    continue
                for ev in parse_fixtures(payload, key, self.leagues[key][1], [h for h, _ in cap.links]):
                    batch[ev.source_id] = ev
            log.info("bwin %s: %d Events, %d Quoten", key, len(batch), sum(e.quote_count for e in batch.values()))
            events.extend(batch.values())
        return events
