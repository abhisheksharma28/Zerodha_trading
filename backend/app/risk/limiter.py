"""In-process token-bucket rate limiters.

Deliberately set *below* Kite's own published limits (see
docs/ZERODHA_API_NOTES.md section 4) so the platform fails safe internally —
hitting our own ceiling is a risk event to investigate, not a signal to push
closer to the exchange's actual cap. Backed by Redis-free in-memory state for
now (single backend process); if the app ever runs multiple backend
processes, this must move to a Redis-backed limiter (e.g. sliding window in
Lua) instead of relying on per-process memory.
"""

import threading
import time

from app.config import get_settings


class RateLimiter:
    def __init__(self, rate_per_second: float, burst: int | None = None) -> None:
        self.rate = rate_per_second
        self.capacity = burst or max(1, int(rate_per_second))
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
            if time.monotonic() >= deadline:
                from app.brokers.exceptions import RateLimitExceeded

                raise RateLimitExceeded(
                    f"Internal rate limit ({self.rate}/s) exceeded — refusing to call broker."
                )
            time.sleep(0.05)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    @classmethod
    def for_orders(cls) -> "RateLimiter":
        settings = get_settings()
        return cls(rate_per_second=settings.risk_max_orders_per_second)

    @classmethod
    def for_quotes(cls) -> "RateLimiter":
        return cls(rate_per_second=1)  # Kite hard limit is 1 req/s

    @classmethod
    def for_historical(cls) -> "RateLimiter":
        return cls(rate_per_second=3)  # Kite hard limit is 3 req/s
