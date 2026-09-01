from typing import Any

from pydantic import BaseModel, Field


class TemplateSummary(BaseModel):
    slug: str
    name: str
    category: str
    description: str
    timeframe: str
    time_horizon: str
    complexity: str
    market_types: list[str]
    supports_long: bool
    supports_short: bool
    supports_intraday: bool
    supports_swing: bool
    supports_market_neutral: bool
    warning: str
    min_instruments: int
    max_instruments: int | None


class TemplateDetail(TemplateSummary):
    logic: str
    risks: list[str]
    best_for: str
    required_data: list[str]
    example: str
    parameters: dict[str, Any]
    presets: dict[str, dict[str, Any]]


class StrategyFromTemplateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    preset: str | None = Field(default="balanced")
    parameters: dict[str, Any] | None = None


class SeedResult(BaseModel):
    created: list[str]
    skipped: list[str]
