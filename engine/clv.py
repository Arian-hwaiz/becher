"""Schlussquoten und CLV (Closing Line Value).

* ``select_closing``: aus der Quoten-Zeitreihe eines Marktes die letzte Quote je Buchmacher und
  Ausgang vor dem Anstoß (Schlussquote). Reine Funktion.
* ``clv_percent``: Vorteil der eigenen Wettquote gegenüber der fairen Schlussquote der
  Referenz (devigged). Positiv = besser als der Markt zum Schluss.
* ``settle``: Auszahlung einer Wette aus Ergebnis und Quote.
* ``capture_closing_odds`` / ``update_bets_clv``: Datenbank-Anbindung (Phase 5).

CLV ist die einzige ehrliche Erfolgsmessung (docs/konzept/05): wer über viele Wetten positiven
CLV hat, hat eine echte Kante, unabhängig vom kurzfristigen Ergebnis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from engine import devig as dv

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snap:
    bookmaker_id: int
    outcome: str
    price: float
    observed_at: datetime


def select_closing(snaps: Iterable[Snap], start_time: datetime, max_before: timedelta = timedelta(hours=6)) -> list[Snap]:
    """Letzte Quote je (Buchmacher, Ausgang) vor Anstoß, höchstens ``max_before`` alt."""
    best: dict[tuple[int, str], Snap] = {}
    for s in snaps:
        if s.observed_at > start_time or start_time - s.observed_at > max_before:
            continue
        k = (s.bookmaker_id, s.outcome)
        if k not in best or s.observed_at > best[k].observed_at:
            best[k] = s
    return list(best.values())


def fair_closing_price(closing_prices: Sequence[float], outcome_index: int, method: str = "power") -> float:
    """Faire Schlussquote eines Ausgangs aus den Schlussquoten der Referenz (alle Ausgänge)."""
    p = dv.devig(closing_prices, method)[outcome_index]
    return 1.0 / p


def clv_percent(bet_price: float, fair_closing: float) -> float:
    """CLV in Prozent: (eigene Quote / faire Schlussquote − 1) · 100."""
    return (bet_price / fair_closing - 1.0) * 100.0


def settle(stake: float, price: float, result: str) -> float:
    """Auszahlung (inkl. Einsatz) je Ergebnis."""
    if result == "won":
        return stake * price
    if result == "lost":
        return 0.0
    if result == "void":
        return stake
    if result == "half_won":
        return stake / 2 * price + stake / 2
    if result == "half_lost":
        return stake / 2
    raise ValueError(result)


# ---------------------------------------------------------------- Datenbank

OUTCOME_ORDER = {"h2h": ["home", "draw", "away"], "totals": ["over", "under"], "spreads": ["home", "away"]}


def capture_closing_odds(conn, now: datetime | None = None, lookback: timedelta = timedelta(hours=48)) -> int:
    """Sichert Schlussquoten für Märkte, deren Event begonnen hat und die noch keine haben."""
    now = now or datetime.now(timezone.utc)
    markets = conn.execute(
        """SELECT m.id, e.start_time FROM markets m JOIN events e ON e.id = m.event_id
           WHERE e.start_time <= %s AND e.start_time > %s
             AND NOT EXISTS (SELECT 1 FROM closing_odds c WHERE c.market_id = m.id)""",
        (now, now - lookback),
    ).fetchall()
    n = 0
    for m in markets:
        rows = conn.execute(
            "SELECT bookmaker_id, outcome, price, observed_at FROM odds_snapshots WHERE market_id=%s AND observed_at <= %s",
            (m["id"], m["start_time"]),
        ).fetchall()
        closing = select_closing([Snap(r["bookmaker_id"], r["outcome"], float(r["price"]), r["observed_at"]) for r in rows],
                                 m["start_time"])
        if not closing:
            continue
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO closing_odds (market_id, bookmaker_id, outcome, price, captured_at)
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
                [(m["id"], s.bookmaker_id, s.outcome, s.price, s.observed_at) for s in closing],
            )
        n += len(closing)
    log.info("Schlussquoten: %d Märkte geprüft, %d Quoten gesichert", len(markets), n)
    return n


def update_bets_clv(conn, method: str = "power", reference_kinds: Sequence[str] = ("sharp",)) -> int:
    """Berechnet CLV für Wetten ohne CLV, deren Markt Schlussquoten einer Referenz hat."""
    bets = conn.execute(
        """SELECT b.id, b.market_id, b.outcome, b.price, m.type FROM bets b JOIN markets m ON m.id = b.market_id
           WHERE b.clv IS NULL AND b.market_id IS NOT NULL"""
    ).fetchall()
    n = 0
    for b in bets:
        order = OUTCOME_ORDER.get(b["type"])
        if not order or b["outcome"] not in order:
            continue
        refs = conn.execute(
            """SELECT c.bookmaker_id, c.outcome, c.price FROM closing_odds c JOIN bookmakers k ON k.id = c.bookmaker_id
               WHERE c.market_id=%s AND k.kind = ANY(%s)""",
            (b["market_id"], list(reference_kinds)),
        ).fetchall()
        by_bm: dict[int, dict[str, float]] = {}
        for r in refs:
            by_bm.setdefault(r["bookmaker_id"], {})[r["outcome"]] = float(r["price"])
        present = [oc for oc in order if any(oc in q for q in by_bm.values())]
        complete = [q for q in by_bm.values() if all(oc in q for oc in present)]
        if len(present) < 2 or not complete:
            continue
        fairs = [fair_closing_price([q[oc] for oc in present], present.index(b["outcome"]), method) for q in complete]
        fair = sum(fairs) / len(fairs)
        clv = clv_percent(float(b["price"]), fair)
        conn.execute("UPDATE bets SET clv=%s WHERE id=%s", (round(clv, 4), b["id"]))
        n += 1
    log.info("CLV berechnet für %d Wetten", n)
    return n
