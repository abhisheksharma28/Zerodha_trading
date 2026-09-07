"""Data adapters for IMIE — thin wrappers over the existing Kite plumbing.

* trailing 1-minute history (for time-of-day baselines + intraday
  indicators), paged + cached per day
* today's session bars (a slice of the same series)
* the live snapshot from the in-RAM tick state, when a subscription exists

Everything degrades: no broker session -> ``None`` + a reason; short
history -> the caller lowers confidence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.live.market_state import MARKET_STATE
from app.services import broker_service

logger = get_logger(__name__)

_IST_MIN = 9 * 60 + 15   # 09:15
_IST_MAX = 15 * 60 + 30  # 15:30

# token -> (fetched_epoch, bars)   1-minute bars, ~1 trading day of TTL
_cache: dict[str, tuple[float, list["Bar"]]] = {}
_CACHE_TTL = 55.0  # a scan runs each minute; a fresh pull per token per minute


@dataclass(frozen=True)
class Bar:
    ts: str          # ISO, IST
    minute_of_day: int   # minutes past midnight IST (session bucket key)
    open: float
    high: float
    low: float
    close: float
    volume: float


def get_client(db: Session, settings: Settings) -> Any | None:
    try:
        return broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.info("imie_no_broker", error=str(exc))
        return None


def _minute_of_day(ts: Any) -> int:
    s = str(ts)
    # "2026-09-07T11:17:00+0530" / "2026-09-07 11:17:00"
    try:
        hh = int(s[11:13])
        mm = int(s[14:16])
        return hh * 60 + mm
    except (ValueError, IndexError):
        return -1


def minute_bars(client: Any, token: str, *, days: int) -> list[Bar]:
    """Trailing 1-minute bars, oldest first. Cached ~1 minute per token."""
    hit = _cache.get(token)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=max(2, days))
    try:
        rows = client.get_historical_candles(str(token), "minute", from_dt, to_dt)
    except Exception as exc:  # noqa: BLE001
        logger.info("imie_minute_history_failed", token=token, error=str(exc))
        return []
    bars: list[Bar] = []
    for r in rows:
        if len(r) < 5 or r[4] is None:
            continue
        mod = _minute_of_day(r[0])
        if mod < _IST_MIN or mod > _IST_MAX:
            continue
        bars.append(Bar(
            ts=str(r[0]), minute_of_day=mod,
            open=float(r[1]), high=float(r[2]), low=float(r[3]), close=float(r[4]),
            volume=float(r[5]) if len(r) > 5 and r[5] is not None else 0.0,
        ))
    _cache[token] = (time.time(), bars)
    return bars


def split_sessions(bars: list[Bar]) -> list[list[Bar]]:
    """Group a flat 1-minute series into per-session lists (a new session
    starts whenever minute-of-day goes backwards)."""
    out: list[list[Bar]] = []
    prev = 10**9
    for b in bars:
        if b.minute_of_day < prev - 5:
            out.append([])
        out[-1].append(b) if out else out.append([b])
        prev = b.minute_of_day
    return [s for s in out if s]


def today_session(bars: list[Bar]) -> list[Bar]:
    sessions = split_sessions(bars)
    return sessions[-1] if sessions else []


def live_snapshot(token: str) -> dict[str, Any] | None:
    try:
        st = MARKET_STATE.get(int(token))
    except (TypeError, ValueError):
        return None
    if st is None:
        return None
    d = st.as_dict()
    return d if d.get("last_price") else None
