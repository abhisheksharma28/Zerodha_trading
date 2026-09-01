"""Adapter for indianapi.in (Indian Stock Market API).

Covers company profile, key metrics, financial statements, shareholding,
corporate actions and news for NSE/BSE names on a free-tier-friendly REST
API. One blob is fetched per symbol and sliced by each method.

EXPERIMENTAL: response mapping is best-effort against the vendor's public
docs and has not been verified end-to-end here. Every failure degrades to
ProviderResult.missing rather than raising, so the UI never breaks.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.providers.fundamentals.base import ProviderResult

logger = get_logger(__name__)
_SOURCE = "indianapi.in"
_CACHE_TTL = 6 * 60 * 60  # fundamentals move slowly; 6h is plenty
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}


class IndianApiFundamentalsProvider:
    name = "indianapi"

    def __init__(self, api_key: str, base_url: str = "https://stock.indianapi.in") -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")

    # --- fetch + cache ------------------------------------------------

    def _blob(self, symbol: str) -> dict[str, Any] | None:
        key = symbol.upper()
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL:
            return hit[1]
        blob: dict[str, Any] | None = None
        try:
            resp = httpx.get(
                f"{self._base}/stock",
                params={"name": symbol},
                headers={"X-Api-Key": self._key},
                timeout=12.0,
            )
            if resp.status_code == 200:
                blob = resp.json()
            elif resp.status_code == 429:
                logger.warning("indianapi_rate_limited", symbol=symbol)
            else:
                logger.warning("indianapi_error", symbol=symbol, status=resp.status_code)
        except Exception as exc:  # noqa: BLE001
            logger.warning("indianapi_fetch_failed", symbol=symbol, error=str(exc))
        _cache[key] = (time.time(), blob)
        return blob

    def _section(self, symbol: str, *keys: str) -> ProviderResult:
        blob = self._blob(symbol)
        if blob is None:
            return ProviderResult.missing(_SOURCE, "provider unavailable or rate-limited")
        node: Any = blob
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return ProviderResult.missing(_SOURCE, f"'{'/'.join(keys)}' not in response")
            node = node[k]
        return ProviderResult.ok(_SOURCE, node)

    # --- interface -------------------------------------------------

    def get_company_profile(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "companyProfile")

    def get_key_metrics(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "keyMetrics")

    def get_financials(self, symbol: str, *, period: str = "annual") -> ProviderResult:
        return self._section(symbol, "financials")

    def get_quarterly_results(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "quarterlyResults")

    def get_balance_sheet(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "balanceSheet")

    def get_cash_flow(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "cashFlow")

    def get_shareholding(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "shareHoldingPattern")

    def get_corporate_actions(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "corporateActions")

    def get_news(self, symbol: str) -> ProviderResult:
        return self._section(symbol, "recentNews")
