"""Collector-Lauf: einmalig oder im Intervall, für alle aktiven Collector (COLLECTORS in .env).

    python -m collectors.run --once                 # ein Durchlauf aller aktiven Collector
    python -m collectors.run --once --only betfair  # nur ein Collector
    python -m collectors.run                        # alle COLLECT_INTERVAL_SECONDS
    python -m collectors.run --scan                 # nach jedem Durchlauf den Opportunity-Scan starten
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from collectors.base import Collector
from common import db
from common.config import settings

log = logging.getLogger("collectors.run")


def make_collector(name: str) -> Collector:
    """Erzeugt einen Collector nach Namen; importiert erst hier, damit fehlende Keys nur den betroffenen stören."""
    if name == "odds_api":
        from collectors.odds_api import OddsApiCollector
        return OddsApiCollector()
    if name == "betfair":
        from collectors.betfair import BetfairCollector
        return BetfairCollector()
    raise ValueError(f"unbekannter Collector {name!r}; bekannt: odds_api, betfair")


def run_collector(collector: Collector) -> tuple[int, int]:
    started = datetime.now(timezone.utc)
    try:
        events = collector.fetch()
        with db.connect() as conn:
            store = db.Store(conn)
            n_ev, n_snap = store.save_events(events, observed_at=started)
            store.log_run(collector.source, started, True, n_ev, n_snap)
        log.info("%s: %d Events, %d Quoten gespeichert", collector.source, n_ev, n_snap)
        return n_ev, n_snap
    except Exception as exc:  # noqa: BLE001
        log.exception("%s: Lauf fehlgeschlagen", collector.source)
        try:
            with db.connect() as conn:
                db.Store(conn).log_run(collector.source, started, False, 0, 0, str(exc)[:500])
        except Exception:  # noqa: BLE001
            log.error("Fehler konnte nicht protokolliert werden")
        return 0, 0


def run_once(names: list[str] | None = None, scan: bool = False) -> None:
    for name in names or settings.active_collectors:
        try:
            collector = make_collector(name)
        except Exception as exc:  # noqa: BLE001
            log.error("%s: nicht gestartet (%s)", name, exc)
            continue
        run_collector(collector)
    if scan:
        from engine.scan import run_scan
        with db.connect() as conn:
            run_scan(conn)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="nur ein Durchlauf")
    parser.add_argument("--only", help="nur diesen Collector (odds_api oder betfair)")
    parser.add_argument("--scan", action="store_true", help="nach jedem Durchlauf scannen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    names = [args.only] if args.only else None

    if args.once:
        run_once(names, scan=args.scan)
        return
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", seconds=settings.collect_interval_seconds,
                  next_run_time=datetime.now(timezone.utc), kwargs={"names": names, "scan": args.scan})
    log.info("Starte Collector %s alle %d s. Strg+C zum Beenden.", names or settings.active_collectors,
             settings.collect_interval_seconds)
    sched.start()


if __name__ == "__main__":
    main()
