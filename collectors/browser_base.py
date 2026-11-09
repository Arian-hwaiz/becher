"""Grundgerüst für eigene Buchmacher-Collector per Browser (Playwright).

Viele Buchmacher haben keine öffentliche API. Der zuverlässigste Weg ist ein echter Browser,
der die Übersichtsseite einer Liga lädt und die Quoten aus dem DOM liest. Dieses Modul kapselt
das Gemeinsame; je Buchmacher bleibt nur ``league_urls`` und ``parse_page`` zu schreiben.

Beispiel-Skelett (collectors/sites/beispiel.py):

    class BeispielCollector(BrowserCollector):
        source = "beispiel"
        bookmaker_source_key = "beispiel"
        league_urls = {"soccer_germany_bundesliga": "https://…/fussball/bundesliga"}

        def parse_page(self, html: str, league_key: str) -> list[NormalizedEvent]:
            ...  # mit selectolax/BeautifulSoup die Event-Zeilen lesen

Hinweise:
* Erst mit ``python -m collectors.sites.beispiel --dump`` eine Seite als HTML speichern, den
  Parser gegen diese Datei testen (tests/fixtures), dann live laufen lassen.
* Zwischen Seitenaufrufen pausieren (``delay_s``), eine feste User-Agent-Kennung und ein
  persistentes Browserprofil nutzen; nie Login-Daten im Code.
* Bookmaker in ``bookmakers`` + ``bookmaker_source_keys`` (source = ``source``) anlegen.
"""
from __future__ import annotations

import logging
import time
from abc import abstractmethod
from pathlib import Path

from collectors.base import Collector
from common.models import NormalizedEvent

log = logging.getLogger(__name__)


class BrowserCollector(Collector):
    source = "browser"
    bookmaker_source_key = ""
    league_urls: dict[str, str] = {}
    delay_s: float = 3.0
    headless: bool = True
    profile_dir: Path | None = None       # persistentes Profil (Cookies, Consent)
    user_agent: str | None = None

    def fetch(self) -> list[NormalizedEvent]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Playwright fehlt: pip install playwright && playwright install chromium") from exc
        events: list[NormalizedEvent] = []
        with sync_playwright() as p:
            if self.profile_dir:
                ctx = p.chromium.launch_persistent_context(str(self.profile_dir), headless=self.headless,
                                                           user_agent=self.user_agent)
                page = ctx.new_page()
            else:
                browser = p.chromium.launch(headless=self.headless)
                ctx = browser.new_context(user_agent=self.user_agent, locale="de-DE")
                page = ctx.new_page()
            for i, (league_key, url) in enumerate(self.league_urls.items()):
                if i:
                    time.sleep(self.delay_s)
                try:
                    page.goto(url, wait_until="networkidle", timeout=45_000)
                    self.after_load(page)
                    html = page.content()
                    parsed = self.parse_page(html, league_key)
                    log.info("%s: %s → %d Events", self.source, league_key, len(parsed))
                    events.extend(parsed)
                except Exception:  # noqa: BLE001
                    log.exception("%s: %s fehlgeschlagen", self.source, url)
            ctx.close()
        return events

    def after_load(self, page) -> None:
        """Hook: Cookie-Banner schließen, scrollen, auf Quoten warten. Standard: nichts."""

    @abstractmethod
    def parse_page(self, html: str, league_key: str) -> list[NormalizedEvent]:
        """Liest Events und Quoten aus dem HTML einer Ligaseite."""

    def dump(self, out_dir: Path) -> None:
        """Speichert jede Ligaseite als HTML, um Parser offline zu entwickeln."""
        from playwright.sync_api import sync_playwright
        out_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            page = browser.new_context(user_agent=self.user_agent, locale="de-DE").new_page()
            for league_key, url in self.league_urls.items():
                page.goto(url, wait_until="networkidle", timeout=45_000)
                self.after_load(page)
                (out_dir / f"{self.source}_{league_key}.html").write_text(page.content(), encoding="utf-8")
                log.info("gespeichert: %s", out_dir / f"{self.source}_{league_key}.html")
            browser.close()
