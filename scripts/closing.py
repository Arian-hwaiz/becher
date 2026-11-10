"""Schlussquoten sichern und CLV für eigene Wetten berechnen.

    python scripts/closing.py            # beides
    python scripts/closing.py --report   # zusätzlich CLV-Auswertung ausgeben
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db
from engine import account_health, method_eval
from engine.clv import capture_closing_odds, update_bets_clv


def report(conn) -> None:
    rows = conn.execute(
        """SELECT k.name, count(*) AS n, sum(b.stake) AS stake, sum(coalesce(b.payout, 0) - CASE WHEN b.result='open' THEN 0 ELSE b.stake END) AS profit,
                  avg(b.clv) AS clv, count(b.clv) AS n_clv
           FROM bets b JOIN bookmakers k ON k.id = b.bookmaker_id GROUP BY k.name ORDER BY n DESC"""
    ).fetchall()
    print("\nWetten je Buchmacher:")
    for r in rows:
        clv = f"{r['clv']:+.2f} %" if r["clv"] is not None else "–"
        print(f"  {r['name']:<18} {r['n']:>4} Wetten  Einsatz {r['stake']:>9.2f}  Gewinn {r['profit']:>+9.2f}  Ø CLV {clv} ({r['n_clv']})")
    tot = conn.execute("SELECT count(*) AS n, avg(clv) AS clv, sum(CASE WHEN clv > 0 THEN 1 ELSE 0 END) AS pos FROM bets WHERE clv IS NOT NULL").fetchone()
    if tot["n"]:
        print(f"\nCLV gesamt: Ø {tot['clv']:+.2f} % über {tot['n']} Wetten, {tot['pos']} davon positiv ({tot['pos'] / tot['n'] * 100:.0f} %)")
    scores = method_eval.evaluate(conn)
    if scores:
        print("\nDevig-Methoden an abgerechneten Wetten (Brier/Log-Loss: kleiner = besser):")
        for m in scores:
            print(f"  {m.market_type:<8} {m.method:<15} n={m.n:<4} Brier {m.brier:.4f}  LogLoss {m.logloss:.4f}  Ø CLV {m.avg_clv:+.2f} % {'← Empfehlung' if m.recommended else ''}")
    health = account_health.evaluate(conn)
    if health:
        print("\nKonto-Risiko (0 unauffällig … 100 akut):")
        for h in health:
            print(f"  {h.bookmaker:<18} {h.score:>3} ({h.level}) · {h.bets} Wetten")
            for r in h.reasons:
                print(f"      • {r}")
            for t in h.tips:
                print(f"      💡 {t}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with db.connect() as conn:
        capture_closing_odds(conn)
        update_bets_clv(conn)
        if args.report:
            report(conn)


if __name__ == "__main__":
    main()
