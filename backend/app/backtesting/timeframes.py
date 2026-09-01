"""Canonical timeframe registry for the backtest / strategy engine.

One place that knows, for every supported bar size:

* its **canonical token** (``"5m"``, ``"1d"`` …) and the aliases that map to
  it (``"5"``, ``"5min"``, ``"5minute"``, ``"5m"``);
* the **Kite historical-data interval** string to request it with
  (``"5minute"``, ``"day"`` …);
* whether it is **intraday** (multiple bars per session) or end-of-day;
* how many bars of it there are in a trading year, so annualised metrics
  (Sharpe, CAGR, Sortino) are correct instead of always assuming 252.

Strategies declare which of these they support; the backtest service
validates the requested timeframe against that set and refuses — with a
clear reason — rather than silently producing wrong results on data the
strategy was never designed for.
"""

from __future__ import annotations

from dataclasses import dataclass

# NSE cash session: 09:15–15:30 IST = 375 minutes. ~250 trading days a year.
_SESSION_MINUTES = 375
_TRADING_DAYS_PER_YEAR = 250


@dataclass(frozen=True)
class Timeframe:
    token: str            # canonical, e.g. "5m"
    label: str            # human, e.g. "5 minutes"
    kite_interval: str     # Kite historical API interval, e.g. "5minute"
    minutes: int           # bar length in minutes (1440 for a day)
    intraday: bool

    @property
    def bars_per_year(self) -> float:
        if not self.intraday:
            return float(_TRADING_DAYS_PER_YEAR)
        per_day = _SESSION_MINUTES / self.minutes
        return per_day * _TRADING_DAYS_PER_YEAR

    @property
    def seconds(self) -> int:
        return self.minutes * 60


_TIMEFRAMES: tuple[Timeframe, ...] = (
    Timeframe("1m", "1 minute", "minute", 1, True),
    Timeframe("3m", "3 minutes", "3minute", 3, True),
    Timeframe("5m", "5 minutes", "5minute", 5, True),
    Timeframe("10m", "10 minutes", "10minute", 10, True),
    Timeframe("15m", "15 minutes", "15minute", 15, True),
    Timeframe("30m", "30 minutes", "30minute", 30, True),
    Timeframe("1h", "1 hour", "60minute", 60, True),
    Timeframe("1d", "1 day", "day", 1440, False),
)

_BY_TOKEN: dict[str, Timeframe] = {}
for _tf in _TIMEFRAMES:
    # canonical + a generous set of aliases so UI / API / legacy rows all resolve
    _aliases = {
        _tf.token,
        _tf.label,
        _tf.kite_interval,
        _tf.token.rstrip("mhd"),          # "5"
        f"{_tf.minutes}min",              # "5min"
        f"{_tf.minutes}minute",           # "5minute"
        f"{_tf.minutes}minutes",
        f"{_tf.minutes}m",               # "5m"
    }
    if not _tf.intraday:
        _aliases |= {"day", "1day", "daily", "eod", "D", "1D"}
    if _tf.token == "1h":
        _aliases |= {"60m", "60min", "60minute", "hour", "1hour", "H", "1H"}
    for _a in _aliases:
        _BY_TOKEN[_a.lower()] = _tf

ALL_TIMEFRAMES: tuple[str, ...] = tuple(t.token for t in _TIMEFRAMES)
INTRADAY_TIMEFRAMES: tuple[str, ...] = tuple(t.token for t in _TIMEFRAMES if t.intraday)
EOD_TIMEFRAMES: tuple[str, ...] = tuple(t.token for t in _TIMEFRAMES if not t.intraday)


class UnknownTimeframeError(ValueError):
    pass


def resolve(token: str) -> Timeframe:
    """Any alias -> the canonical Timeframe. Raises UnknownTimeframeError."""
    tf = _BY_TOKEN.get(str(token).strip().lower())
    if tf is None:
        raise UnknownTimeframeError(
            f"Unknown timeframe {token!r}. Supported: {', '.join(ALL_TIMEFRAMES)}."
        )
    return tf


def canonical(token: str) -> str:
    return resolve(token).token


def kite_interval(token: str) -> str:
    return resolve(token).kite_interval


def bars_per_year(token: str) -> float:
    return resolve(token).bars_per_year


def is_intraday(token: str) -> bool:
    return resolve(token).intraday


def catalog() -> list[dict]:
    """Everything the frontend needs to render a timeframe selector."""
    return [
        {
            "token": t.token,
            "label": t.label,
            "kite_interval": t.kite_interval,
            "minutes": t.minutes,
            "intraday": t.intraday,
            "bars_per_year": round(t.bars_per_year, 2),
        }
        for t in _TIMEFRAMES
    ]
