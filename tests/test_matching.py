from datetime import datetime, timedelta, timezone

from engine.matching import EventKey, Team, TeamMatcher, find_event, normalize_name


def T(i, name):
    return Team(i, name, normalize_name(name))


def test_normalize_removes_noise_and_accents():
    assert normalize_name("FC Bayern München") == normalize_name("Bayern Munich")
    assert normalize_name("Borussia Mönchengladbach") == normalize_name("Gladbach") or "monchengladbach" in normalize_name("Gladbach")
    assert normalize_name("Manchester Utd") == normalize_name("Manchester United")
    assert normalize_name("1. FC Köln") == normalize_name("Cologne")
    assert normalize_name("Paris SG") == normalize_name("Paris Saint-Germain")


def test_exact_and_alias_match():
    m = TeamMatcher([T(1, "Bayern München"), T(2, "Borussia Dortmund")])
    r = m.match("odds_api", "FC Bayern Munich")
    assert r.team_id == 1 and r.method == "exact"
    m.add_alias("tipico", "Bayern", 1)
    r = m.match("tipico", "Bayern")
    assert r.team_id == 1 and r.method == "alias" and r.confidence == 1.0


def test_fuzzy_match_and_ambiguity():
    m = TeamMatcher([T(1, "Manchester United"), T(2, "Manchester City"), T(3, "Liverpool")])
    assert m.match("x", "Liverpool FC").team_id == 3
    r = m.match("x", "Man United")
    assert r.team_id == 1 and r.method in ("exact", "fuzzy")
    # "Manchester" allein ist mehrdeutig → kein Treffer
    r = m.match("x", "Manchester")
    assert r.team_id is None and r.method == "none"


def test_no_false_match_for_unrelated_name():
    m = TeamMatcher([T(1, "Bayern München"), T(2, "Borussia Dortmund")])
    r = m.match("x", "Real Madrid")
    assert r.team_id is None


def test_find_event_with_swap_and_tolerance():
    t0 = datetime(2026, 11, 10, 19, 30, tzinfo=timezone.utc)
    cands = [
        EventKey(10, 1, 2, t0),
        EventKey(11, 3, 4, t0),
        EventKey(12, 1, 2, t0 + timedelta(days=7)),
    ]
    assert find_event(1, 2, t0 + timedelta(minutes=15), cands) == (10, False)
    assert find_event(2, 1, t0, cands) == (10, True)
    assert find_event(1, 2, t0 + timedelta(hours=5), cands) == (None, False)
    assert find_event(1, 3, t0, cands) == (None, False)
