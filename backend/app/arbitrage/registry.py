"""Registry of Arbitrage Lab strategies."""

from __future__ import annotations

from app.arbitrage.base import ArbitrageStrategy
from app.arbitrage.strategies import (
    CalendarSpreadStrategy,
    CashAndCarryStrategy,
    CointegrationSpreadStrategy,
    IndexFuturesBasisStrategy,
    PairsArbitrageStrategy,
    SectorRelativeValueStrategy,
)

ARB_STRATEGIES: list[type[ArbitrageStrategy]] = [
    PairsArbitrageStrategy,
    CointegrationSpreadStrategy,
    SectorRelativeValueStrategy,
    IndexFuturesBasisStrategy,
    CashAndCarryStrategy,
    CalendarSpreadStrategy,
]

_BY_SLUG = {s.SPEC.slug: s for s in ARB_STRATEGIES}

# strategies whose canonical data path needs verified F&O historical bars
FUTURES_SLUGS = {"index-futures-basis", "cash-and-carry", "calendar-spread"}


def get_arb_strategy(slug: str) -> type[ArbitrageStrategy]:
    try:
        return _BY_SLUG[slug]
    except KeyError:
        raise KeyError(f"Unknown arbitrage strategy '{slug}'") from None
