"""Automatic trading halts, separate from the manual kill switch.

A breaker trips on a condition the system detects on its own — stale market
data, a dropped broker feed — and, while any breaker is tripped,
``OrderRouter`` refuses new orders exactly as it does for the manual kill
switch. Manual and automatic halts are independent: clearing one never
clears the other.

The async monitor in :mod:`app.live.engine` feeds :meth:`observe`; the
router consults :data:`BREAKERS`.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

REASON_DATA_STALE = "market_data_stale"
REASON_FEED_DOWN = "broker_feed_disconnected"


class CircuitBreakers:
    def __init__(self) -> None:
        self._reasons: dict[str, str] = {}       # reason -> human detail
        self._tripped_at: dict[str, float] = {}
        self._manual_override_clear = False
        self._lock = threading.Lock()

    @property
    def halted(self) -> bool:
        with self._lock:
            return bool(self._reasons) and not self._manual_override_clear

    def trip(self, reason: str, detail: str) -> None:
        with self._lock:
            if reason not in self._reasons:
                self._tripped_at[reason] = time.time()
                logger.warning("circuit_breaker_tripped", reason=reason, detail=detail)
            self._reasons[reason] = detail
            self._manual_override_clear = False

    def clear(self, reason: str) -> None:
        with self._lock:
            if reason in self._reasons:
                self._reasons.pop(reason, None)
                self._tripped_at.pop(reason, None)
                logger.info("circuit_breaker_cleared", reason=reason)
            if not self._reasons:
                self._manual_override_clear = False

    def force_clear_all(self) -> None:
        """Operator override: resume trading even though a condition may
        still be present (use with care)."""
        with self._lock:
            self._manual_override_clear = True
            logger.warning("circuit_breaker_force_cleared", reasons=list(self._reasons))

    def observe(
        self,
        *,
        feed_connected: bool,
        seconds_since_tick: float | None,
        stale_threshold: float,
        market_open: bool,
    ) -> None:
        if not feed_connected:
            self.trip(REASON_FEED_DOWN, "no live connection to the broker market-data feed")
        else:
            self.clear(REASON_FEED_DOWN)

        if (
            feed_connected
            and market_open
            and seconds_since_tick is not None
            and seconds_since_tick > stale_threshold
        ):
            self.trip(
                REASON_DATA_STALE,
                f"no tick for {seconds_since_tick:.0f}s (> {stale_threshold:.0f}s)",
            )
        else:
            self.clear(REASON_DATA_STALE)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            return {
                "halted": bool(self._reasons) and not self._manual_override_clear,
                "override_active": self._manual_override_clear,
                "reasons": [
                    {
                        "reason": r,
                        "detail": d,
                        "tripped_seconds_ago": round(now - self._tripped_at.get(r, now), 1),
                    }
                    for r, d in self._reasons.items()
                ],
            }

    def reset(self) -> None:  # test hook
        with self._lock:
            self._reasons.clear()
            self._tripped_at.clear()
            self._manual_override_clear = False


BREAKERS = CircuitBreakers()


def is_market_open(now: float | None = None) -> bool:
    """Coarse NSE session check in IST (Mon-Fri, 09:15-15:35). Deliberately
    a hair past the close so a last-minute stale feed still trips."""
    import datetime as _dt

    ts = _dt.datetime.fromtimestamp(now or time.time(), tz=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    if ts.weekday() >= 5:
        return False
    minutes = ts.hour * 60 + ts.minute
    return 9 * 60 + 15 <= minutes <= 15 * 60 + 35
