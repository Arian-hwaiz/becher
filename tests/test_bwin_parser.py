import json
from decimal import Decimal
from pathlib import Path

from collectors.bwin import parse_fixtures

FIX = json.loads((Path(__file__).parent / "fixtures" / "bwin_sample.json").read_text(encoding="utf-8"))
LINKS = ["https://www.bwin.de/de/sports/events/fc-bayern-m%C3%BCnchen-1-fc-k%C3%B6ln-2:7906958",
         "https://www.bwin.de/de/sports/events/irgendwas-anderes-2:1234"]


def events():
    return {e.source_id: e for e in parse_fixtures(FIX, "soccer_germany_bundesliga", "Bundesliga", LINKS)}


def test_prematch_only_and_teams():
    evs = events()
    assert set(evs) == {"2:7906958", "2:7907847"}          # Live-Spiel 2:9999999 fällt raus
    ev = evs["2:7906958"]
    assert ev.source == "bwin" and ev.sport_key == "soccer" and ev.league_key == "soccer_germany_bundesliga"
    assert ev.home_name == "FC Bayern München" and ev.away_name == "1. FC Köln"
    assert ev.start_time.isoformat() == "2026-11-20T19:30:00+00:00"


def test_h2h_outcomes_by_participant():
    h2h = next(m for m in events()["2:7906958"].markets if m.type == "h2h")
    assert {q.outcome: q.price for q in h2h.quotes} == {
        "home": Decimal("1.11"), "draw": Decimal("11.0"), "away": Decimal("19.5")}
    assert all(q.bookmaker_source_key == "bwin" for q in h2h.quotes)


def test_totals_lines_and_ignored_markets():
    ev = events()["2:7906958"]
    tot = {m.line: {q.outcome: q.price for q in m.quotes} for m in ev.markets if m.type == "totals"}
    assert tot[Decimal("2.5")] == {"over": Decimal("1.2"), "under": Decimal("4.5")}
    assert set(tot) == {Decimal("2.5"), Decimal("3.5")}
    assert {m.type for m in ev.markets} == {"h2h", "totals"}   # Doppelte Chance ignoriert


def test_links_from_page_or_built_from_fixture_id():
    evs = events()
    assert evs["2:7906958"].links["bwin"] == LINKS[0]
    assert evs["2:7907847"].links["bwin"] == "https://www.bwin.de/de/sports/events/union-berlin-rb-leipzig-2:7907847"
