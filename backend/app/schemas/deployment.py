import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import DeploymentStatus, TradingMode


class DeploymentCreate(BaseModel):
    strategy_version_id: uuid.UUID
    name: str
    mode: TradingMode
    instrument_universe: list[str]
    config: dict = Field(default_factory=dict)
    # Required, and must literally equal this phrase, when mode == LIVE.
    # This is the human-in-the-loop confirmation requirement #14 depends on —
    # a UI "Deploy" button click alone is not sufficient for LIVE.
    live_trading_confirmation_phrase: str | None = None

    @model_validator(mode="after")
    def validate_live_confirmation(self) -> "DeploymentCreate":
        if self.mode == TradingMode.LIVE:
            if self.live_trading_confirmation_phrase != "DEPLOY LIVE TRADING":
                raise ValueError(
                    'LIVE deployments require live_trading_confirmation_phrase == '
                    '"DEPLOY LIVE TRADING" exactly. This is deliberate friction — '
                    "see requirement #14 in the project instructions."
                )
        elif self.mode not in (TradingMode.SIMULATION, TradingMode.PAPER):
            raise ValueError("mode must be simulation, paper, or live (never backtest).")
        return self


class DeploymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_version_id: uuid.UUID
    name: str
    mode: TradingMode
    status: DeploymentStatus
    config: dict
    instrument_universe: list
    live_trading_confirmed: bool
    live_trading_confirmed_at: datetime | None
    cloned_from_deployment_id: uuid.UUID | None
    deployed_at: datetime | None
    paused_at: datetime | None
    stopped_at: datetime | None
    last_heartbeat_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DeploymentCloneRequest(BaseModel):
    name: str
    mode: TradingMode
    live_trading_confirmation_phrase: str | None = None
