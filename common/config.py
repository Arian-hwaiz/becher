"""Konfiguration aus .env bzw. Umgebungsvariablen."""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql://becher:becher@localhost:5432/becher"

    odds_api_key: str = ""
    odds_api_sports: str = "soccer_germany_bundesliga"
    odds_api_regions: str = "eu"
    odds_api_markets: str = "h2h,totals"
    odds_api_min_remaining: int = 20       # unter dieser Reserve keine Abfragen mehr (Credits je Monat)

    collect_interval_seconds: int = Field(default=14400, ge=30)
    collectors: str = "odds_api"            # aktive Collector, kommagetrennt: odds_api, betfair, bwin, admiral

    # Eigene Scraper (bwin, admiral): Ligen als Odds-API-Schlüssel, Pausen und Mindestabstand
    scrape_leagues: str = "soccer_germany_bundesliga,soccer_germany_bundesliga2,soccer_epl"
    scrape_interval_seconds: int = Field(default=120, ge=30)   # Mindestabstand zwischen zwei Läufen je Scraper
    scrape_delay_seconds: float = Field(default=3.0, ge=1.0)   # Pause zwischen zwei Seitenaufrufen
    scrape_headless: bool = True

    # Betfair Exchange (https://developer.betfair.com): App-Key plus Session-Token
    # oder Benutzername/Passwort für den interaktiven Login
    betfair_app_key: str = ""
    betfair_session_token: str = ""
    betfair_username: str = ""
    betfair_password: str = ""
    betfair_event_types: str = "1,2,7522"   # 1 Fußball, 2 Tennis, 7522 Basketball
    betfair_hours_ahead: int = 48

    # Dashboard: Nutzeransicht (Port 8501) und getrennter Admin-Bereich (Port 8502)
    dashboard_url: str = "http://localhost:8501"   # Adresse der Nutzeransicht, für Links aus dem Admin-Bereich
    admin_password: str = ""                        # leer = Admin-Bereich ohne Passwort (nur auf dem eigenen PC sinnvoll)

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_min_percent: float = 1.0      # Telegram nur ab diesem konservativen Prozent
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"           # low | medium | high

    @property
    def active_collectors(self) -> list[str]:
        return [c.strip() for c in self.collectors.split(",") if c.strip()]

    @property
    def scrape_league_list(self) -> list[str]:
        return [s.strip() for s in self.scrape_leagues.split(",") if s.strip()]

    @property
    def sports(self) -> list[str]:
        return [s.strip() for s in self.odds_api_sports.split(",") if s.strip()]


settings = Settings()
