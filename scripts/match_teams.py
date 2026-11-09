"""Team-Matching nachziehen und prüfen.

    python scripts/match_teams.py            # Events ohne Team-IDs zuordnen, Bericht
    python scripts/match_teams.py --review   # nur unsichere Aliase (Konfidenz < 0.95) anzeigen
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db


def backfill(store: db.Store) -> int:
    rows = store.conn.execute(
        """SELECT e.id, e.home_name, e.away_name, l.sport_id, s.source
           FROM events e JOIN leagues l ON l.id=e.league_id
           JOIN event_source_ids s ON s.event_id=e.id
           WHERE e.home_team_id IS NULL OR e.away_team_id IS NULL"""
    ).fetchall()
    for r in rows:
        h = store.resolve_team(r["sport_id"], r["source"], r["home_name"])
        a = store.resolve_team(r["sport_id"], r["source"], r["away_name"])
        store.conn.execute("UPDATE events SET home_team_id=%s, away_team_id=%s WHERE id=%s", (h, a, r["id"]))
    return len(rows)


def review(store: db.Store) -> None:
    rows = store.conn.execute(
        """SELECT a.source, a.alias, t.name, a.confidence FROM team_aliases a JOIN teams t ON t.id=a.team_id
           WHERE a.confidence < 0.95 ORDER BY a.confidence"""
    ).fetchall()
    print(f"Unsichere Aliase: {len(rows)}")
    for r in rows:
        print(f"  {r['confidence']:.2f}  {r['source']:<10} {r['alias']!r:<35} → {r['name']!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--review", action="store_true")
    args = ap.parse_args()
    with db.connect() as conn:
        store = db.Store(conn)
        if not args.review:
            n = backfill(store)
            print(f"Events nachgezogen: {n}")
        teams = conn.execute("SELECT count(*) AS n FROM teams").fetchone()["n"]
        aliases = conn.execute("SELECT count(*) AS n FROM team_aliases").fetchone()["n"]
        print(f"Teams: {teams}, Aliase: {aliases}")
        review(store)


if __name__ == "__main__":
    main()
