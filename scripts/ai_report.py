"""KI-Auswertung (Phase 6): Treffer einordnen oder Wochenbericht schreiben.

    python scripts/ai_report.py --assess            # aktuelle Treffer priorisieren
    python scripts/ai_report.py --weekly            # Wochenbericht (Kontext: 7 Tage)
    python scripts/ai_report.py --context           # nur den Kontext als JSON ausgeben (ohne KI, ohne Kosten)
    python scripts/ai_report.py --weekly --out docs/berichte/woche.md
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db
from engine import ai


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--assess", action="store_true", help="aktuelle Treffer einordnen")
    g.add_argument("--weekly", action="store_true", help="Wochenbericht")
    g.add_argument("--context", action="store_true", help="nur Kontext-JSON ausgeben")
    ap.add_argument("--hours", type=int, help="Zeitfenster in Stunden (Standard 24 bzw. 168)")
    ap.add_argument("--out", help="Ausgabe zusätzlich in diese Datei schreiben")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    hours = args.hours or (168 if args.weekly else 24)

    with db.connect() as conn:
        ctx = ai.build_context(conn, hours=hours)
        if args.context:
            text = json.dumps(ctx, ensure_ascii=False, indent=1)
            print(text)
        elif args.assess:
            result, resp = ai.assess_opportunities(ctx)
            text = result.model_dump_json(indent=1)
            ai.save_report(conn, "assessment", text, resp, hours)
            print(f"\n{result.summary}\n")
            for p in sorted(result.picks, key=lambda p: p.priority):
                print(f"  [{p.priority}] {p.event} · {p.bookmaker} · {p.market} {p.outcome}\n      {p.reason}")
                for r in p.risks:
                    print(f"      ⚠ {r}")
            for w in result.warnings:
                print(f"  ⚠ {w}")
            for s in result.suggested_settings:
                print(f"  → {s}")
        else:
            text, resp = ai.weekly_report(ctx)
            ai.save_report(conn, "weekly", text, resp, hours)
            print(text)
        if not args.context:
            u = resp.usage
            print(f"\n[{resp.model}: {u.input_tokens} Eingabe-, {u.output_tokens} Ausgabe-Tokens]")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"gespeichert: {args.out}")


if __name__ == "__main__":
    main()
