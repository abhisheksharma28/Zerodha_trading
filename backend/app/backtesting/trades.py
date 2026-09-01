"""Reconstruct round-trip trades from a chronological fill list.

FIFO matching per instrument: each fill on the opposite side of the current
position closes the oldest open lot(s), producing a closed Trade with entry
and exit prices, quantity, holding period and P&L. Any lot still open at the
end is reported as an open trade marked-to-market at ``mark_prices``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from app.backtesting.engine import SimulatedFill


@dataclass
class ClosedTrade:
    instrument: str
    direction: str  # "long" | "short"
    quantity: int
    entry_time: Any
    exit_time: Any
    entry_price: float
    exit_price: float
    gross_pnl: float
    costs: float
    net_pnl: float
    bars_held: int
    return_pct: float
    is_open: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        for k in ("entry_time", "exit_time"):
            d[k] = str(d[k]) if d[k] is not None else None
        for k in ("entry_price", "exit_price", "gross_pnl", "costs", "net_pnl", "return_pct"):
            d[k] = round(d[k], 4)
        return d


@dataclass
class _Lot:
    qty: int
    price: float
    time: Any
    index: int
    cost: float  # entry-side cost allocated to this lot


def reconstruct_trades(
    fills: list[SimulatedFill],
    *,
    fill_costs: list[float] | None = None,
    mark_prices: dict[str, float] | None = None,
) -> list[ClosedTrade]:
    fill_costs = fill_costs or [0.0] * len(fills)
    mark_prices = mark_prices or {}
    # stable per-instrument bar index for holding-period estimates
    order_by_instrument: dict[str, deque[_Lot]] = {}
    side_by_instrument: dict[str, str] = {}
    trades: list[ClosedTrade] = []

    for idx, (fill, fcost) in enumerate(zip(fills, fill_costs, strict=False)):
        sym = fill.instrument
        lots = order_by_instrument.setdefault(sym, deque())
        qty = int(fill.quantity)
        is_buy = fill.transaction_type.upper() == "BUY"
        cur_side = side_by_instrument.get(sym)

        opening = cur_side is None or (cur_side == "long") == is_buy
        if opening:
            side_by_instrument[sym] = "long" if is_buy else "short"
            lots.append(_Lot(qty=qty, price=float(fill.price), time=fill.bar_timestamp,
                             index=idx, cost=fcost))
            continue

        # closing (possibly flipping)
        remaining = qty
        exit_cost_per_unit = fcost / qty if qty else 0.0
        while remaining > 0 and lots:
            lot = lots[0]
            matched = min(remaining, lot.qty)
            direction = "long" if cur_side == "long" else "short"
            entry_px = lot.price
            exit_px = float(fill.price)
            if direction == "long":
                gross = (exit_px - entry_px) * matched
            else:
                gross = (entry_px - exit_px) * matched
            entry_cost = lot.cost * (matched / lot.qty) if lot.qty else 0.0
            costs = entry_cost + exit_cost_per_unit * matched
            bars_held = max(0, idx - lot.index)
            notional = entry_px * matched
            trades.append(
                ClosedTrade(
                    instrument=sym, direction=direction, quantity=matched,
                    entry_time=lot.time, exit_time=fill.bar_timestamp,
                    entry_price=entry_px, exit_price=exit_px,
                    gross_pnl=gross, costs=costs, net_pnl=gross - costs,
                    bars_held=bars_held,
                    return_pct=(gross - costs) / notional * 100.0 if notional else 0.0,
                )
            )
            lot.qty -= matched
            lot.cost -= entry_cost
            remaining -= matched
            if lot.qty == 0:
                lots.popleft()

        if not lots:
            side_by_instrument.pop(sym, None)
        if remaining > 0:  # flip: the leftover opens a new lot on the other side
            side_by_instrument[sym] = "long" if is_buy else "short"
            lots.append(_Lot(qty=remaining, price=float(fill.price),
                             time=fill.bar_timestamp, index=idx, cost=0.0))

    # anything still open -> mark to market
    for sym, lots in order_by_instrument.items():
        for lot in lots:
            if lot.qty == 0:
                continue
            direction = side_by_instrument.get(sym, "long")
            mark = mark_prices.get(sym, lot.price)
            gross = ((mark - lot.price) if direction == "long" else (lot.price - mark)) * lot.qty
            notional = lot.price * lot.qty
            trades.append(
                ClosedTrade(
                    instrument=sym, direction=direction, quantity=lot.qty,
                    entry_time=lot.time, exit_time=None,
                    entry_price=lot.price, exit_price=mark,
                    gross_pnl=gross, costs=lot.cost, net_pnl=gross - lot.cost,
                    bars_held=0,
                    return_pct=(gross - lot.cost) / notional * 100.0 if notional else 0.0,
                    is_open=True,
                )
            )
    return trades
