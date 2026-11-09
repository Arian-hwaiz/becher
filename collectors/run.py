"""Collector-Lauf: einmalig oder im Intervall.

    python -m collectors.run --once        # ein Durchlauf
    python -m collectors.run               # alle COLLECT_INTERVAL_SECONDS
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from collectors.odds_api import OddsApiCollector
from common import db
from common.config import settings

log = logging.getLogger("collectors.run")


def run_once() -> None:
    started = datetime.now(timezone.utc)
    collector = OddsApiCollector()
    try:
        events = collector.fetch()
        with db.connect() as conn:
            store = db.Store(conn)
            n_ev, n_snap = store.save_events(events, observed_at=started)
            store.log_run(collector.source, started, True, n_ev, n_snap)
        log.info("Gespeichert: %d Events, %d Quoten", n_ev, n_snap)
    except Exception as exc:  # noqa: BLE001
        log.exception("Collector-Lauf fehlgeschlagen")
        try:
            with db.connect() as conn:
                db.Store(conn).log_run(collector.source, started, False, 0, 0, str(exc)[:500])
        except Exception:  # noqa: BLE001
            log.error("Fehler konnte nicht protokolliert werden")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="nur ein Durchlauf")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.once:
        run_once()
        return
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", seconds=settings.collect_interval_seconds, next_run_time=datetime.now(timezone.utc))
    log.info("Starte Collector alle %d s. Strg+C zum Beenden.", settings.collect_interval_seconds)
    sched.start()


if __name__ == "__main__":
    main()
