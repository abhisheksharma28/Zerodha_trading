"""Named instrument universes for the basket product layer.

A basket's ``spec`` still stores a concrete member list (that is what the
engine ranks), but the *catalog* builds those lists from these named
universes instead of copy-pasting tickers. Phase 2 will turn membership
dynamic (liquidity / eligibility screened); this module is the seam.

All symbols are NSE cash equities or NSE-listed ETFs. Lists are curated
for liquidity + a long price history so the walk-forward backtest has data.
"""

from __future__ import annotations


def _dedupe(seq: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for s in seq:
        seen.setdefault(s.strip().upper(), None)
    return list(seen)


# --- broad equity pools ---------------------------------------------------

LARGE_CAP_CORE = _dedupe([
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "LT", "ITC", "AXISBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NTPC", "POWERGRID", "TATAMOTORS",
    "M&M", "ADANIPORTS", "ASIANPAINT", "HCLTECH", "TATASTEEL", "JSWSTEEL",
    "COALINDIA", "GRASIM", "NESTLEIND", "WIPRO",
])

# large + liquid mid — the alpha / momentum hunting ground
LARGE_MID_ALPHA = _dedupe(LARGE_CAP_CORE + [
    "TRENT", "BEL", "HAL", "BAJAJ-AUTO", "DIVISLAB", "CIPLA", "DRREDDY",
    "SIEMENS", "ABB", "HAVELLS", "PERSISTENT", "COFORGE", "DIXON", "LTIM",
    "TVSMOTOR", "POLYCAB", "SUPREMEIND", "CUMMINSIND",
])

QUALITY = _dedupe([
    "HINDUNILVR", "NESTLEIND", "TCS", "INFY", "HCLTECH", "ASIANPAINT",
    "PIDILITIND", "BAJAJ-AUTO", "HEROMOTOCO", "MARUTI", "MARICO", "DABUR",
    "COLPAL", "BRITANNIA", "TITAN", "HAVELLS", "KOTAKBANK", "BAJFINANCE",
    "DIVISLAB", "CIPLA",
])

LOW_VOL = _dedupe([
    "HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA", "DABUR", "MARICO",
    "POWERGRID", "NTPC", "SUNPHARMA", "CIPLA", "DRREDDY", "ASIANPAINT",
    "PIDILITIND", "COLPAL", "BAJAJ-AUTO", "HDFCBANK", "TCS", "INFY",
])

MIDCAP_LIQUID = _dedupe([
    "PERSISTENT", "COFORGE", "DIXON", "POLYCAB", "CUMMINSIND", "ASHOKLEY",
    "BALKRISIND", "MPHASIS", "AUROPHARMA", "LUPIN", "ALKEM", "TORNTPHARM",
    "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "APLAPOLLO", "SUPREMEIND", "PIIND",
    "BHARATFORG", "SRF", "TATACHEM", "GODREJPROP", "MUTHOOTFIN", "ABCAPITAL",
    "FEDERALBNK",
])

HIGH_YIELD = _dedupe([
    "ITC", "COALINDIA", "POWERGRID", "NTPC", "ONGC", "IOC", "BPCL", "HINDPETRO",
    "GAIL", "OIL", "HINDZINC", "VEDL",
])

CONSUMPTION = _dedupe([
    "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "GODREJCP",
    "TATACONSUM", "COLPAL", "VBL", "TITAN", "MARUTI", "M&M", "TATAMOTORS",
    "TRENT", "JUBLFOOD", "PAGEIND", "UNITDSPR", "HAVELLS", "PIDILITIND",
])

# REITs / InvITs — thin coverage; the engine drops names with no price history
# and the sleeve degrades to cash, so this is safe to ship ahead of full data.
REITS_INVITS = _dedupe(["EMBASSY", "MINDSPACE", "BIRET", "NXST", "INDIGRID", "IRBINVIT"])


# --- sector universes (>= 5 liquid names each; no single-stock proxies) ---

SECTORS: dict[str, list[str]] = {
    "Financials": _dedupe([
        "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK",
        "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN", "SBILIFE", "HDFCLIFE",
    ]),
    "IT": _dedupe([
        "INFY", "TCS", "HCLTECH", "WIPRO", "TECHM", "LTIM", "PERSISTENT", "COFORGE",
    ]),
    "Pharma": _dedupe([
        "SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "AUROPHARMA",
        "TORNTPHARM", "ALKEM", "ZYDUSLIFE",
    ]),
    "Auto": _dedupe([
        "MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT",
        "TVSMOTOR", "ASHOKLEY", "BHARATFORG",
    ]),
    "FMCG": _dedupe([
        "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO",
        "GODREJCP", "TATACONSUM", "COLPAL", "VBL",
    ]),
    "Metals": _dedupe([
        "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL", "JINDALSTEL", "NMDC",
        "HINDZINC", "SAIL",
    ]),
    "Energy": _dedupe([
        "RELIANCE", "ONGC", "NTPC", "POWERGRID", "COALINDIA", "BPCL", "IOC",
        "GAIL", "TATAPOWER",
    ]),
    "Infra & Capital Goods": _dedupe([
        "LT", "SIEMENS", "ABB", "BEL", "HAL", "CUMMINSIND", "POLYCAB", "HAVELLS",
        "THERMAX",
    ]),
    "Realty": _dedupe([
        "DLF", "GODREJPROP", "OBEROIRLTY", "PRESTIGE", "PHOENIXLTD", "BRIGADE",
    ]),
}

SECTOR_ALL = _dedupe([s for names in SECTORS.values() for s in names])


# --- registry -----------------------------------------------------------

_REGISTRY: dict[str, list[str]] = {
    "LARGE_CAP_CORE": LARGE_CAP_CORE,
    "LARGE_MID_ALPHA": LARGE_MID_ALPHA,
    "QUALITY": QUALITY,
    "LOW_VOL": LOW_VOL,
    "MIDCAP_LIQUID": MIDCAP_LIQUID,
    "HIGH_YIELD": HIGH_YIELD,
    "CONSUMPTION": CONSUMPTION,
    "REITS_INVITS": REITS_INVITS,
    "SECTOR_ALL": SECTOR_ALL,
    **{f"SECTOR::{k}": v for k, v in SECTORS.items()},
}


def members(name: str) -> list[str]:
    """Resolve a named universe to its current member list (a copy)."""
    try:
        return list(_REGISTRY[name])
    except KeyError as exc:
        raise KeyError(f"unknown universe {name!r}") from exc


def names() -> list[str]:
    return list(_REGISTRY)
