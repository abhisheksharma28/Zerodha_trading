"""Incremental, O(1)-per-update technical indicators for the live path.

Each class keeps just enough state to advance one step when a new value (or
bar) arrives — no re-scanning history, no re-allocating windows. Results are
defined to match the batch functions in ``app.strategies.indicators`` exactly
(same seeding, same Wilder smoothing), so a strategy behaves identically
whether it is fed bar-by-bar live or a full series in a backtest. See
``tests/test_live_indicators.py`` for the parity checks.

``update(...)`` returns the current indicator value, or ``None`` until there
is enough data.
"""

from __future__ import annotations

import math
from collections import deque


class RollingMean:
    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)
        self._sum = 0.0

    def update(self, x: float) -> float | None:
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]
        self._buf.append(x)
        self._sum += x
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    @property
    def value(self) -> float | None:
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period


SMA = RollingMean


class RollingStd:
    """Sample stdev (ddof=1 by default) over a rolling window — matches
    ``app.strategies.indicators.rolling_std``."""

    def __init__(self, period: int, *, ddof: int = 1) -> None:
        if period <= 1:
            raise ValueError("period must be > 1")
        self.period = period
        self.ddof = ddof
        self._buf: deque[float] = deque(maxlen=period)

    def update(self, x: float) -> float | None:
        self._buf.append(x)
        if len(self._buf) < self.period:
            return None
        m = sum(self._buf) / self.period
        var = sum((v - m) ** 2 for v in self._buf) / (self.period - self.ddof)
        return math.sqrt(var) if var > 0 else 0.0


class EMA:
    """Standard EMA seeded with the SMA of the first ``period`` points —
    matches ``app.strategies.indicators.ema``."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._k = 2.0 / (period + 1.0)
        self._seed: list[float] = []
        self._ema: float | None = None

    def update(self, x: float) -> float | None:
        if self._ema is None:
            self._seed.append(x)
            if len(self._seed) < self.period:
                return None
            self._ema = sum(self._seed) / self.period
            return self._ema
        self._ema = x * self._k + self._ema * (1.0 - self._k)
        return self._ema

    @property
    def value(self) -> float | None:
        return self._ema


class RSI:
    """Wilder RSI — SMA-seeded average gain/loss then Wilder smoothing.
    Matches ``app.strategies.indicators.rsi``."""

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._prev: float | None = None
        self._gains: list[float] = []
        self._losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None

    def update(self, x: float) -> float | None:
        if self._prev is None:
            self._prev = x
            return None
        change = x - self._prev
        self._prev = x
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        if self._avg_gain is None or self._avg_loss is None:
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) < self.period:
                return None
            self._avg_gain = sum(self._gains) / self.period
            self._avg_loss = sum(self._losses) / self.period
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period

        if self._avg_loss == 0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - 100.0 / (1.0 + rs)


class WilderATR:
    """Wilder ATR fed bar-by-bar. Matches ``app.strategies.indicators.atr``
    (first ATR = SMA of the first ``period`` true ranges, then Wilder)."""

    def __init__(self, period: int = 14) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._prev_close: float | None = None
        self._trs: list[float] = []
        self._atr: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        if self._prev_close is None:
            self._prev_close = close
            return None
        tr = max(high - low, abs(high - self._prev_close), abs(low - self._prev_close))
        self._prev_close = close
        if self._atr is None:
            self._trs.append(tr)
            if len(self._trs) < self.period:
                return None
            self._atr = sum(self._trs) / self.period
        else:
            self._atr = (self._atr * (self.period - 1) + tr) / self.period
        return self._atr

    @property
    def value(self) -> float | None:
        return self._atr


class SessionVWAP:
    """Cumulative volume-weighted average price for the current session.
    Call :meth:`reset` at the session boundary."""

    def __init__(self) -> None:
        self._pv = 0.0
        self._v = 0.0

    def update(self, price: float, volume: float) -> float | None:
        if volume < 0:
            return self.value
        self._pv += price * volume
        self._v += volume
        return self.value

    @property
    def value(self) -> float | None:
        return self._pv / self._v if self._v > 0 else None

    def reset(self) -> None:
        self._pv = 0.0
        self._v = 0.0


class Bollinger:
    def __init__(self, period: int = 20, num_std: float = 2.0) -> None:
        self.num_std = num_std
        self._mean = RollingMean(period)
        self._std = RollingStd(period)

    def update(self, x: float) -> tuple[float, float, float] | None:
        m = self._mean.update(x)
        s = self._std.update(x)
        if m is None or s is None:
            return None
        return (m - self.num_std * s, m, m + self.num_std * s)


class MACD:
    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        self._fast = EMA(fast)
        self._slow = EMA(slow)
        self._signal = EMA(signal)

    def update(self, x: float) -> tuple[float, float, float] | None:
        f = self._fast.update(x)
        s = self._slow.update(x)
        if f is None or s is None:
            return None
        macd = f - s
        sig = self._signal.update(macd)
        if sig is None:
            return None
        return (macd, sig, macd - sig)


class RollingExtrema:
    """Rolling (min, max) over the last ``period`` values."""

    def __init__(self, period: int) -> None:
        if period <= 0:
            raise ValueError("period must be positive")
        self.period = period
        self._buf: deque[float] = deque(maxlen=period)

    def update(self, x: float) -> tuple[float, float] | None:
        self._buf.append(x)
        if len(self._buf) < self.period:
            return None
        return (min(self._buf), max(self._buf))


# --- a bundle used by the live indicator engine -----------------------


def _round(v: float | None, digits: int = 4) -> float | None:
    return round(v, digits) if isinstance(v, (int, float)) else None


class IndicatorSet:
    """Per-instrument bundle updated one bar at a time. Price indicators use
    the close; ATR uses the bar high/low; VWAP is fed the bar's typical
    price and volume. Indicators that don't expose a stored ``.value``
    (RSI / Bollinger / MACD / extrema) have their last result cached here."""

    def __init__(self) -> None:
        self.ema9 = EMA(9)
        self.ema20 = EMA(20)
        self.ema50 = EMA(50)
        self.sma20 = RollingMean(20)
        self.rsi14 = RSI(14)
        self.atr14 = WilderATR(14)
        self.vwap = SessionVWAP()
        self.bb20 = Bollinger(20, 2.0)
        self.macd = MACD()
        self.hl20 = RollingExtrema(20)
        self.bars = 0
        self._rsi: float | None = None
        self._bb: tuple[float, float, float] | None = None
        self._macd: tuple[float, float, float] | None = None
        self._hl: tuple[float, float] | None = None

    def update_bar(
        self, *, high: float, low: float, close: float, volume: float = 0.0
    ) -> dict[str, object]:
        self.bars += 1
        self.ema9.update(close)
        self.ema20.update(close)
        self.ema50.update(close)
        self.sma20.update(close)
        self._rsi = self.rsi14.update(close)
        self.atr14.update(high, low, close)
        self.vwap.update((high + low + close) / 3.0, volume)
        self._bb = self.bb20.update(close)
        self._macd = self.macd.update(close)
        self._hl = self.hl20.update(close)
        return self.snapshot()

    def new_session(self) -> None:
        self.vwap.reset()

    def snapshot(self) -> dict[str, object]:
        return {
            "bars": self.bars,
            "ema9": _round(self.ema9.value),
            "ema20": _round(self.ema20.value),
            "ema50": _round(self.ema50.value),
            "sma20": _round(self.sma20.value),
            "rsi14": _round(self._rsi),
            "atr14": _round(self.atr14.value),
            "vwap": _round(self.vwap.value),
            "bb_lower": _round(self._bb[0]) if self._bb else None,
            "bb_mid": _round(self._bb[1]) if self._bb else None,
            "bb_upper": _round(self._bb[2]) if self._bb else None,
            "macd": _round(self._macd[0]) if self._macd else None,
            "macd_signal": _round(self._macd[1]) if self._macd else None,
            "macd_hist": _round(self._macd[2]) if self._macd else None,
            "roll_low20": _round(self._hl[0]) if self._hl else None,
            "roll_high20": _round(self._hl[1]) if self._hl else None,
        }
