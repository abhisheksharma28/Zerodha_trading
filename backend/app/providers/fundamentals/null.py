"""Fallback provider: everything is 'not configured'."""

from __future__ import annotations

from app.providers.fundamentals.base import ProviderResult

_REASON = (
    "No fundamentals provider is configured. Set FUNDAMENTALS_PROVIDER (and its "
    "API key) in the environment — see .env.example."
)


class NullFundamentalsProvider:
    name = "none"

    def _miss(self) -> ProviderResult:
        return ProviderResult.missing("none", _REASON)

    def get_company_profile(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_key_metrics(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_financials(self, symbol: str, *, period: str = "annual") -> ProviderResult:
        return self._miss()

    def get_quarterly_results(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_balance_sheet(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_cash_flow(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_shareholding(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_corporate_actions(self, symbol: str) -> ProviderResult:
        return self._miss()

    def get_news(self, symbol: str) -> ProviderResult:
        return self._miss()
