"""Scraper für ADMIRAL Sportwetten Österreich (admiral.at, ohne Login).

Die Ligaseite holt Spiele und Quoten über einen WebSocket (``wss://widget-ws.admiral.at``). Jeder
Frame ist einzeln per Deflate (ohne Header) komprimiertes JSON; die Quoten stecken in
``SportsbookSnapshotUpdated``-Nachrichten als Liste von Entitäten (Event, Competitor, Market,
Selection, …), die sich über ``urn`` gegenseitig referenzieren.

Ablauf: ``collectors.page_capture`` öffnet die Ligaseite in Playwright und schneidet die
empfangenen Frames und die Spiel-Links mit. ``decode_frames`` entpackt die Frames,
``parse_snapshot`` (reine Funktion, Test mit tests/fixtures/admiral_sample.json) baut daraus
NormalizedEvents:

* h2h: Markttyp ``asw:markettype:1`` (1x2), Auswahl 1/2/3 → home/draw/away,
* totals: Markttyp ``asw:markettype:18``, Linie aus ``properties.total``, Auswahl 12/13 → over/under,
* Direkt-Link: Link der Ligaseite ``…/<heim>-vs-<gast>?t=…``, über die Teamnamen zugeordnet.
"""
from __future__ import annotations

import json
import logging
import zlib
from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable
from urllib.parse import urlparse

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote
from engine.matching import normalize_name

log = logging.getLogger(__name__)

SOURCE = "admiral"
BOOKMAKER_SOURCE_KEY = "admiral"
BASE = "https://www.admiral.at/de/sports/sportwetten/fussball"

LEAGUES: dict[str, tuple[str, str]] = {
    "soccer_germany_bundesliga": (f"{BASE}/deutschland/bundesliga", "Bundesliga"),
    "soccer_germany_bundesliga2": (f"{BASE}/deutschland/2-bundesliga", "2. Bundesliga"),
    "soccer_epl": (f"{BASE}/england/premier-league", "Premier League"),
}

MT_1X2 = "asw:markettype:1"
MT_TOTAL = "asw:markettype:18"
SEL = {"asw:selectiontype:1": "home", "asw:selectiontype:2": "draw", "asw:selectiontype:3": "away",
       "asw:selectiontype:12": "over", "asw:selectiontype:13": "under"}


def decode_frames(frames: Iterable[bytes | str]) -> list[dict[str, Any]]:
    """Entpackt WebSocket-Frames und gibt alle Nachrichten (``payload``-Einträge) zurück."""
    out: list[dict[str, Any]] = []
    for fr in frames:
        try:
            raw = fr.encode() if isinstance(fr, str) else zlib.decompressobj(-15).decompress(fr)
            msg = json.loads(raw)
        except (zlib.error, ValueError):
            continue
        payload = msg.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError:
                continue
        if isinstance(payload, list):
            out.extend(p for p in payload if isinstance(p, dict))
    return out


def snapshot_entities(messages: Iterable[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Typ → urn → Entität aus allen SportsbookSnapshotUpdated-Nachrichten (spätere überschreiben)."""
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for m in messages:
        if m.get("type") != "SportsbookSnapshotUpdated":
            continue
        for it in ((m.get("body") or {}).get("snapshotUpdate") or {}).get("snapshotUpdateItems", []):
            ent = it.get("entity") or {}
            if "urn" in ent:
                by.setdefault(it.get("type", ""), {})[ent["urn"]] = ent
    return by


def _name(ent: dict[str, Any]) -> str:
    return (ent.get("translations") or {}).get("de") or ent.get("name", "")


def _slug_part(s: str) -> str:
    # Umlaute stehen in der Adresse als ae/oe/ue ("osnabrueck"); für den Vergleich wie ohne Akzent schreiben
    s = s.replace("-", " ")
    for a, b in (("ae", "a"), ("oe", "o"), ("ue", "u")):
        s = s.replace(a, b)
    return normalize_name(s)


def _slug_teams(href: str) -> tuple[str, str] | None:
    last = urlparse(href).path.rstrip("/").rsplit("/", 1)[-1]
    if "-vs-" not in last:
        return None
    h, a = last.split("-vs-", 1)
    return _slug_part(h), _slug_part(a)


def _close(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ta = {t for t in a.split() if len(t) >= 3}
    tb = {t for t in b.split() if len(t) >= 3}
    return bool(ta & tb)


def _event_link(home: str, away: str, links: Iterable[str]) -> str | None:
    """Link, dessen Adresse beide Teams nennt; sonst der einzige Link, der wenigstens ein Team nennt."""
    nh = _slug_part(normalize_name(home))
    na = _slug_part(normalize_name(away))
    half: set[str] = set()
    for href in links:
        st = _slug_teams(href)
        if not st:
            continue
        score = _close(nh, st[0]) + _close(na, st[1])
        if score == 2:
            return href
        if score == 1:
            half.add(href.split("?", 1)[0])
    if len(half) == 1:
        prefix = half.pop()
        return next(h for h in links if h.split("?", 1)[0] == prefix)
    return None


def parse_snapshot(messages: Iterable[dict[str, Any]], league_key: str, league_name: str,
                   links: Iterable[str] = ()) -> list[NormalizedEvent]:
    by = snapshot_entities(messages)
    evs = [e for e in by.get("Event", {}).values() if e.get("state", 1) == 1 and e.get("type", 0) == 0]
    if not evs:
        return []
    # Die Ligaseite kann auch Top-Spiele anderer Ligen mitschicken: nur die häufigste Competition behalten
    comp, _ = Counter(e.get("competition") for e in evs).most_common(1)[0]
    competitors = by.get("Competitor", {})
    markets_by_urn = by.get("Market", {})
    selections = by.get("Selection", {})
    links = list(links)
    out: list[NormalizedEvent] = []
    for e in evs:
        if e.get("competition") != comp:
            continue
        side = {c.get("qualifier"): competitors.get(c.get("competitor"), {}) for c in e.get("eventCompetitors", [])}
        if not side.get("home") or not side.get("away"):
            continue
        ev = NormalizedEvent(
            source=SOURCE, source_id=e["urn"], league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=_name(side["home"]), away_name=_name(side["away"]),
            start_time=datetime.fromisoformat(e["startTime"].replace("Z", "+00:00")),
        )
        markets: dict[tuple[str, Decimal | None], NormalizedMarket] = {}
        for mu in e.get("markets", []):
            m = markets_by_urn.get(mu)
            if not m or m.get("state", 1) != 1:
                continue
            if m.get("type") == MT_1X2 and (m.get("properties") or {}).get("IsMainMarket", True):
                key = ("h2h", None)
            elif m.get("type") == MT_TOTAL and (m.get("properties") or {}).get("total") is not None:
                key = ("totals", Decimal(str(m["properties"]["total"])))
            else:
                continue
            for su in m.get("selections", []):
                s = selections.get(su)
                outcome = SEL.get((s or {}).get("type"))
                if not s or outcome is None or s.get("state", 1) != 1 or not s.get("odds"):
                    continue
                nm = markets.setdefault(key, NormalizedMarket(key[0], key[1]))
                nm.quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, Decimal(str(s["odds"]))))
        ev.markets = [m for m in markets.values() if len(m.quotes) >= 2]
        link = _event_link(ev.home_name, ev.away_name, links)
        if link:
            ev.links[BOOKMAKER_SOURCE_KEY] = link
        out.append(ev)
    return out


class AdmiralCollector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("admiral: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("admiral: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        keys = list(self.leagues)
        caps = capture_pages([self.leagues[k][0] for k in keys], capture_ws=True, wait_s=10,
                             link_contains="/sportwetten/fussball/")
        events: list[NormalizedEvent] = []
        for key, cap in zip(keys, caps):
            batch = parse_snapshot(decode_frames(cap.ws_frames), key, self.leagues[key][1],
                                   [h for h, _ in cap.links])
            log.info("admiral %s: %d Events, %d Quoten, %d Direkt-Links", key, len(batch),
                     sum(e.quote_count for e in batch), sum(1 for e in batch if e.links))
            events.extend(batch)
        return events
