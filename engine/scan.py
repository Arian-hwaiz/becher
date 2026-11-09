"""Opportunity-Scan: aus den jüngsten Quoten je Markt Valuebets und Surebets finden.

Ablauf (``scan_market`` ist eine reine Funktion, ``run_scan`` hängt sie an die Datenbank):

1. Pro Markt die jüngste Quote je (Buchmacher, Ausgang) nehmen, nicht älter als ``max_age_s``.
2. Referenzen = Buchmacher mit ``kind in ('sharp', 'exchange')``, die alle Ausgänge anbieten
   (Börse nur mit ausreichender Liquidität). Daraus faire Wahrscheinlichkeiten (``devig.consensus``).
3. Valuebets: jeder Soft-Buchmacher-Ausgang gegen die faire Wahrscheinlichkeit, EV nach Steuer
   und Kommission des jeweiligen Buchmachers, konservativer EV mit Unsicherheitsband.
4. Surebets: beste effektive Quote je Ausgang über alle Buchmacher, Marge > 0.

Ergebnisse werden als ``Opportunity`` zurückgegeben bzw. in ``opportunities`` geschrieben.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from engine import devig as dv
from engine import surebet as sb
from engine import valuebet as vb

log = logging.getLogger(__name__)

OUTCOME_ORDER = {
    "h2h": ["home", "draw", "away"],
    "totals": ["over", "under"],
    "spreads": ["home", "away"],
}


@dataclass(frozen=True)
class Bookmaker:
    id: int
    key: str
    kind: str                       # sharp | soft | exchange
    tax_rate: float = 0.0
    tax_mode: str = "none"
    commission: float = 0.0


@dataclass(frozen=True)
class OddsRow:
    """Jüngste Quote eines Buchmachers für einen Ausgang."""

    bookmaker_id: int
    outcome: str
    price: float
    observed_at: datetime
    source_ts: datetime | None = None
    liquidity: float | None = None


@dataclass
class Opportunity:
    kind: str                       # value | arb
    market_id: int
    bookmaker_id: int | None
    outcome: str | None
    price: float | None
    fair_price: float | None
    ev: float | None
    ev_conservative: float | None
    method: str
    reference_age_s: int | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanConfig:
    method: str = "power"
    max_age_s: int = 600            # Quoten älter als das werden ignoriert
    min_ev: float = 0.0             # Schwelle für konservativen EV (0 = jeder positive Wert)
    min_arb_percent: float = 0.0
    min_exchange_liquidity: float | None = 2000.0
    n_effective: float = 400.0
    z: float = 1.0
    exchange_weight: float = 1.0
    sharp_weight: float = 1.0


def _effective(bm: Bookmaker, price: float) -> float:
    return sb.effective_price(
        price,
        commission=bm.commission if bm.kind == "exchange" else 0.0,
        tax_rate=bm.tax_rate,
        tax_mode=bm.tax_mode,
    )


def scan_market(market_id: int, market_type: str, rows: Iterable[OddsRow], bookmakers: dict[int, Bookmaker],
                now: datetime | None = None, cfg: ScanConfig | None = None) -> list[Opportunity]:
    cfg = cfg or ScanConfig()
    now = now or datetime.now(timezone.utc)
    order = OUTCOME_ORDER.get(market_type)
    if not order:
        return []

    # jüngste Quote je (Buchmacher, Ausgang)
    latest: dict[tuple[int, str], OddsRow] = {}
    for r in rows:
        if (now - r.observed_at).total_seconds() > cfg.max_age_s:
            continue
        k = (r.bookmaker_id, r.outcome)
        if k not in latest or r.observed_at > latest[k].observed_at:
            latest[k] = r

    by_bm: dict[int, dict[str, OddsRow]] = {}
    for (bid, oc), r in latest.items():
        by_bm.setdefault(bid, {})[oc] = r

    # Ausgänge, die der Markt tatsächlich hat (h2h ohne Draw bei 2-Weg-Sportarten)
    present = [oc for oc in order if any(oc in q for q in by_bm.values())]
    if len(present) < 2:
        return []
    complete = {bid: q for bid, q in by_bm.items() if all(oc in q for oc in present)}

    out: list[Opportunity] = []

    # ---- Referenzen und Valuebets --------------------------------------
    refs: list[dv.Reference] = []
    for bid, q in complete.items():
        bm = bookmakers.get(bid)
        if not bm or bm.kind not in ("sharp", "exchange"):
            continue
        age = max((now - (r.source_ts or r.observed_at)).total_seconds() for r in q.values())
        liq = min((r.liquidity for r in q.values() if r.liquidity is not None), default=None)
        prices = [q[oc].price for oc in present]
        if bm.kind == "exchange":
            # Börse: Back-Quoten enthalten keine Marge, aber Kommission → als Quote nach Kommission
            prices = [sb.effective_price(p, commission=bm.commission) for p in prices]
        refs.append(dv.Reference(bm.key, prices, weight=cfg.exchange_weight if bm.kind == "exchange" else cfg.sharp_weight,
                                 age_s=age, liquidity=liq))
    fair: list[float] | None = None
    if refs:
        try:
            fair = dv.consensus(refs, method=cfg.method, max_age_s=cfg.max_age_s,
                                min_liquidity=cfg.min_exchange_liquidity)
        except ValueError:
            fair = None
    if fair is not None:
        ref_age = int(min(r.age_s for r in refs))
        ref_names = [r.name for r in refs]
        for bid, q in by_bm.items():
            bm = bookmakers.get(bid)
            if not bm or bm.kind != "soft":
                continue
            for i, oc in enumerate(present):
                if oc not in q:
                    continue
                price = q[oc].price
                q_eff = _effective(bm, price)
                p = fair[i]
                sd = vb.probability_uncertainty(p, cfg.n_effective, ref_age)
                ev = vb.expected_value(q_eff, p)
                ev_low = vb.expected_value(q_eff, max(0.0, p - cfg.z * sd))
                if ev_low > cfg.min_ev:
                    out.append(Opportunity(
                        kind="value", market_id=market_id, bookmaker_id=bid, outcome=oc, price=price,
                        fair_price=round(1.0 / p, 3), ev=round(ev, 4), ev_conservative=round(ev_low, 4),
                        method=cfg.method, reference_age_s=ref_age,
                        details={"price_effective": round(q_eff, 4), "fair_prob": round(p, 4),
                                 "references": ref_names, "kelly_quarter": round(vb.kelly(q_eff, p - cfg.z * sd), 4)},
                    ))

    # ---- Surebets --------------------------------------------------------
    best: dict[str, tuple[float, int, float]] = {}  # outcome -> (eff_price, bookmaker_id, raw price)
    for bid, q in by_bm.items():
        bm = bookmakers.get(bid)
        if not bm:
            continue
        for oc, r in q.items():
            eff = _effective(bm, r.price)
            if oc not in best or eff > best[oc][0]:
                best[oc] = (eff, bid, r.price)
    if all(oc in best for oc in present):
        pct = sb.margin_percent([best[oc][0] for oc in present])
        if pct > cfg.min_arb_percent:
            sol = sb.simple([best[oc][0] for oc in present], present)
            out.append(Opportunity(
                kind="arb", market_id=market_id, bookmaker_id=None, outcome=None, price=None, fair_price=None,
                ev=round(pct / 100.0, 4), ev_conservative=round(pct / 100.0, 4), method="best_price",
                reference_age_s=None,
                details={"legs": [{"outcome": oc, "bookmaker_id": best[oc][1], "price": best[oc][2],
                                   "price_effective": round(best[oc][0], 4), "stake": round(s, 4)}
                                  for oc, s in zip(present, sol.stakes)],
                         "percent": pct},
            ))
    return out


# ---------------------------------------------------------------- Datenbank

def load_bookmakers(conn) -> dict[int, Bookmaker]:
    rows = conn.execute("SELECT id, key, kind, tax_rate, tax_mode, commission FROM bookmakers WHERE is_active").fetchall()
    return {r["id"]: Bookmaker(r["id"], r["key"], r["kind"], float(r["tax_rate"]), r["tax_mode"], float(r["commission"]))
            for r in rows}


def run_scan(conn, cfg: ScanConfig | None = None, now: datetime | None = None, write: bool = True) -> list[Opportunity]:
    """Scannt alle Märkte kommender Events und schreibt Treffer in ``opportunities``."""
    cfg = cfg or ScanConfig()
    now = now or datetime.now(timezone.utc)
    bookmakers = load_bookmakers(conn)
    markets = conn.execute(
        """SELECT m.id, m.type FROM markets m JOIN events e ON e.id=m.event_id
           WHERE e.start_time > %s AND e.status='scheduled'""",
        (now,),
    ).fetchall()
    found: list[Opportunity] = []
    for m in markets:
        rows = conn.execute(
            """SELECT DISTINCT ON (bookmaker_id, outcome) bookmaker_id, outcome, price, observed_at, source_ts, liquidity
               FROM odds_snapshots WHERE market_id=%s AND observed_at > %s
               ORDER BY bookmaker_id, outcome, observed_at DESC""",
            (m["id"], now.replace(microsecond=0) - __import__("datetime").timedelta(seconds=cfg.max_age_s)),
        ).fetchall()
        odds = [OddsRow(r["bookmaker_id"], r["outcome"], float(r["price"]), r["observed_at"], r["source_ts"],
                        float(r["liquidity"]) if r["liquidity"] is not None else None) for r in rows]
        found.extend(scan_market(m["id"], m["type"], odds, bookmakers, now, cfg))
    if write and found:
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO opportunities (found_at, kind, market_id, bookmaker_id, outcome, price, fair_price,
                                              ev, ev_conservative, method, reference_age_s, details)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(now, o.kind, o.market_id, o.bookmaker_id, o.outcome, o.price, o.fair_price, o.ev,
                  o.ev_conservative, o.method, o.reference_age_s, json.dumps(o.details)) for o in found],
            )
    log.info("Scan: %d Märkte, %d Treffer (%d Value, %d Arb)", len(markets), len(found),
             sum(o.kind == "value" for o in found), sum(o.kind == "arb" for o in found))
    return found
