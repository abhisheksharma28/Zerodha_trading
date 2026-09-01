"""Fundamentals provider selection.

``FUNDAMENTALS_PROVIDER`` env var picks the adapter:
  yfinance  -> YFinanceFundamentalsProvider  (default; free, no key, Yahoo Finance)
  indianapi -> IndianApiFundamentalsProvider  (needs FUNDAMENTALS_API_KEY; ~500 calls/mo free)
  none      -> NullFundamentalsProvider (UI shows "not configured")
"""

from __future__ import annotations

from functools import lru_cache

from app.config import Settings, get_settings
from app.providers.fundamentals.base import (
    CompanyProfile,
    FundamentalDataProvider,
    KeyMetrics,
    ProviderResult,
)
from app.providers.fundamentals.indian_api import IndianApiFundamentalsProvider
from app.providers.fundamentals.null import NullFundamentalsProvider
from app.providers.fundamentals.yfinance_provider import YFinanceFundamentalsProvider

__all__ = [
    "CompanyProfile",
    "FundamentalDataProvider",
    "KeyMetrics",
    "ProviderResult",
    "get_fundamentals_provider",
]


@lru_cache(maxsize=1)
def _build(name: str, key: str, base: str) -> FundamentalDataProvider:
    if name == "indianapi" and key:
        return IndianApiFundamentalsProvider(key, base or "https://stock.indianapi.in")
    if name == "yfinance":
        return YFinanceFundamentalsProvider()
    if name in ("", "none"):
        return NullFundamentalsProvider()
    # unknown / misconfigured -> free default rather than nothing
    return YFinanceFundamentalsProvider()


def get_fundamentals_provider(settings: Settings | None = None) -> FundamentalDataProvider:
    s = settings or get_settings()
    return _build(
        (s.fundamentals_provider or "yfinance").lower(),
        s.fundamentals_api_key or "",
        s.fundamentals_api_base or "",
    )
