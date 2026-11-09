"""Kurzer Statusbericht: letzte Läufe, Quoten der letzten Stunde, Buchmacher-Abdeckung.

    python scripts/status.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db


def main() -> None:
    with db.connect() as conn:
        runs = conn.execute(
            "SELECT source, started_at, ok, events, snapshots, error FROM collector_runs ORDER BY started_at DESC LIMIT 5"
        ).fetchall()
        print("Letzte Läufe:")
        for r in runs:
            state = "ok" if r["ok"] else f"FEHLER {r['error']}"
            print(f"  {r['started_at']:%Y-%m-%d %H:%M} {r['source']:<10} {r['events']:>4} Events {r['snapshots']:>6} Quoten  {state}")

        cov = conn.execute(
            """SELECT b.name, count(*) AS n, max(o.observed_at) AS last
               FROM odds_snapshots o JOIN bookmakers b ON b.id=o.bookmaker_id
               WHERE o.observed_at > now() - interval '1 hour'
               GROUP BY b.name ORDER BY n DESC"""
        ).fetchall()
        print("\nQuoten der letzten Stunde je Buchmacher:")
        for c in cov:
            print(f"  {c['name']:<18} {c['n']:>6}  zuletzt {c['last']:%H:%M}")

        ev = conn.execute(
            "SELECT count(*) AS n FROM events WHERE start_time > now()"
        ).fetchone()["n"]
        print(f"\nKommende Events in der Datenbank: {ev}")


if __name__ == "__main__":
    main()
