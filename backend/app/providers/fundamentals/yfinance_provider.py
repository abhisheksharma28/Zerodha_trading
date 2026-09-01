"""Free, no-key fundamentals via yfinance (Yahoo Finance) for NSE names.

Covers company profile, valuation / quality / growth metrics, income
statement, balance sheet, cash flow, an approximate holder split, dividends
/ splits and recent news. Indian promoter/FII/DII granularity is NOT
available from Yahoo — use a dedicated Indian provider for that.

yfinance scrapes Yahoo and can rate-limit or change shape, so every call is
wrapped: any failure returns ProviderResult.missing.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.logging import get_logger
from app.providers.fundamentals.base import ProviderResult

logger = get_logger(__name__)
_SOURCE = "yfinance"
_TTL = 6 * 60 * 60
_cache: dict[str, tuple[float, Any]] = {}


def _df_to_periods(df: Any, limit: int = 5) -> list[dict[str, Any]] | None:
    try:
        if df is None or getattr(df, "empty", True):
            return None
        out = []
        for col in list(df.columns)[:limit]:
            label = str(col.date()) if hasattr(col, "date") else str(col)
            series = df[col]
            out.append({"period": label, **{str(k): _num(v) for k, v in series.items()}})
        return out or None
    except Exception:  # noqa: BLE001
        return None


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # drop NaN


class YFinanceFundamentalsProvider:
    name = "yfinance"

    def __init__(self, suffix: str = ".NS") -> None:
        self._suffix = suffix

    def _ticker(self, symbol: str) -> Any | None:
        key = symbol.upper()
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _TTL:
            return hit[1]
        try:
            import yfinance as yf

            t = yf.Ticker(f"{symbol}{self._suffix}")
            _ = t.info  # force the fetch so failures surface here
            _cache[key] = (time.time(), t)
            return t
        except Exception as exc:  # noqa: BLE001
            logger.warning("yfinance_fetch_failed", symbol=symbol, error=str(exc))
            _cache[key] = (time.time(), None)
            return None

    def _info(self, symbol: str) -> dict[str, Any] | None:
        t = self._ticker(symbol)
        try:
            return dict(t.info) if t is not None else None
        except Exception:  # noqa: BLE001
            return None

    # --- interface -------------------------------------------------

    def get_company_profile(self, symbol: str) -> ProviderResult:
        i = self._info(symbol)
        if not i:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        return ProviderResult.ok(_SOURCE, {
            "company_name": i.get("longName") or i.get("shortName"),
            "sector": i.get("sector"),
            "industry": i.get("industry"),
            "website": i.get("website"),
            "description": i.get("longBusinessSummary"),
            "employees": i.get("fullTimeEmployees"),
            "country": i.get("country"),
        })

    def get_key_metrics(self, symbol: str) -> ProviderResult:
        i = self._info(symbol)
        if not i:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        pct = lambda x: round(x * 100.0, 2) if isinstance(x, (int, float)) else None  # noqa: E731
        return ProviderResult.ok(_SOURCE, {
            "marketCap": i.get("marketCap"),
            "pe": i.get("trailingPE"),
            "forwardPe": i.get("forwardPE"),
            "pb": i.get("priceToBook"),
            "ps": i.get("priceToSalesTrailing12Months"),
            "dividendYield": pct(i.get("dividendYield")),
            "roe": pct(i.get("returnOnEquity")),
            "roa": pct(i.get("returnOnAssets")),
            "debtToEquity": i.get("debtToEquity"),
            "currentRatio": i.get("currentRatio"),
            "operatingMargin": pct(i.get("operatingMargins")),
            "profitMargin": pct(i.get("profitMargins")),
            "eps": i.get("trailingEps"),
            "bookValue": i.get("bookValue"),
            "revenueGrowth": pct(i.get("revenueGrowth")),
            "earningsGrowth": pct(i.get("earningsGrowth")),
            "week52High": i.get("fiftyTwoWeekHigh"),
            "week52Low": i.get("fiftyTwoWeekLow"),
            "beta": i.get("beta"),
        })

    def _statement(self, symbol: str, attr: str, label: str) -> ProviderResult:
        t = self._ticker(symbol)
        if t is None:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        data = _df_to_periods(getattr(t, attr, None))
        return ProviderResult.ok(_SOURCE, data) if data else ProviderResult.missing(
            _SOURCE, f"no {label} from Yahoo Finance"
        )

    def get_financials(self, symbol: str, *, period: str = "annual") -> ProviderResult:
        return self._statement(symbol, "financials", "income statement")

    def get_quarterly_results(self, symbol: str) -> ProviderResult:
        return self._statement(symbol, "quarterly_financials", "quarterly results")

    def get_balance_sheet(self, symbol: str) -> ProviderResult:
        return self._statement(symbol, "balance_sheet", "balance sheet")

    def get_cash_flow(self, symbol: str) -> ProviderResult:
        return self._statement(symbol, "cashflow", "cash flow")

    def get_shareholding(self, symbol: str) -> ProviderResult:
        t = self._ticker(symbol)
        if t is None:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        try:
            mh = t.major_holders
            if mh is None or mh.empty:
                return ProviderResult.missing(_SOURCE, "no holder data from Yahoo Finance")
            d = mh.to_dict().get("Value", mh.to_dict())
            return ProviderResult.ok(_SOURCE, {
                "insiders_pct": _num(d.get("insidersPercentHeld")),
                "institutions_pct": _num(d.get("institutionsPercentHeld")),
                "institutions_count": _num(d.get("institutionsCount")),
                "note": "Yahoo split only — promoter/FII/DII detail needs an Indian provider.",
            })
        except Exception as exc:  # noqa: BLE001
            return ProviderResult.missing(_SOURCE, f"holder parse failed: {exc}")

    def get_corporate_actions(self, symbol: str) -> ProviderResult:
        t = self._ticker(symbol)
        if t is None:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        try:
            div = t.dividends
            spl = t.splits
            return ProviderResult.ok(_SOURCE, {
                "dividends": [
                    {"date": str(k.date()), "amount": _num(v)} for k, v in div.tail(8).items()
                ] if div is not None and not div.empty else [],
                "splits": [
                    {"date": str(k.date()), "ratio": _num(v)} for k, v in spl.tail(8).items()
                ] if spl is not None and not spl.empty else [],
            })
        except Exception as exc:  # noqa: BLE001
            return ProviderResult.missing(_SOURCE, f"corporate-actions parse failed: {exc}")

    def get_news(self, symbol: str) -> ProviderResult:
        t = self._ticker(symbol)
        if t is None:
            return ProviderResult.missing(_SOURCE, "Yahoo Finance did not return data")
        try:
            items = getattr(t, "news", []) or []
            out = [
                {
                    "title": n.get("title") or (n.get("content") or {}).get("title"),
                    "publisher": n.get("publisher"),
                    "link": n.get("link") or (n.get("content") or {}).get("canonicalUrl", {}).get("url"),
                    "published": n.get("providerPublishTime"),
                }
                for n in items[:12]
            ]
            return ProviderResult.ok(_SOURCE, out) if out else ProviderResult.missing(
                _SOURCE, "no news from Yahoo Finance"
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderResult.missing(_SOURCE, f"news parse failed: {exc}")
