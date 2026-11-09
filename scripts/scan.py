"""Opportunity-Scan über die Datenbank laufen lassen und Treffer anzeigen.

    python scripts/scan.py                 # scannen, speichern, anzeigen
    python scripts/scan.py --dry-run       # nur anzeigen
    python scripts/scan.py --method shin --min-ev 0.01
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db
from engine.scan import ScanConfig, run_scan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--method", default="power", help="Devig-Methode: multiplicative, additive, power, shin, logit")
    ap.add_argument("--min-ev", type=float, default=0.0, help="Schwelle für konservativen EV, z. B. 0.02")
    ap.add_argument("--max-age", type=int, default=600, help="maximales Quotenalter in Sekunden")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = ScanConfig(method=args.method, min_ev=args.min_ev, max_age_s=args.max_age)
    with db.connect() as conn:
        found = run_scan(conn, cfg, write=not args.dry_run)
        names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM bookmakers").fetchall()}
        info = {
            r["id"]: r for r in conn.execute(
                """SELECT m.id, m.type, m.line, e.home_name, e.away_name, e.start_time
                   FROM markets m JOIN events e ON e.id=m.event_id"""
            ).fetchall()
        }
        for o in sorted(found, key=lambda o: -(o.ev_conservative or 0)):
            m = info[o.market_id]
            head = f"{m['start_time']:%d.%m %H:%M} {m['home_name']} - {m['away_name']} [{m['type']}{' ' + str(m['line']) if m['line'] is not None else ''}]"
            if o.kind == "value":
                print(f"VALUE {o.ev_conservative*100:5.2f}% (EV {o.ev*100:5.2f}%)  {head}  {o.outcome} @ {o.price} "
                      f"{names.get(o.bookmaker_id)}  fair {o.fair_price}  Ref-Alter {o.reference_age_s}s")
            else:
                legs = ", ".join(f"{l['outcome']} @ {l['price']} {names.get(l['bookmaker_id'])}" for l in o.details["legs"])
                print(f"ARB   {o.details['percent']:5.2f}%  {head}  {legs}")


if __name__ == "__main__":
    main()
