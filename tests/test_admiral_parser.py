import json
import zlib
from decimal import Decimal
from pathlib import Path

from collectors.admiral import decode_frames, parse_snapshot

FIX = json.loads((Path(__file__).parent / "fixtures" / "admiral_sample.json").read_text(encoding="utf-8"))
BASE = "https://www.admiral.at/de/sports/sportwetten/fussball/deutschland/bundesliga"
LINKS = [BASE, f"{BASE}/bayern-muenchen-vs-1-fc-koeln?t=1795203", f"{BASE}/leverkusen-vs-paderborn?t=17952714",
         f"{BASE}/werder-vs-hsv?t=1795365"]


def events():
    return {e.source_id: e for e in parse_snapshot(FIX, "soccer_germany_bundesliga", "Bundesliga", LINKS)}


def _deflate(obj) -> bytes:
    c = zlib.compressobj(wbits=-15)
    return c.compress(json.dumps(obj).encode()) + c.flush()


def test_decode_frames_unpacks_nested_payload():
    inner = [{"type": "SportsbookSnapshotUpdated", "body": {}}]
    frames = [_deflate({"payload": json.dumps(inner), "properties": {"service": "sportsbook"}}),
              _deflate({"pong": {}}), b"kaputt"]
    assert decode_frames(frames) == inner


def test_only_main_competition_and_teams():
    evs = events()
    assert set(evs) == {"asw:event:17087197", "asw:event:17087198"}   # anderes Turnier fällt raus
    ev = evs["asw:event:17087197"]
    assert ev.source == "admiral" and ev.sport_key == "soccer"
    assert ev.home_name == "Bayern München" and ev.away_name == "1. FC Köln"
    assert ev.start_time.isoformat() == "2026-11-20T19:30:00+00:00"


def test_h2h_and_totals():
    ev = events()["asw:event:17087197"]
    h2h = next(m for m in ev.markets if m.type == "h2h")
    assert {q.outcome: q.price for q in h2h.quotes} == {
        "home": Decimal("1.08"), "draw": Decimal("12.0"), "away": Decimal("20.0")}
    tot = {m.line: {q.outcome: q.price for q in m.quotes} for m in ev.markets if m.type == "totals"}
    assert tot == {Decimal("2.5"): {"over": Decimal("1.15"), "under": Decimal("4.8")},
                   Decimal("3.5"): {"over": Decimal("1.45"), "under": Decimal("2.6")}}
    assert all(q.bookmaker_source_key == "admiral" for m in ev.markets for q in m.quotes)
    assert {m.type for m in ev.markets} == {"h2h", "totals"}            # „Wer erzielt das Tor“ ignoriert


def test_links_matched_by_team_names():
    evs = events()
    assert evs["asw:event:17087197"].links["admiral"] == LINKS[1]      # muenchen/koeln ↔ München/Köln
    assert evs["asw:event:17087198"].links["admiral"] == LINKS[2]      # Kurzformen in der Adresse
