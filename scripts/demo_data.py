"""Demo-Daten erzeugen, um Dashboard und Scan ohne API-Key auszuprobieren.

    python scripts/demo_data.py          # legt 6 Beispiel-Events mit Quoten an und scannt
    python scripts/demo_data.py --clear  # löscht die Demo-Events wieder

Die Quoten sind erfunden, aber realistisch verteilt; einige enthalten absichtlich Value und Surebets.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # Projektwurzel importierbar machen

from common import db
from common.models import NormalizedEvent, NormalizedMarket, Quote
from engine.scan import ScanConfig, run_scan

SOURCE = "demo"
BOOKS = ["pinnacle", "betfair_ex_eu", "bet365", "tipico_de", "bwin", "betano", "unibet_eu"]
EVENTS = [
    ("soccer", "soccer_germany_bundesliga", "Bundesliga", "FC Bayern München", "Borussia Dortmund", (1.75, 4.0, 4.4)),
    ("soccer", "soccer_germany_bundesliga", "Bundesliga", "VfB Stuttgart", "SC Freiburg", (2.3, 3.5, 3.1)),
    ("soccer", "soccer_epl", "Premier League", "Liverpool", "Arsenal", (2.1, 3.6, 3.4)),
    ("soccer", "soccer_spain_la_liga", "La Liga", "Real Madrid", "Sevilla", (1.45, 4.8, 7.0)),
    ("basketball", "basketball_nba", "NBA", "Boston Celtics", "Miami Heat", (1.55, None, 2.5)),
    ("tennis", "tennis_atp", "ATP Paris", "Alexander Zverev", "Carlos Alcaraz", (2.6, None, 1.5)),
]


def _market(mtype: str, line, fair: list[float | None], outcomes: list[str], rng: random.Random, ts: datetime) -> NormalizedMarket:
    m = NormalizedMarket(mtype, Decimal(str(line)) if line is not None else None)
    for bk in BOOKS:
        margin = 0.02 if bk == "pinnacle" else 0.0 if bk == "betfair_ex_eu" else rng.uniform(0.05, 0.08)
        for oc, f in zip(outcomes, fair):
            if f is None:
                continue
            p = 1.0 / f
            price = 1.0 / (p * (1 + margin))
            price *= rng.uniform(0.97, 1.03) if bk not in ("pinnacle", "betfair_ex_eu") else 1.0
            if bk == "tipico_de" and oc == outcomes[0] and rng.random() < 0.6:
                price *= 1.25  # absichtlich Value (reicht auch nach 5,3 % Steuer und Unsicherheitsabschlag)
            if bk == "bwin" and oc == outcomes[-1] and rng.random() < 0.4:
                price *= 1.22  # ergibt zusammen mit anderen Quoten gelegentlich eine Surebet
            m.quotes.append(Quote(bk, oc, Decimal(f"{price:.2f}"), ts))
    return m


def build(rng: random.Random, now: datetime) -> list[NormalizedEvent]:
    out = []
    for i, (sport, lkey, lname, home, away, (h, d, a)) in enumerate(EVENTS):
        start = now + timedelta(hours=6 + 5 * i)
        ev = NormalizedEvent(SOURCE, f"demo-{i}", lkey, lname, sport, home, away, start)
        outcomes = ["home", "draw", "away"] if d else ["home", "away"]
        ev.markets.append(_market("h2h", None, [h, d, a] if d else [h, a], outcomes, rng, now))
        tot_line = {"soccer": 2.5, "basketball": 215.5, "tennis": 22.5}[sport]
        ev.markets.append(_market("totals", tot_line, [1.9, 1.9], ["over", "under"], rng, now))
        if sport != "tennis":
            ev.markets.append(_market("spreads", -1.5 if sport == "soccer" else -4.5, [2.6, 1.5] if sport == "soccer" else [1.9, 1.9],
                                      ["home", "away"], rng, now))
        out.append(ev)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    with db.connect() as conn:
        if args.clear:
            n = conn.execute("DELETE FROM events WHERE id IN (SELECT event_id FROM event_source_ids WHERE source=%s)", (SOURCE,)).rowcount
            print(f"{n} Demo-Events gelöscht.")
            return
        for bk in BOOKS:  # Demo nutzt die Odds-API-Schlüssel
            conn.execute("INSERT INTO bookmaker_source_keys (source, source_key, bookmaker_id) "
                         "SELECT %s, source_key, bookmaker_id FROM bookmaker_source_keys WHERE source='odds_api' AND source_key=%s "
                         "ON CONFLICT DO NOTHING", (SOURCE, bk))
        now = datetime.now(timezone.utc)
        store = db.Store(conn)
        n_ev, n_q = store.save_events(build(random.Random(args.seed), now), observed_at=now)
        store.log_run(SOURCE, now, True, n_ev, n_q)
        # Börsenliquidität für die Demo setzen, damit Betfair als Referenz zählt
        conn.execute("UPDATE odds_snapshots SET liquidity=8000 WHERE source=%s AND bookmaker_id=(SELECT id FROM bookmakers WHERE key='betfair_ex')", (SOURCE,))
        found = run_scan(conn, ScanConfig(method="power"), now=now)
        print(f"{n_ev} Events, {n_q} Quoten, {len(found)} Treffer ({sum(o.kind == 'value' for o in found)} Value, "
              f"{sum(o.kind == 'arb' for o in found)} Surebets). Dashboard: streamlit run dashboard/app.py")


if __name__ == "__main__":
    main()
