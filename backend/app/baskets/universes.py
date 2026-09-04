"""Named instrument universes for the basket product layer.

A basket's ``spec`` still stores a concrete member list (that is what the
engine ranks), but the *catalog* builds those lists from these named
universes instead of copy-pasting tickers. Phase 2 will turn membership
dynamic (liquidity / eligibility screened); this module is the seam.

All symbols are NSE cash equities or NSE-listed ETFs. Lists are curated
for liquidity + a long price history so the walk-forward backtest has data.
"""

from __future__ import annotations

from typing import Any


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


# --- metadata ---------------------------------------------------------
# What each pool is, the selection intent, and how it is (re)curated. The
# member lists are hand-maintained today; the eligibility screen
# (app.baskets.eligibility) is what turns "listed here" into "tradeable
# right now".

_META: dict[str, dict[str, str]] = {
    "LARGE_CAP_CORE": {
        "label": "Large-cap core",
        "intent": "The ~30 most liquid NSE large-caps — the low-turnover spine of the core products.",
        "curation": "Reviewed against NIFTY 50/NEXT 50 membership; changes are rare and deliberate.",
    },
    "LARGE_MID_ALPHA": {
        "label": "Large + liquid mid",
        "intent": "Large-cap core plus high-liquidity mid-caps — the hunting ground for the momentum / multi-factor alpha products.",
        "curation": "Adds names with a multi-year history and consistent delivery volume; screened for eligibility each rebalance.",
    },
    "QUALITY": {
        "label": "Quality compounders",
        "intent": "High return-on-capital, low-leverage franchises with durable demand.",
        "curation": "Fundamental quality is applied on the live signal only (not through history) per the fundamentals-latest rule.",
    },
    "LOW_VOL": {
        "label": "Low volatility",
        "intent": "Historically calm large-caps — staples, pharma, utilities, top private banks.",
        "curation": "Trailing realised-volatility rank; refreshed with the member review.",
    },
    "MIDCAP_LIQUID": {
        "label": "Liquid mid-caps",
        "intent": "Mid-caps with enough traded value to size in and out without undue impact.",
        "curation": "NIFTY Midcap 150 constituents filtered for turnover and history.",
    },
    "HIGH_YIELD": {
        "label": "High dividend yield",
        "intent": "Consistent, well-covered dividend payers for the income products.",
        "curation": "Trailing yield plus a payout-consistency check; PSU-heavy by nature.",
    },
    "CONSUMPTION": {
        "label": "India consumption",
        "intent": "Staples, discretionary, autos, retail and QSR — the domestic consumption basket.",
        "curation": "Thematic; mapped to the consumption value chain.",
    },
    "REITS_INVITS": {
        "label": "REITs & InvITs",
        "intent": "Listed real-estate and infrastructure trusts for the multi-asset income sleeve.",
        "curation": "All liquid NSE-listed trusts; short history is expected and handled by the eligibility screen.",
    },
    "SECTOR_ALL": {
        "label": "All sector leaders",
        "intent": "The union of the nine sector books — the pool the sector-rotation product ranks.",
        "curation": "Derived from the SECTOR:: books; not curated directly.",
    },
}

for _k in SECTORS:
    _META.setdefault(f"SECTOR::{_k}", {
        "label": f"{_k} leaders",
        "intent": f"The most liquid, representative names in the {_k} sector.",
        "curation": "Sector book; reviewed with the member list.",
    })


def describe(name: str) -> dict[str, Any]:
    """Metadata + current member count for a named universe."""
    if name not in _REGISTRY:
        raise KeyError(f"unknown universe {name!r}")
    meta = _META.get(name, {"label": name, "intent": "", "curation": ""})
    return {"name": name, **meta, "n_members": len(_REGISTRY[name]),
            "members": list(_REGISTRY[name])}


def catalog() -> list[dict[str, Any]]:
    """All named universes with metadata (no member lists)."""
    return [
        {k: v for k, v in describe(n).items() if k != "members"}
        for n in _REGISTRY
    ]
