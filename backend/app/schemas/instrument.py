import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class InstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    instrument_token: str
    tradingsymbol: str
    name: str | None
    exchange: str
    segment: str
    instrument_type: str
    expiry: date | None
    strike: float | None
    tick_size: float | None
    lot_size: int | None
    underlying: str | None
    active: bool
    last_synced_at: datetime | None


class SyncResult(BaseModel):
    synced_at: str
    total: int
    by_exchange: dict[str, dict[str, int]]


class OptionStrikeRow(BaseModel):
    strike: float | None
    option_type: str
    tradingsymbol: str
    instrument_token: str
    lot_size: int | None
