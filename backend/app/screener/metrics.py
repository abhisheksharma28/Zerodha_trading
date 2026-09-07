"""Per-stock feature extraction for the screener.

Fundamentals come from the configured provider's ``get_key_metrics``
(a camelCase dict — read defensively, Yahoo omits fields freely).
Technicals are derived from ~1y of Kite daily candles: last close, the
real 52-week high/low, 50/200-day SMAs and 1m / 6m returns.

Everything is best-effort. ``StockMetrics.completeness`` is the fraction
of the inputs the scorer wants that were actually available, and the
scorer uses it to cap thin-data names at HOLD.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.screener import technical_rating

logger = get_logger(__name__)

# the fundamental inputs the scorer would like to have, for completeness scoring
_WANTED_FUNDAMENTALS = (
    "pe", "pb", "ps", "roe", "debtToEquity", "operatingMargin",
    "profitMargin", "revenueGrowth", "earningsGrowth",
)


@dataclass
class StockMetrics:
    symbol: str
    name: str | None = None
    sector: str | None = None

    # fundamentals (raw, as pulled)
    market_cap: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    roe: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    operating_margin: float | None = None
    profit_margin: float | None = None
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    # technicals (from candles)
    ltp: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    sma50: float | None = None
    sma200: float | None = None
    ret_1m: float | None = None
    ret_6m: float | None = None

    # TradingView-style technical rating (see app.screener.technical_rating)
    ta: dict[str, Any] | None = None

    fundamentals_ok: bool = False
    technicals_ok: bool = False
    missing: list[str] = field(default_factory=list)

    @property
    def pct_from_52w_high(self) -> float | None:
        if self.ltp and self.week52_high:
            return (self.ltp - self.week52_high) / self.week52_high * 100.0
        return None

    @property
    def pct_from_52w_low(self) -> float | None:
        if self.ltp and self.week52_low:
            return (self.ltp - self.week52_low) / self.week52_low * 100.0
        return None

    @property
    def completeness(self) -> float:
        have = sum(1 for k in _WANTED_FUNDAMENTALS if getattr(self, _FIELD_BY_KEY[k]) is not None)
        frac_f = have / len(_WANTED_FUNDAMENTALS)
        frac_t = 1.0 if (self.technicals_ok and self.sma200 is not None) else 0.4 if self.ltp else 0.0
        return round(0.65 * frac_f + 0.35 * frac_t, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_cap": self.market_cap, "pe": self.pe, "forward_pe": self.forward_pe,
            "pb": self.pb, "ps": self.ps, "ev_ebitda": self.ev_ebitda,
            "dividend_yield": self.dividend_yield, "roe": self.roe,
            "debt_equity": self.debt_equity, "current_ratio": self.current_ratio,
            "operating_margin": self.operating_margin, "profit_margin": self.profit_margin,
            "revenue_growth": self.revenue_growth, "earnings_growth": self.earnings_growth,
            "ltp": self.ltp, "week52_high": self.week52_high, "week52_low": self.week52_low,
            "sma50": self.sma50, "sma200": self.sma200,
            "ret_1m": self.ret_1m, "ret_6m": self.ret_6m,
            "pct_from_52w_high": self.pct_from_52w_high,
            "pct_from_52w_low": self.pct_from_52w_low,
            "completeness": self.completeness,
        }


_FIELD_BY_KEY = {
    "pe": "pe", "pb": "pb", "ps": "ps", "roe": "roe", "debtToEquity": "debt_equity",
    "operatingMargin": "operating_margin", "profitMargin": "profit_margin",
    "revenueGrowth": "revenue_growth", "earningsGrowth": "earnings_growth",
}


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x  # drop NaN


def from_fundamentals(m: StockMetrics, km: dict[str, Any] | None, profile: dict[str, Any] | None) -> None:
    if profile:
        m.name = m.name or profile.get("company_name")
        m.sector = m.sector or profile.get("sector")
    if not km:
        m.missing.append("fundamentals")
        return
    m.fundamentals_ok = True
    m.market_cap = _f(km.get("marketCap"))
    m.pe = _f(km.get("pe"))
    m.forward_pe = _f(km.get("forwardPe"))
    m.pb = _f(km.get("pb"))
    m.ps = _f(km.get("ps"))
    m.ev_ebitda = _f(km.get("evEbitda") or km.get("enterpriseToEbitda"))
    m.dividend_yield = _f(km.get("dividendYield"))
    m.roe = _f(km.get("roe"))
    m.debt_equity = _f(km.get("debtToEquity"))
    m.current_ratio = _f(km.get("currentRatio"))
    m.operating_margin = _f(km.get("operatingMargin"))
    m.profit_margin = _f(km.get("profitMargin"))
    m.revenue_growth = _f(km.get("revenueGrowth"))
    m.earnings_growth = _f(km.get("earningsGrowth"))


def from_candles(m: StockMetrics, candles: list[list[Any]] | None) -> None:
    """candles: Kite rows [ts, o, h, l, c, v], oldest first."""
    rows = [r for r in candles or [] if len(r) >= 5 and r[4] is not None]
    closes = [float(r[4]) for r in rows]
    highs = [float(r[2]) for r in rows if r[2] is not None]
    lows = [float(r[3]) for r in rows if r[3] is not None]
    volumes = [float(r[5]) if len(r) > 5 and r[5] is not None else 0.0 for r in rows]
    if len(closes) < 20:
        m.missing.append("candles")
        return
    m.technicals_ok = True
    m.ltp = closes[-1]
    window = closes[-252:]
    m.week52_high = max(highs[-252:]) if highs else max(window)
    m.week52_low = min(lows[-252:]) if lows else min(window)
    if len(closes) >= 50:
        m.sma50 = sum(closes[-50:]) / 50
    if len(closes) >= 200:
        m.sma200 = sum(closes[-200:]) / 200
    if len(closes) >= 22:
        m.ret_1m = (closes[-1] - closes[-22]) / closes[-22] * 100.0
    if len(closes) >= 126:
        m.ret_6m = (closes[-1] - closes[-126]) / closes[-126] * 100.0

    m.ta = technical_rating.rate(closes, highs, lows, volumes)


def candle_window() -> tuple[datetime, datetime]:
    to_dt = datetime.now()
    return to_dt - timedelta(days=400), to_dt
