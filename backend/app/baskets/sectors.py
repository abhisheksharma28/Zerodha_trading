"""Sector attribution for basket members — used by the sector-concentration
cap in the rebalance engine.

Equity names resolve through the platform's best-effort NSE sector map.
ETF / gold / silver / bond / cash instruments are *asset-class* sleeves,
not sectors, so they get their own buckets and are excluded from the
equity sector cap.
"""

from __future__ import annotations

from app.market_data.nse_universe import _KNOWN_SECTOR

# non-equity instruments the basket universes use — never counted as an
# equity "sector"
_NON_EQUITY: dict[str, str] = {
    "NIFTYBEES": "Index ETF", "JUNIORBEES": "Index ETF", "MID150BEES": "Index ETF",
    "MOM100": "Index ETF", "SETFNIF50": "Index ETF", "BANKBEES": "Index ETF",
    "GOLDBEES": "Gold", "GOLD1": "Gold",
    "SILVERBEES": "Silver", "SILVER1": "Silver",
    "LIQUIDBEES": "Cash", "LIQUIDCASE": "Cash",
    "GSEC10IETF": "Bond", "EBBETF0433": "Bond", "LTGILTBEES": "Bond", "GILT5YBEES": "Bond",
    "COMMOIETF": "Commodities", "DIVOPPBEES": "Dividend ETF",
}

_EXCLUDED_BUCKETS = frozenset(
    {"Index ETF", "Gold", "Silver", "Cash", "Bond", "Commodities", "Dividend ETF"}
)


def sector_of(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in _NON_EQUITY:
        return _NON_EQUITY[s]
    return _KNOWN_SECTOR.get(s, "Other")


def is_equity_sector(bucket: str) -> bool:
    """True when a bucket should be subject to the equity sector cap."""
    return bucket not in _EXCLUDED_BUCKETS
