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

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    anthropic_api_key: str = ""

    @property
    def sports(self) -> list[str]:
        return [s.strip() for s in self.odds_api_sports.split(",") if s.strip()]


settings = Settings()
