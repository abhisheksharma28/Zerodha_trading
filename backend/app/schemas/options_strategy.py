import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import TradingMode


class OptionsTemplate(BaseModel):
    slug: str
    name: str
    category: str
    underlying: str
    structure: str
    time_horizon: str
    complexity: str
    warning: str
    supports_backtest: bool
    supports_paper: bool
    supports_live: bool
    parameters: dict[str, Any]
    presets: dict[str, dict[str, Any]]


class CreateOptionsInstance(BaseModel):
    mode: TradingMode = TradingMode.PAPER
    preset: str | None = "as_specified"
    parameters: dict[str, Any] | None = None


class OptionsInstanceRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    slug: str
    mode: TradingMode
    status: str
    config: dict[str, Any]
    basket_id: str
    underlying: str
    expiry: date | None
    entry_date: date | None
    dte_at_entry: int | None
    spot_at_entry: float | None
    lot_size: int | None
    strike_a: float | None
    strike_b: float | None
    strike_c: float | None
    basket: dict[str, Any] | None
    net_credit: float | None
    credit_pct: float | None
    deployed_capital: float | None
    deployed_capital_source: str | None
    target_amount: float | None
    stop_loss_amount: float | None
    last_spot: float | None
    last_pnl: float | None
    exit_reason: str | None
    realized_pnl: float | None
    fees: float | None
    net_pnl: float | None
    not_eligible_reason: str | None
    created_at: datetime
    updated_at: datetime


class OptionsBacktestRequest(BaseModel):
    preset: str | None = "as_specified"
    parameters: dict[str, Any] | None = None
    start: date
    end: date
    spot_path: dict[str, float] | None = Field(
        default=None, description="{iso_date: nifty_spot}. Required for the SYNTHETIC source."
    )
    recorded_quotes: dict[str, dict[str, dict[str, float]]] | None = Field(
        default=None,
        description="Real historical option quotes {iso_date: {strike_str: {bid,ask,last}}}. "
                    "When present, a faithful RecordedOptionData backtest is run instead of "
                    "the synthetic one.",
    )
    synthetic_vol: float = 0.13
    fallback_margin_per_short_lot: float = 150000.0
    costs: dict[str, float] | None = None
