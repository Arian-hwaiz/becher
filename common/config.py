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

    collect_interval_seconds: int = Field(default=300, ge=30)
    collectors: str = "odds_api"            # aktive Collector, kommagetrennt: odds_api, betfair

    # Betfair Exchange (https://developer.betfair.com): App-Key plus Session-Token
    # oder Benutzername/Passwort für den interaktiven Login
    betfair_app_key: str = ""
    betfair_session_token: str = ""
    betfair_username: str = ""
    betfair_password: str = ""
    betfair_event_types: str = "1,2,7522"   # 1 Fußball, 2 Tennis, 7522 Basketball
    betfair_hours_ahead: int = 48

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    notify_min_percent: float = 1.0      # Telegram nur ab diesem konservativen Prozent
    anthropic_api_key: str = ""

    @property
    def active_collectors(self) -> list[str]:
        return [c.strip() for c in self.collectors.split(",") if c.strip()]

    @property
    def sports(self) -> list[str]:
        return [s.strip() for s in self.odds_api_sports.split(",") if s.strip()]


settings = Settings()
