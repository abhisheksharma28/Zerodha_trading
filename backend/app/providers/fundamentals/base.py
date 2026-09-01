"""Provider-agnostic fundamentals interface + normalized model.

The UI and services depend ONLY on these types. Concrete adapters
(indianapi.in, FinEdge, a licensed vendor, …) live beside this file and are
selected at runtime by ``get_fundamentals_provider(settings)``. When no
provider is configured the null adapter returns ``available=False`` for
every call so the UI shows "Data provider not configured" rather than
breaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass
class ProviderResult:
    """Envelope every provider method returns. ``data`` is None when
    ``available`` is False (no provider, not covered, rate-limited, error)."""

    available: bool
    source: str
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: Any = None
    reason: str | None = None

    @classmethod
    def missing(cls, source: str, reason: str) -> ProviderResult:
        return cls(available=False, source=source, reason=reason)

    @classmethod
    def ok(cls, source: str, data: Any) -> ProviderResult:
        return cls(available=True, source=source, data=data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "source": self.source,
            "fetched_at": self.fetched_at,
            "reason": self.reason,
            "data": self.data,
        }


@dataclass
class CompanyProfile:
    symbol: str
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    isin: str | None = None
    description: str | None = None
    website: str | None = None
    listing_date: str | None = None
    face_value: float | None = None


@dataclass
class KeyMetrics:
    market_cap: float | None = None
    pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    roe: float | None = None
    roce: float | None = None
    debt_equity: float | None = None
    current_ratio: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    eps: float | None = None
    book_value: float | None = None
    revenue_growth_yoy: float | None = None
    profit_growth_yoy: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    beta: float | None = None


@runtime_checkable
class FundamentalDataProvider(Protocol):
    name: str

    def get_company_profile(self, symbol: str) -> ProviderResult: ...
    def get_key_metrics(self, symbol: str) -> ProviderResult: ...
    def get_financials(self, symbol: str, *, period: str = "annual") -> ProviderResult: ...
    def get_quarterly_results(self, symbol: str) -> ProviderResult: ...
    def get_balance_sheet(self, symbol: str) -> ProviderResult: ...
    def get_cash_flow(self, symbol: str) -> ProviderResult: ...
    def get_shareholding(self, symbol: str) -> ProviderResult: ...
    def get_corporate_actions(self, symbol: str) -> ProviderResult: ...
    def get_news(self, symbol: str) -> ProviderResult: ...
