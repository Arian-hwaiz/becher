"""Scraper für Winamax (winamax.de, ohne Login).

Die Ligaseite holt ihre Daten über socket.io (``sports-*.winamax.de/uof-sports-server``). Die
erste große Nachricht ``42["m", {...}]`` enthält getrennte Tabellen ``matches``, ``bets``,
``outcomes`` und ``odds`` (Outcome-ID → Quote). Jedes Match verweist mit ``mainBetId`` auf
seinen 1X2-Markt („Ergebnis“, Outcome-Codes 1/x/2).

Der Collector öffnet die Ligaseite in Playwright und schneidet die socket.io-Antworten
(Polling und WebSocket) mit. ``parse_messages`` (reine Funktion, Test mit
tests/fixtures/winamax_sample.json) baut daraus NormalizedEvents mit 1X2 und Direkt-Link
``/sportwetten/match/<matchId>``. Weitere Märkte stehen erst auf der Spielseite.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from collectors.base import Collector
from collectors.page_capture import capture_pages, too_soon
from common.config import settings
from common.models import NormalizedEvent, NormalizedMarket, Quote

log = logging.getLogger(__name__)

SOURCE = "winamax"
BOOKMAKER_SOURCE_KEY = "winamax"
ORIGIN = "https://www.winamax.de"

# Odds-API-Ligaschlüssel → (Ligaseite, Turnier-ID bei Winamax, Anzeigename)
LEAGUES: dict[str, tuple[str, int, str]] = {
    "soccer_germany_bundesliga": (f"{ORIGIN}/sportwetten/sports/1/30/42", 42, "Bundesliga"),
    "soccer_germany_bundesliga2": (f"{ORIGIN}/sportwetten/sports/1/30/41", 41, "2. Bundesliga"),
    "soccer_epl": (f"{ORIGIN}/sportwetten/sports/1/1/1", 1, "Premier League"),
}
CODES = {"1": "home", "x": "draw", "2": "away"}


def decode_socketio(texts: Iterable[str | bytes]) -> list[dict[str, Any]]:
    """Findet in socket.io-Antworten (Polling „len:42[...]“ oder WebSocket „42[...]“) alle Daten-Objekte."""
    dec = json.JSONDecoder()
    out: list[dict[str, Any]] = []
    for t in texts:
        s = t.decode("utf-8", "replace") if isinstance(t, bytes) else t
        i = 0
        while (i := s.find("42[", i)) != -1:
            try:
                obj, end = dec.raw_decode(s, i + 2)
            except ValueError:
                i += 3
                continue
            if isinstance(obj, list) and len(obj) >= 2 and isinstance(obj[1], dict):
                out.append(obj[1])
            i = end
    return out


def parse_messages(messages: Iterable[dict[str, Any]], league_key: str, tournament_id: int,
                   league_name: str) -> list[NormalizedEvent]:
    matches: dict[str, dict] = {}
    bets: dict[str, dict] = {}
    outcomes: dict[str, dict] = {}
    odds: dict[str, Any] = {}
    for m in messages:          # spätere Nachrichten ergänzen frühere
        for k, v in (m.get("matches") or {}).items():
            matches.setdefault(str(k), {}).update(v)
        for k, v in (m.get("bets") or {}).items():
            bets.setdefault(str(k), {}).update(v)
        for k, v in (m.get("outcomes") or {}).items():
            outcomes.setdefault(str(k), {}).update(v)
        odds.update({str(k): v for k, v in (m.get("odds") or {}).items()})

    events: list[NormalizedEvent] = []
    for mid, mt in matches.items():
        if mt.get("tournamentId") != tournament_id or mt.get("status") != "PREMATCH" or not mt.get("available", True):
            continue
        ev = NormalizedEvent(
            source=SOURCE, source_id=str(mt.get("matchId", mid)), league_key=league_key, league_name=league_name,
            sport_key=league_key.split("_", 1)[0], home_name=mt["competitor1Name"], away_name=mt["competitor2Name"],
            start_time=datetime.fromtimestamp(int(mt["matchStart"]), tz=timezone.utc),
        )
        bet = bets.get(str(mt.get("mainBetId")))
        quotes = []
        if bet and bet.get("available", True) and bet.get("template") == "3way":
            for oid in bet.get("outcomes", []):
                oc = outcomes.get(str(oid), {})
                outcome = CODES.get(str(oc.get("code", "")).lower())
                price = odds.get(str(oid))
                if outcome and oc.get("available", True) and price and float(price) > 1:
                    quotes.append(Quote(BOOKMAKER_SOURCE_KEY, outcome, Decimal(str(price))))
        if len({q.outcome for q in quotes}) == 3:
            ev.markets = [NormalizedMarket("h2h", None, quotes)]
        ev.links[BOOKMAKER_SOURCE_KEY] = f"{ORIGIN}/sportwetten/match/{ev.source_id}"
        events.append(ev)
    return events


class WinamaxCollector(Collector):
    source = SOURCE

    def __init__(self, leagues: list[str] | None = None):
        keys = leagues or settings.scrape_league_list
        self.leagues = {k: LEAGUES[k] for k in keys if k in LEAGUES}
        unknown = [k for k in keys if k not in LEAGUES]
        if unknown:
            log.warning("winamax: Ligen ohne bekannte Seite übersprungen: %s", unknown)

    def fetch(self) -> list[NormalizedEvent]:
        if too_soon(SOURCE):
            log.info("winamax: letzter Lauf jünger als %d s, übersprungen", settings.scrape_interval_seconds)
            return []
        keys = list(self.leagues)
        caps = capture_pages([self.leagues[k][0] for k in keys], capture_ws=True, wait_s=8,
                             want_response=lambda u: "uof-sports-server/socket.io" in u)
        events: list[NormalizedEvent] = []
        for key, cap in zip(keys, caps):
            msgs = decode_socketio([b for _, b in cap.responses] + list(cap.ws_frames))
            url, tid, name = self.leagues[key]
            batch = [e for e in parse_messages(msgs, key, tid, name) if e.markets]
            log.info("winamax %s: %d Events, %d Quoten", key, len(batch), sum(e.quote_count for e in batch))
            events.extend(batch)
        return events
