"""Named instrument universes a paper strategy can be deployed against
without the user hand-picking every symbol.

A universe key is resolved to a concrete list of ``NSE:<tradingsymbol>``
refs at deploy time. Curated index lists come from :mod:`nse_universe`;
the wider ones ("all F&O stocks", "every NSE stock") are read live from
the synced instrument master so they track the real listing.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.market_data.nse_universe import NIFTY_50, NIFTY_100, NIFTY_200
from app.models.instrument import Instrument

# key -> (label, short blurb). "custom" is the sentinel for hand-picking.
# "fno" is the widest practical universe: the ~210 stocks with listed
# single-stock futures are the liquid, tradable market. The full NSE
# equity list is ~10k rows dominated by illiquid small-caps, bonds and
# ETFs that the paper engine can't fill meaningfully, so it isn't offered.
EQUITY_UNIVERSES: list[dict[str, str]] = [
    {"key": "custom", "label": "Custom — pick instruments", "note": "Choose symbols yourself."},
    {"key": "nifty50", "label": "NIFTY 50", "note": "50 large-cap leaders."},
    {"key": "nifty100", "label": "NIFTY 100", "note": "Large + upper mid-cap."},
    {"key": "nifty200", "label": "NIFTY 200", "note": "Large + mid-cap, ~200 names."},
    {"key": "fno", "label": "Whole market (all F&O stocks)",
     "note": "Every NSE stock with listed futures (~210) — the liquid, tradable market. Daily timeframe recommended."},
]
_VALID_KEYS = {u["key"] for u in EQUITY_UNIVERSES}


def _nse_equity_symbols(db: Session) -> set[str]:
    return set(
        db.execute(
            select(Instrument.tradingsymbol).where(
                Instrument.exchange == "NSE",
                Instrument.instrument_type == "EQ",
                Instrument.active.is_(True),
            )
        ).scalars().all()
    )


def resolve_equity_universe(db: Session, key: str | None) -> list[str]:
    """Expand a universe key to ``["NSE:RELIANCE", ...]``. ``custom`` / empty
    returns ``[]`` (the caller then uses the hand-picked list)."""
    k = (key or "").strip().lower()
    if k in ("", "custom"):
        return []
    if k not in _VALID_KEYS:
        raise ValidationError(f"Unknown universe '{key}'.")

    if k == "nifty50":
        return [f"NSE:{s}" for s, _n, _sec in NIFTY_50]
    if k == "nifty100":
        return [f"NSE:{s}" for s in sorted(NIFTY_100)]
    if k == "nifty200":
        return [f"NSE:{s}" for s in sorted(NIFTY_200)]

    # k == "fno": NFO stock-futures' `name` is the underlying NSE
    # tradingsymbol; keep only those that are still a listed NSE equity
    # (drops index futures and any delisted underlying).
    fut_underlyings = db.execute(
        select(Instrument.name)
        .distinct()
        .where(
            Instrument.exchange == "NFO",
            Instrument.instrument_type == "FUT",
            Instrument.active.is_(True),
            Instrument.name.is_not(None),
        )
    ).scalars().all()
    eq = _nse_equity_symbols(db)
    return sorted(f"NSE:{n}" for n in fut_underlyings if n in eq)
