from decimal import Decimal
from pathlib import Path

from collectors.interwetten import parse_league_page

PAGE = (Path(__file__).parent / "fixtures" / "interwetten_sample.html").read_text(encoding="utf-8")


def events():
    return {e.source_id: e for e in parse_league_page(PAGE, "soccer_germany_bundesliga", "Bundesliga")}


def test_matches_only_no_outrights():
    assert set(events()) == {"18973779", "18973780"}       # Langzeitwette „Bundesliga 2026/27“ fällt raus


def test_teams_start_time_vienna_and_link():
    ev = events()["18973779"]
    assert ev.source == "interwetten" and ev.sport_key == "soccer"
    assert ev.home_name == "Bayern München" and ev.away_name == "1. FC Köln"
    assert ev.start_time.isoformat() == "2026-11-20T20:30:00+01:00"   # Ortszeit Wien = 19:30 UTC
    assert ev.links["interwetten"] == "https://www.interwetten.com/de/sportwetten/e/18973779/bayern-munchen-1-fc-koln"


def test_h2h_quotes():
    ev = events()["18973780"]
    [h2h] = ev.markets
    assert h2h.type == "h2h" and h2h.line is None
    assert {q.outcome: q.price for q in h2h.quotes} == {
        "home": Decimal("1.27"), "draw": Decimal("6.50"), "away": Decimal("9.00")}
    assert all(q.bookmaker_source_key == "interwetten" for q in h2h.quotes)
