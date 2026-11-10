import json
from decimal import Decimal
from pathlib import Path

from collectors.betathome import entities, parse_entities

FRAMES = json.loads((Path(__file__).parent / "fixtures" / "betathome_sample.json").read_text(encoding="utf-8"))
LINK = ("https://sports2.bet-at-home.com/de/event/1/fu%C3%9Fball/ger/bundesliga/"
        "bayern-m%C3%BCnchen-1-fc-k%C3%B6ln/318770418102116352")


def events():
    by = entities(FRAMES)
    return {e.source_id: e for e in parse_entities(by, "soccer_germany_bundesliga", "Bundesliga", "Bundesliga",
                                                   "ger", [LINK])}


def test_only_requested_league():
    assert set(events()) == {"318770418102116352", "318771642676355072"}   # 3. Liga fällt raus


def test_teams_time_and_links():
    evs = events()
    ev = evs["318770418102116352"]
    assert ev.source == "betathome" and ev.home_name == "Bayern München" and ev.away_name == "1. FC Köln"
    assert ev.start_time.isoformat() == "2026-11-20T19:30:00+00:00"
    assert ev.links["betathome"] == LINK
    # ohne Link auf der Seite: nach demselben Muster gebaut
    assert evs["318771642676355072"].links["betathome"] == (
        "https://sports2.bet-at-home.com/de/event/1/fu%C3%9Fball/ger/bundesliga/union-berlin-rb-leipzig/318771642676355072")


def test_h2h_and_totals_regular_time():
    ev = events()["318770418102116352"]
    h2h = next(m for m in ev.markets if m.type == "h2h")
    assert {q.outcome: q.price for q in h2h.quotes} == {
        "home": Decimal("1.08"), "draw": Decimal("11.0"), "away": Decimal("19.0")}
    tot = [m for m in ev.markets if m.type == "totals"]
    assert [(m.line, {q.outcome: q.price for q in m.quotes}) for m in tot] == [
        (Decimal("4.5"), {"over": Decimal("2.05"), "under": Decimal("1.7")})]
    assert {m.type for m in ev.markets} == {"h2h", "totals"}       # „Beide Teams treffen“ ignoriert
