"""Shared helpers for basis / spread arbitrage strategies (cash-and-carry,
index-futures basis, calendar spread).

They all reduce to: two aligned price series, a basis or spread, an
annualisation using time-to-expiry, a rolling Z-score, and an expiry-aware
exit. ``expiry_ts`` (epoch seconds) is a param; days-to-expiry is derived
from the synchronised point timestamp.
"""

from __future__ import annotations

from datetime import datetime

from app.arbitrage.data_sync import SyncedPoint
from app.strategies.library.base import ParamSpec

BASIS_COMMON: dict[str, ParamSpec] = {
    "expiry_ts": ParamSpec("number", 0.0,
                           "Epoch seconds of the near contract's expiry (0 = derive from data / "
                           "assume 30d).", min=0.0, group="core"),
    "lookback": ParamSpec("integer", 40, "Rolling Z-score window for the basis / spread.",
                          min=10, max=1000),
    "entry_zscore": ParamSpec("number", 2.0, "Absolute Z to enter.", min=0.3, max=10.0),
    "exit_zscore": ParamSpec("number", 0.3, "Z (toward 0) to exit.", min=0.0, max=10.0),
    "stop_zscore": ParamSpec("number", 4.0, "Z beyond which to force-exit.",
                             min=0.5, max=20.0, group="risk"),
    "close_days_before_expiry": ParamSpec("integer", 2,
                                          "Force-close this many days before the near expiry.",
                                          min=0, max=30, group="risk"),
    "dividend_yield_annual": ParamSpec("number", 0.012,
                                       "Assumed annual dividend yield on the cash leg.",
                                       min=0.0, max=0.2, group="risk"),
}


def days_to_expiry(point: SyncedPoint, expiry_ts: float, fallback_days: float = 30.0) -> float:
    if expiry_ts <= 0:
        return fallback_days
    try:
        now = float(point.ts) if isinstance(point.ts, (int, float)) else \
            datetime.fromisoformat(str(point.ts)).timestamp()
    except (ValueError, TypeError):
        return fallback_days
    return max(0.0, (expiry_ts - now) / 86400.0)
