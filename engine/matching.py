"""Team- und Event-Matching (Phase 2).

Jeder Buchmacher schreibt Teamnamen anders ("Bayern München", "FC Bayern Munich", "Bayern").
Damit Quoten verschiedener Quellen auf dasselbe Event fallen, braucht es

1. eine kanonische Team-Tabelle (``teams``),
2. Aliase je Quelle (``team_aliases``) mit Konfidenz (1.0 = bestätigt, <1 = automatisch),
3. ein Fuzzy-Matching für neue Schreibweisen,
4. ein Event-Matching: gleiche Sportart, beide Teams gleich (auch vertauscht → ``swap_teams``),
   Anstoß innerhalb einer Toleranz.

Die Logik hier ist reine Python-Logik ohne Datenbank, damit sie testbar bleibt. Die
Datenbank-Anbindung steht in ``common.db.Store`` (``resolve_teams``, ``find_matching_event``).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

try:  # rapidfuzz ist schnell und gut; difflib als Notnagel
    from rapidfuzz import fuzz as _fuzz

    def _ratio(a: str, b: str) -> float:
        return float(_fuzz.token_set_ratio(a, b))

except ImportError:  # pragma: no cover
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0


# Wörter ohne Unterscheidungskraft. Reihenfolge egal, Vergleich auf Token-Ebene.
STOPWORDS = {
    "fc", "cf", "sc", "afc", "ac", "as", "ss", "ssc", "us", "sv", "vfb", "vfl", "tsv", "tsg", "bsc", "fsv",
    "sg", "spvgg", "rb", "bk", "if", "fk", "nk", "hk", "sk", "kv", "rc", "cd", "ud", "sd", "ca", "cs",
    "club", "clube", "de", "del", "der", "die", "the", "la", "le", "los", "las", "el", "al", "do", "da",
    "futebol", "futbol", "football", "calcio", "sport", "sports", "sporting", "team", "women", "w",
    "u19", "u20", "u21", "u23", "ii", "b", "reserves", "res", "amateure", "amateurs", "ladies", "fem",
}

# Häufige Abkürzungen / Sprachvarianten → eine Schreibweise
REPLACEMENTS = {
    "utd": "united",
    "munich": "munchen",
    "muenchen": "munchen",
    "koeln": "koln",
    "cologne": "koln",
    "nuernberg": "nurnberg",
    "nuremberg": "nurnberg",
    "moenchengladbach": "monchengladbach",
    "gladbach": "monchengladbach",
    "st": "saint",
    "st.": "saint",
    "inter": "internazionale",
    "man": "manchester",
    "wolves": "wolverhampton",
    "spurs": "tottenham",
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "athletico": "atletico",
    "real sociedad": "sociedad",
}

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")


def strip_accents(s: str) -> str:
    s = s.replace("ß", "ss")
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Kanonische Vergleichsform: klein, ohne Akzente/Satzzeichen, ohne Füllwörter, Token sortiert."""
    s = strip_accents(name).lower().strip()
    s = s.replace("-", " ").replace("/", " ")
    s = _PUNCT.sub(" ", s)
    s = _SPACES.sub(" ", s).strip()
    # Mehrwort-Ersetzungen zuerst
    for k, v in sorted(REPLACEMENTS.items(), key=lambda kv: -len(kv[0])):
        if " " in k:
            s = re.sub(rf"\b{re.escape(k)}\b", v, s)
    tokens = []
    for t in s.split():
        t = REPLACEMENTS.get(t, t)
        tokens.extend(t.split())
    tokens = [t for t in tokens if t not in STOPWORDS and not t.isdigit()]
    if not tokens:  # z. B. "FC" allein → Original behalten
        tokens = s.split() or [s]
    return " ".join(sorted(set(tokens)))


@dataclass(frozen=True)
class Team:
    id: int
    name: str                 # kanonischer Name
    normalized: str


@dataclass(frozen=True)
class Match:
    team_id: int | None
    confidence: float         # 0..1
    method: str               # alias | exact | fuzzy | none
    candidate: str | None = None


class TeamMatcher:
    """Hält Teams und Aliase einer Sportart im Speicher und ordnet Rohnamen zu."""

    def __init__(self, teams: Iterable[Team], aliases: dict[tuple[str, str], int] | None = None,
                 fuzzy_threshold: float = 88.0, ambiguity_gap: float = 4.0):
        self.teams: dict[int, Team] = {t.id: t for t in teams}
        self.by_normalized: dict[str, int] = {}
        for t in self.teams.values():
            self.by_normalized.setdefault(t.normalized, t.id)
        self.aliases: dict[tuple[str, str], int] = dict(aliases or {})
        self.fuzzy_threshold = fuzzy_threshold
        self.ambiguity_gap = ambiguity_gap

    # ---- Pflege ---------------------------------------------------------

    def add_team(self, team: Team) -> None:
        self.teams[team.id] = team
        self.by_normalized.setdefault(team.normalized, team.id)

    def add_alias(self, source: str, alias: str, team_id: int) -> None:
        self.aliases[(source, alias)] = team_id

    # ---- Matching -------------------------------------------------------

    def match(self, source: str, raw_name: str) -> Match:
        if (source, raw_name) in self.aliases:
            return Match(self.aliases[(source, raw_name)], 1.0, "alias", raw_name)
        norm = normalize_name(raw_name)
        if norm in self.by_normalized:
            tid = self.by_normalized[norm]
            return Match(tid, 0.98, "exact", self.teams[tid].name)
        if not self.teams:
            return Match(None, 0.0, "none")
        scored = sorted(
            ((_ratio(norm, t.normalized), t) for t in self.teams.values()),
            key=lambda x: -x[0],
        )
        best_score, best = scored[0]
        second = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= self.fuzzy_threshold and best_score - second >= self.ambiguity_gap:
            return Match(best.id, round(best_score / 100.0, 3), "fuzzy", best.name)
        return Match(None, round(best_score / 100.0, 3), "none", best.name)


@dataclass(frozen=True)
class EventKey:
    event_id: int
    home_team_id: int | None
    away_team_id: int | None
    start_time: datetime


def find_event(home_id: int, away_id: int, start_time: datetime, candidates: Iterable[EventKey],
               tolerance: timedelta = timedelta(hours=2)) -> tuple[int | None, bool]:
    """Sucht unter ``candidates`` das Event mit denselben Teams. Gibt (event_id, swap_teams) zurück."""
    best: tuple[timedelta, int, bool] | None = None
    for c in candidates:
        if c.home_team_id is None or c.away_team_id is None:
            continue
        if {c.home_team_id, c.away_team_id} != {home_id, away_id}:
            continue
        delta = abs(c.start_time - start_time)
        if delta > tolerance:
            continue
        swap = c.home_team_id != home_id
        if best is None or delta < best[0]:
            best = (delta, c.event_id, swap)
    return (best[1], best[2]) if best else (None, False)
