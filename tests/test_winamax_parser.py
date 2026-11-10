import json
from decimal import Decimal
from pathlib import Path

from collectors.winamax import decode_socketio, parse_messages

FIX = json.loads((Path(__file__).parent / "fixtures" / "winamax_sample.json").read_text(encoding="utf-8"))


def events(with_ws: bool = False):
    msgs = decode_socketio([FIX["polling"]] + (FIX["ws"] if with_ws else []))
    return {e.source_id: e for e in parse_messages(msgs, "soccer_germany_bundesliga", 42, "Bundesliga")}


def test_decode_polling_and_ws():
    assert len(decode_socketio([FIX["polling"]])) == 1
    assert len(decode_socketio(FIX["ws"])) == 1            # „3probe“ ist kein Datenpaket


def test_tournament_filter_teams_time_link():
    evs = events()
    assert set(evs) == {"72513310", "72513312"}              # Spiel aus Turnier 41 fällt raus
    ev = evs["72513310"]
    assert ev.source == "winamax" and ev.home_name == "FC Bayern München" and ev.away_name == "1. FC Köln"
    assert ev.start_time.isoformat() == "2026-11-20T19:30:00+00:00"
    assert ev.links["winamax"] == "https://www.winamax.de/sportwetten/match/72513310"


def test_h2h_and_later_update():
    [h2h] = events()["72513310"].markets
    assert {q.outcome: q.price for q in h2h.quotes} == {
        "home": Decimal("1.08"), "draw": Decimal("11.5"), "away": Decimal("16")}
    [h2h] = events(with_ws=True)["72513310"].markets
    assert {q.outcome: q.price for q in h2h.quotes}["home"] == Decimal("1.1")   # Änderung per WebSocket
