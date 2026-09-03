"""Approximate margin required to place / hold a paper order.

Deliberately simple and clearly labelled as an estimate - real SPAN +
exposure needs the exchange margin files. Configurable multipliers.
"""

from __future__ import annotations

from dataclasses import dataclass

# fraction of contract notional blocked as margin
_FUT_MARGIN_PCT = 0.16          # index futures ~ 10-14%, stock futures ~ 20%
_OPT_SELL_MARGIN_PCT = 0.16     # writing an option ~ futures-like
_MIS_EQUITY_MARGIN_PCT = 0.20   # ~ 5x intraday leverage
_CNC_MARGIN_PCT = 1.00          # delivery = full value


@dataclass
class MarginQuote:
    required: float
    basis: str  # human-readable how it was computed


def estimate(*, asset_class: str, product: str, side: str, price: float, quantity: int) -> MarginQuote:
    notional = abs(price) * quantity
    if asset_class == "OPT":
        if side == "BUY":
            return MarginQuote(notional, "option premium (full)")
        return MarginQuote(notional * _OPT_SELL_MARGIN_PCT, f"~{_OPT_SELL_MARGIN_PCT:.0%} of notional (writing, estimated)")
    if asset_class == "FUT":
        return MarginQuote(notional * _FUT_MARGIN_PCT, f"~{_FUT_MARGIN_PCT:.0%} of notional (estimated SPAN+exposure)")
    # equity
    if product == "MIS":
        return MarginQuote(notional * _MIS_EQUITY_MARGIN_PCT, f"~{_MIS_EQUITY_MARGIN_PCT:.0%} of value (MIS ~5x)")
    return MarginQuote(notional * _CNC_MARGIN_PCT, "full value (CNC delivery)")
