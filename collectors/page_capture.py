"""Gemeinsamer Unterbau für Scraper, die die Daten einer Buchmacher-Seite mitlesen.

Viele Buchmacher-Seiten laden ihre Quoten selbst als JSON (XHR/fetch) oder über einen
WebSocket. Statt das HTML zu zerlegen, öffnet ``capture_pages`` die Ligaseite in einem echten
Browser (Playwright) und schneidet mit, was die Seite ohnehin lädt: passende JSON-Antworten,
empfangene WebSocket-Frames und die Links auf der Seite (für Direkt-Links zum Spiel).

Regeln (siehe docs/HANDBUCH.md, Abschnitt Scraper):
* kein Login, keine Cookies aus dem eigenen Browser, nichts mit Wettkonten,
* kein Umgehen von Bot-Schutz: Zeigt eine Seite eine Challenge/Captcha oder blockt sie
  (403, Cloudflare), bricht der Lauf für diese Seite ab und meldet das,
* höflich: normaler Browser-User-Agent, Pause zwischen Seitenaufrufen
  (``SCRAPE_DELAY_SECONDS``), Mindestabstand zwischen Läufen (``SCRAPE_INTERVAL_SECONDS``).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from common.config import settings

log = logging.getLogger(__name__)

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")

BLOCK_MARKERS = ("Attention Required! | Cloudflare", "Just a moment...", "captcha", "Access Denied",
                 "Sorry, you have been blocked")


class BlockedError(RuntimeError):
    """Die Seite blockt automatisierte Zugriffe. Wir umgehen das nicht."""


@dataclass
class PageCapture:
    url: str
    responses: list[tuple[str, bytes]] = field(default_factory=list)   # (URL, Body) passender Antworten
    ws_frames: list[bytes | str] = field(default_factory=list)          # empfangene WebSocket-Frames
    links: list[tuple[str, str]] = field(default_factory=list)          # (href, Linktext)


def capture_pages(urls: list[str], want_response: Callable[[str], bool] | None = None,
                  capture_ws: bool = False, wait_s: float = 8.0,
                  link_contains: str | None = None) -> list[PageCapture]:
    """Öffnet jede URL nacheinander in einem Browser und gibt pro Seite das Mitgeschnittene zurück."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError('Playwright fehlt: pip install -e ".[browser]" && python -m playwright install chromium') from exc

    results: list[PageCapture] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.scrape_headless)
        try:
            for i, url in enumerate(urls):
                if i:
                    time.sleep(settings.scrape_delay_seconds)
                cap = PageCapture(url)
                ctx = browser.new_context(user_agent=USER_AGENT, locale="de-DE",
                                          viewport={"width": 1366, "height": 900})
                page = ctx.new_page()

                def on_response(resp, cap=cap):
                    if want_response is None or resp.request.resource_type not in ("xhr", "fetch"):
                        return
                    if not want_response(resp.url):
                        return
                    try:
                        cap.responses.append((resp.url, resp.body()))
                    except Exception:  # noqa: BLE001  (Antwort ohne Body, z. B. Redirect)
                        pass

                def on_ws(ws, cap=cap):
                    ws.on("framereceived", lambda payload: cap.ws_frames.append(payload))

                page.on("response", on_response)
                if capture_ws:
                    page.on("websocket", on_ws)
                try:
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(int(wait_s * 1000))
                    title = page.title()
                    if (resp is not None and resp.status in (403, 429)) or any(m.lower() in title.lower() for m in BLOCK_MARKERS):
                        raise BlockedError(f"{url}: Seite blockt automatisierte Zugriffe ({resp.status if resp else '?'} {title!r})")
                    if link_contains:
                        cap.links = page.eval_on_selector_all(
                            "a[href]", "els => els.map(e => [e.href, (e.innerText || '').trim()])")
                        cap.links = [(h, t) for h, t in cap.links if link_contains in h]
                finally:
                    ctx.close()
                results.append(cap)
        finally:
            browser.close()
    return results


def too_soon(source: str) -> bool:
    """True, wenn der letzte erfolgreiche Lauf dieser Quelle jünger als SCRAPE_INTERVAL_SECONDS ist."""
    try:
        from common import db
        with db.connect() as conn:
            row = conn.execute("SELECT max(started_at) AS t FROM collector_runs WHERE source=%s AND ok",
                               (source,)).fetchone()
    except Exception:  # noqa: BLE001  (ohne Datenbank kein Mindestabstand)
        return False
    last = row["t"] if row else None
    if last is None:
        return False
    return datetime.now(timezone.utc) - last < timedelta(seconds=settings.scrape_interval_seconds)
