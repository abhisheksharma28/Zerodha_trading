"""Central application settings.

All configuration is read from environment variables (see /.env.example at the
repo root for the full documented list). Nothing here should be hardcoded
per-environment — docker-compose.yml and deployment tooling supply the actual
values via env vars / .env files.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- General ---
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    secret_key: str = Field(..., description="Used to encrypt broker tokens at rest")
    timezone: str = "Asia/Kolkata"

    # --- Database ---
    database_url: str

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Zerodha Kite Connect ---
    zerodha_api_key: str = ""
    zerodha_api_secret: str = ""
    zerodha_static_ip: str = ""
    zerodha_redirect_url: str = "http://localhost:8000/api/v1/broker/callback"

    # --- Risk limits (internal ceiling, intentionally tighter than Kite's own) ---
    risk_max_orders_per_second: int = 5
    risk_max_orders_per_minute: int = 200
    risk_max_orders_per_day: int = 1000
    risk_max_live_order_value_inr: float = 100_000

    # --- Strategy-evaluation worker (app.workers) ---
    worker_poll_interval_seconds: int = 60
    # How far back the worker pulls candles each poll; only bars newer than
    # the last one already fed to a strategy are acted on, so this just needs
    # to comfortably exceed one poll interval to survive a missed tick.
    worker_candle_lookback_minutes: int = 120
    # Bar interval fed to running PAPER/SIMULATION strategies when a
    # deployment's config doesn't specify one (Kite intervals: "minute",
    # "3minute", "5minute", "15minute", "30minute", "60minute", "day").
    worker_default_timeframe: str = "5minute"

    # --- CORS ---
    cors_allow_origins: list[str] = ["http://localhost:5173"]
    # Optional regex for CORS origins — handy on Railway where the frontend
    # is served from https://<something>.up.railway.app. Example:
    #   CORS_ALLOW_ORIGIN_REGEX=https://.*\.up\.railway\.app
    cors_allow_origin_regex: str | None = None

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_set(cls, v: str) -> str:
        if not v or v == "change-me-to-a-long-random-string":
            raise ValueError(
                "SECRET_KEY must be set to a real random value — see .env.example"
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
