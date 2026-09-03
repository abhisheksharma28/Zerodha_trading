"""Lightweight fundamental overlay for the scanner.

Pulls ``KeyMetrics`` from the configured (free, default yfinance) provider
and reduces it to three 0-100 sub-scores plus a short list of flags. This
is a *context filter and tie-breaker*, mostly for SWING ideas - it never
drives an intraday call. Cached per symbol per calendar day so a 5-minute
sweep does not hammer the provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.config import Settings
from app.core.logging import get_logger
from app.providers.fundamentals import get_fundamentals_provider

logger = get_logger(__name__)


@dataclass
class FundamentalView:
    available: bool
    symbol: str
    quality: float | None = None      # 0-100  (ROE, margins, low leverage)
    valuation: float | None = None    # 0-100  (cheap = high)
    growth: float | None = None       # 0-100  (revenue / profit YoY)
    bias: str = "NEUTRAL"             # SUPPORTIVE_LONG | SUPPORTIVE_SHORT | NEUTRAL
    flags: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available, "quality": self.quality,
            "valuation": self.valuation, "growth": self.growth, "bias": self.bias,
            "flags": self.flags, "metrics": self.metrics, "reason": self.reason,
        }


_cache: dict[tuple[str, str], FundamentalView] = {}


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) else None


def _get(m: Any, *keys: str) -> float | None:
    """Read a metric from either the provider dict (camelCase keys) or a
    KeyMetrics dataclass (snake_case attrs)."""
    for k in keys:
        if isinstance(m, dict):
            if m.get(k) is not None:
                return _num(m.get(k))
        elif getattr(m, k, None) is not None:
            return _num(getattr(m, k))
    return None


def _score(m: Any) -> FundamentalView:
    roe = _get(m, "roe")
    op_margin = _get(m, "operatingMargin", "operating_margin")
    de = _get(m, "debtToEquity", "debt_equity")
    if de is not None and de > 5:        # Yahoo reports D/E as a percentage
        de = de / 100.0
    pe = _get(m, "pe", "trailingPE")
    pb = _get(m, "pb", "priceToBook")
    rev_g = _get(m, "revenueGrowth", "revenue_growth_yoy")
    earn_g = _get(m, "earningsGrowth", "profit_growth_yoy")

    q_parts: list[float] = []
    if roe is not None:
        q_parts.append(_clamp(roe * 2.5))              # 20% ROE -> 50
    if op_margin is not None:
        q_parts.append(_clamp(op_margin * 3))
    if de is not None:
        q_parts.append(_clamp(100 - de * 40))         # D/E 1.0 -> 60, 2.5 -> 0
    quality = sum(q_parts) / len(q_parts) if q_parts else None

    v_parts: list[float] = []
    if pe is not None and pe > 0:
        v_parts.append(_clamp(100 - (pe - 15) * 2.5))  # PE 15 -> 100, 55 -> 0
    if pb is not None and pb > 0:
        v_parts.append(_clamp(100 - (pb - 2) * 15))
    valuation = sum(v_parts) / len(v_parts) if v_parts else None

    g_parts: list[float] = []
    if rev_g is not None:
        g_parts.append(_clamp(50 + rev_g * 2.5))
    if earn_g is not None:
        g_parts.append(_clamp(50 + earn_g * 2.0))
    growth = sum(g_parts) / len(g_parts) if g_parts else None

    flags: list[str] = []
    if de is not None and de > 2.0:
        flags.append("high leverage")
    if pe is not None and pe > 60:
        flags.append("rich valuation")
    if earn_g is not None and earn_g < -10:
        flags.append("earnings contracting")
    if roe is not None and roe > 18 and (valuation or 0) > 40:
        flags.append("quality at a fair price")

    strong = [s for s in (quality, growth) if s is not None]
    avg_qg = sum(strong) / len(strong) if strong else 50.0
    bias = "SUPPORTIVE_LONG" if avg_qg >= 62 else "SUPPORTIVE_SHORT" if avg_qg <= 38 else "NEUTRAL"

    return FundamentalView(
        available=quality is not None or valuation is not None or growth is not None,
        symbol="", quality=quality, valuation=valuation, growth=growth, bias=bias, flags=flags,
        metrics={
            "pe": pe, "pb": pb, "roe": roe, "debt_equity": de, "operating_margin": op_margin,
            "revenue_growth_yoy": rev_g, "profit_growth_yoy": earn_g,
            "week52_high": _get(m, "week52High", "week52_high"),
            "week52_low": _get(m, "week52Low", "week52_low"),
            "beta": _get(m, "beta"),
        },
    )


def view(settings: Settings, symbol: str, *, asset_class: str = "EQUITY") -> FundamentalView:
    if asset_class != "EQUITY":
        return FundamentalView(available=False, symbol=symbol, reason=f"{asset_class} has no equity fundamentals")
    key = (symbol.upper(), date.today().isoformat())
    if key in _cache:
        return _cache[key]
    try:
        provider = get_fundamentals_provider(settings)
        res = provider.get_key_metrics(symbol)
        if not res.available or res.data is None:
            v = FundamentalView(available=False, symbol=symbol, reason=res.reason or "no metrics")
        else:
            v = _score(res.data)
            v.symbol = symbol
    except Exception as exc:  # noqa: BLE001 - fundamentals are an optional overlay
        logger.warning("scanner_fundamentals_failed", symbol=symbol, error=str(exc))
        v = FundamentalView(available=False, symbol=symbol, reason=f"{type(exc).__name__}")
    _cache[key] = v
    return v


def clear_cache() -> None:
    _cache.clear()
