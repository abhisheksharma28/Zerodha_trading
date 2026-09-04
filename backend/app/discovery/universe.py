"""The curated discovery universe.

Phase 1 is a compact, liquid, long-history multi-asset ETF set — one
representative per exposure — spanning global equity, real assets and
fixed income. It is deliberately small: 10+ years of clean data on ~15
low-correlation building blocks is enough to discover robust 5-10 asset
portfolios (the all-weather / permanent-portfolio literature uses 4-6).

Phase 1b widens this (more sector / factor / duration ETFs, Indian ETFs
from the Kite candle store, individual equities).

Each entry: symbol, name, asset_class, sub_class, region, currency,
provider ("twelvedata" | "kite"), provider_symbol, an approximate expense
ratio and the ETF's inception year (for the tier check).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnivInstrument:
    symbol: str
    name: str
    asset_class: str      # EQUITY | BOND | COMMODITY | REIT | CASH | MIXED
    sub_class: str
    region: str           # US | INTL | EM | IN | GLOBAL
    currency: str
    provider: str
    provider_symbol: str
    expense_ratio: float | None
    inception_year: int | None


CORE: list[UnivInstrument] = [
    # --- global equity ------------------------------------------------
    UnivInstrument("SPY", "SPDR S&P 500 ETF", "EQUITY", "US Large Cap", "US", "USD",
                   "twelvedata", "SPY", 0.0009, 1993),
    UnivInstrument("QQQ", "Invesco QQQ (Nasdaq-100)", "EQUITY", "US Growth / Tech", "US", "USD",
                   "twelvedata", "QQQ", 0.0020, 1999),
    UnivInstrument("IWM", "iShares Russell 2000 ETF", "EQUITY", "US Small Cap", "US", "USD",
                   "twelvedata", "IWM", 0.0019, 2000),
    UnivInstrument("EFA", "iShares MSCI EAFE ETF", "EQUITY", "Developed ex-US", "INTL", "USD",
                   "twelvedata", "EFA", 0.0033, 2001),
    UnivInstrument("EEM", "iShares MSCI Emerging Markets ETF", "EQUITY", "Emerging Markets", "EM", "USD",
                   "twelvedata", "EEM", 0.0068, 2003),
    UnivInstrument("VTV", "Vanguard Value ETF", "EQUITY", "US Value", "US", "USD",
                   "twelvedata", "VTV", 0.0004, 2004),
    UnivInstrument("MTUM", "iShares MSCI USA Momentum Factor ETF", "EQUITY", "US Momentum", "US", "USD",
                   "twelvedata", "MTUM", 0.0015, 2013),
    UnivInstrument("USMV", "iShares MSCI USA Min Vol Factor ETF", "EQUITY", "US Low Volatility", "US", "USD",
                   "twelvedata", "USMV", 0.0015, 2011),
    # --- real assets ------------------------------------------------
    UnivInstrument("VNQ", "Vanguard Real Estate ETF", "REIT", "US REITs", "US", "USD",
                   "twelvedata", "VNQ", 0.0012, 2004),
    UnivInstrument("GLD", "SPDR Gold Shares", "COMMODITY", "Gold", "GLOBAL", "USD",
                   "twelvedata", "GLD", 0.0040, 2004),
    UnivInstrument("SLV", "iShares Silver Trust", "COMMODITY", "Silver", "GLOBAL", "USD",
                   "twelvedata", "SLV", 0.0050, 2006),
    UnivInstrument("DBC", "Invesco DB Commodity Index ETF", "COMMODITY", "Broad Commodities", "GLOBAL", "USD",
                   "twelvedata", "DBC", 0.0087, 2006),
    # --- fixed income ------------------------------------------------
    UnivInstrument("TLT", "iShares 20+ Year Treasury Bond ETF", "BOND", "Long Treasury", "US", "USD",
                   "twelvedata", "TLT", 0.0015, 2002),
    UnivInstrument("IEF", "iShares 7-10 Year Treasury Bond ETF", "BOND", "Intermediate Treasury", "US", "USD",
                   "twelvedata", "IEF", 0.0015, 2002),
    UnivInstrument("AGG", "iShares Core US Aggregate Bond ETF", "BOND", "US Aggregate Bond", "US", "USD",
                   "twelvedata", "AGG", 0.0003, 2003),
    UnivInstrument("TIP", "iShares TIPS Bond ETF", "BOND", "US Inflation-Linked", "US", "USD",
                   "twelvedata", "TIP", 0.0019, 2003),
    UnivInstrument("HYG", "iShares iBoxx High Yield Corporate Bond ETF", "BOND", "US High Yield", "US", "USD",
                   "twelvedata", "HYG", 0.0049, 2007),
    UnivInstrument("LQD", "iShares iBoxx Investment Grade Corp Bond ETF", "BOND", "US Investment Grade", "US", "USD",
                   "twelvedata", "LQD", 0.0014, 2002),
    UnivInstrument("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF", "CASH", "US T-Bills / Cash", "US", "USD",
                   "twelvedata", "BIL", 0.0014, 2007),
]

FX_PAIRS = ["USD/INR"]

_BY_SYMBOL = {u.symbol: u for u in CORE}


def all_instruments() -> list[UnivInstrument]:
    return list(CORE)


def get(symbol: str) -> UnivInstrument | None:
    return _BY_SYMBOL.get(symbol.strip().upper())


def asset_classes() -> list[str]:
    seen: dict[str, None] = {}
    for u in CORE:
        seen.setdefault(u.asset_class, None)
    return list(seen)
