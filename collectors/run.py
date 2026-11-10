"""Collector-Lauf: einmalig oder im Intervall, für alle aktiven Collector (COLLECTORS in .env).

    python -m collectors.run --once                 # ein Durchlauf aller aktiven Collector
    python -m collectors.run --once --only betfair  # nur ein Collector
    python -m collectors.run                        # alle COLLECT_INTERVAL_SECONDS
    python -m collectors.run --scan                 # nach jedem Durchlauf den Opportunity-Scan starten
    python -m collectors.run --only bwin,admiral --scan --interval 900   # eigene Scraper alle 15 min

Blockt eine Seite automatisierte Zugriffe (403, Cloudflare, Captcha), wird der Collector in der
Administration ausgeschaltet und der Buchmacher auf „blockiert“ gesetzt. Es wird nichts umgangen.
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
    if name == "bwin":
        from collectors.bwin import BwinCollector
        return BwinCollector()
    if name == "admiral":
        from collectors.admiral import AdmiralCollector
        return AdmiralCollector()
    if name == "interwetten":
        from collectors.interwetten import InterwettenCollector
        return InterwettenCollector()
    if name == "betathome":
        from collectors.betathome import BetAtHomeCollector
        return BetAtHomeCollector()
    if name == "winamax":
        from collectors.winamax import WinamaxCollector
        return WinamaxCollector()
    raise ValueError(f"unbekannter Collector {name!r}; bekannt: odds_api, betfair, bwin, admiral, interwetten, "
                     "betathome, winamax")


# Scraper-Quelle → Buchmacher-Schlüssel (für den Status „blockiert“)
SCRAPER_BOOKMAKER = {"bwin": "bwin", "admiral": "admiral", "interwetten": "interwetten", "betathome": "betathome",
                     "winamax": "winamax"}


def _mark_blocked(source: str, reason: str) -> None:
    """Collector ausschalten und Buchmacher auf „blockiert“ setzen, damit der Dauerbetrieb nicht weiter anfragt."""
    try:
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO collector_settings (source, enabled, updated_at) VALUES (%s, FALSE, now())
                   ON CONFLICT (source) DO UPDATE SET enabled = FALSE, updated_at = now()""", (source,))
            if source in SCRAPER_BOOKMAKER:
                conn.execute("UPDATE bookmakers SET scraper_status='blockiert', scraper_note=%s WHERE key=%s",
                             (f"automatisch gestoppt: {reason}"[:300], SCRAPER_BOOKMAKER[source]))
    except Exception:  # noqa: BLE001
        log.exception("%s: Blockade konnte nicht vermerkt werden", source)


def run_collector(collector: Collector) -> tuple[int, int]:
    from collectors.page_capture import BlockedError
    started = datetime.now(timezone.utc)
    try:
        events = collector.fetch()
        with db.connect() as conn:
            store = db.Store(conn)
            n_ev, n_snap = store.save_events(events, observed_at=started)
            store.log_run(collector.source, started, True, n_ev, n_snap)
        log.info("%s: %d Events, %d Quoten gespeichert", collector.source, n_ev, n_snap)
        return n_ev, n_snap
    except BlockedError as exc:
        log.error("%s: blockiert, Collector wird ausgeschaltet (%s)", collector.source, exc)
        _mark_blocked(collector.source, str(exc))
        try:
            with db.connect() as conn:
                db.Store(conn).log_run(collector.source, started, False, 0, 0, f"blockiert: {exc}"[:500])
        except Exception:  # noqa: BLE001
            log.error("Fehler konnte nicht protokolliert werden")
        return 0, 0
    except Exception as exc:  # noqa: BLE001
        log.exception("%s: Lauf fehlgeschlagen", collector.source)
        try:
            with db.connect() as conn:
                db.Store(conn).log_run(collector.source, started, False, 0, 0, str(exc)[:500])
        except Exception:  # noqa: BLE001
            log.error("Fehler konnte nicht protokolliert werden")
        return 0, 0


def run_once(names: list[str] | None = None, scan: bool = False, check_switch: bool | None = None) -> None:
    # Schalter der Administration gelten für COLLECTORS aus .env und für den Dauerbetrieb;
    # ein einzelner Lauf mit --once --only läuft immer
    check = (not names) if check_switch is None else check_switch
    for name in names or settings.active_collectors:
        if check:
            try:
                with db.connect() as conn:
                    enabled = db.collector_enabled(conn, name)
            except Exception as exc:  # noqa: BLE001
                log.warning("%s: Schalter aus der Administration nicht lesbar (%s); Collector läuft. "
                            "Schema aktualisieren: python scripts/init_db.py", name, exc)
                enabled = True
            if not enabled:
                log.info("%s: in der Administration ausgeschaltet, übersprungen", name)
                continue
        try:
            collector = make_collector(name)
        except Exception as exc:  # noqa: BLE001
            log.error("%s: nicht gestartet (%s)", name, exc)
            continue
        run_collector(collector)
    if scan:
        from engine.clv import capture_closing_odds, update_bets_clv
        from engine.notify import notify_new
        from engine.scan import run_scan
        with db.connect() as conn:
            found = run_scan(conn)
            notify_new(conn, found, min_percent=settings.notify_min_percent)
            capture_closing_odds(conn)
            update_bets_clv(conn)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="nur ein Durchlauf")
    parser.add_argument("--only", help="nur diese Collector, kommagetrennt (odds_api, betfair, bwin, admiral, interwetten, betathome, winamax)")
    parser.add_argument("--scan", action="store_true", help="nach jedem Durchlauf scannen")
    parser.add_argument("--interval", type=int, help="Abstand im Dauerbetrieb in Sekunden (Standard COLLECT_INTERVAL_SECONDS)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    names = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else None

    if args.once:
        run_once(names, scan=args.scan)
        return
    interval = max(60, args.interval or settings.collect_interval_seconds)
    sched = BlockingScheduler(timezone="UTC")
    sched.add_job(run_once, "interval", seconds=interval, next_run_time=datetime.now(timezone.utc),
                  kwargs={"names": names, "scan": args.scan, "check_switch": True},
                  max_instances=1, coalesce=True)
    log.info("Starte Collector %s alle %d s. Strg+C oder Fenster schließen zum Beenden.",
             names or settings.active_collectors, interval)
    sched.start()


if __name__ == "__main__":
    main()
