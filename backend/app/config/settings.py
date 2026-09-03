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

    # --- Fundamentals data provider (Stock Intelligence) ---
    # "yfinance" (default; free, no key) | "indianapi" (needs a key) | "none".
    # Adapters live in app/providers/fundamentals.
    fundamentals_provider: str = "yfinance"
    fundamentals_api_key: str = ""
    fundamentals_api_base: str = ""

    # --- Research assistant ("Ask AI" chat) ---
    # Provider-agnostic; ASSISTANT_PROVIDER picks the backend:
    #   openai    - any OpenAI-compatible /chat/completions endpoint. The
    #               default base URL is Groq (free tier, no card) — just set
    #               ASSISTANT_OPENAI_API_KEY. Repoint the base URL for
    #               OpenRouter / OpenAI / a local server.
    #   gemini    - Google Gemini free tier (GEMINI_API_KEY).
    #   ollama    - a local Ollama server; no key, offline, must be running.
    #   anthropic - Claude (paid; ANTHROPIC_API_KEY).
    # Missing config -> the endpoint reports "not configured", never a 500.
    assistant_provider: str = "openai"
    assistant_max_tokens: int = 1800

    assistant_openai_api_key: str = ""
    assistant_openai_base_url: str = "https://api.groq.com/openai/v1"
    assistant_openai_model: str = "llama-3.3-70b-versatile"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    # --- Risk limits (internal ceiling, intentionally tighter than Kite's own) ---
    risk_max_orders_per_second: int = 5
    risk_max_orders_per_minute: int = 200
    risk_max_orders_per_day: int = 1000
    risk_max_live_order_value_inr: float = 100_000

    # --- Live-engine latency widget thresholds (milliseconds, advisory) ---
    # Bands for colouring the "⚡ x.x ms" indicator. Deployment-specific:
    # broker RTT dominates end-to-end, so these describe INTERNAL latency.
    latency_threshold_excellent_ms: float = 1.0
    latency_threshold_fast_ms: float = 5.0
    latency_threshold_moderate_ms: float = 20.0
    latency_threshold_high_ms: float = 100.0

    # --- Live market-data ticker (Kite WebSocket) ---
    # Off by default. When enabled the API process opens one ws.kite.trade
    # connection and folds ticks into the in-memory market state.
    live_ticker_enabled: bool = False
    # "full" streams 5-level depth + OI too, which the quote drawer and
    # option chain use; ~4x the bytes of "quote" but negligible at our
    # instrument counts.
    live_ticker_mode: str = "full"  # "ltp" | "quote" | "full"
    # Comma-separated "EXCH:SYMBOL" list; empty => the NIFTY 50 watchlist.
    live_ticker_instruments: str = ""
    live_ticker_max_instruments: int = 500
    live_ticker_stale_seconds: float = 5.0
    # No tick for this long during market hours trips the data-stale circuit
    # breaker and halts new orders until ticks resume.
    circuit_breaker_stale_halt_seconds: float = 15.0

    # --- Market Scanner recommendation engine (app.market_scanner) ---
    # A 5-minute sweep of the tradable universe that produces ranked, live-
    # tracked trade setups shown at the top of the Scanner tab. Runs in the
    # API process (needs the tick feed); market-hours gated.
    market_scanner_enabled: bool = True
    market_scanner_scan_interval_seconds: int = 300
    market_scanner_track_interval_seconds: int = 20
    market_scanner_core_max: int = 120            # deep-scanned F&O names (daily + 15m) / cycle
    market_scanner_broad_max: int = 250           # cash equities scanned daily-only for delivery/swing
    market_scanner_broad_promote_max: int = 15    # (legacy, unused)
    market_scanner_max_live: int = 40             # cap on concurrent LIVE recommendations
    market_scanner_overlay_min_confidence: float = 68.0  # add a separate OPTION card above this
    market_scanner_eod_flatten_ist: str = "15:20"       # unresolved -> NEUTRAL at this IST time

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
