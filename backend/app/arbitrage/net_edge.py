"""Net expected edge — the only number the Arbitrage Lab trades on.

NET_EXPECTED_EDGE = GROSS_EDGE
  - brokerage / exchange / taxes (statutory, every leg, entry AND exit)
  - bid/ask spread crossed (every leg, round trip)
  - execution slippage
  - market impact (sqrt model vs ADV)
  - financing cost (cash legs held to convergence)
  - stock-borrow cost (short legs that need borrow)
  - an execution-risk buffer (leg imbalance / adverse selection haircut)

An opportunity is only executable when NET_EXPECTED_EDGE exceeds the
strategy's configured minimum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.arbitrage.types import TradeStructure
from app.backtesting.costs import CostModel

_DEFAULT_SPREAD_BPS = 4.0        # round-trip spread crossed, per leg, when unknown
_DEFAULT_IMPACT_COEF = 0.8       # impact_bps ~ coef * daily_sigma_bps * sqrt(order/ADV)
_DEFAULT_SIGMA_BPS = 150.0       # ~1.5%/day instrument volatility
_DEFAULT_ADV_NOTIONAL = 5.0e7    # ₹5 cr/day fallback ADV
_SEG_MAP = {"equity": "equity_intraday", "equity_delivery": "equity_delivery",
            "futures": "futures", "options": "options"}


@dataclass
class NetEdgeBreakdown:
    gross_edge: float
    brokerage: float = 0.0
    statutory: float = 0.0      # stt + exch + gst + sebi + stamp
    slippage: float = 0.0
    bid_ask_spread: float = 0.0
    market_impact: float = 0.0
    financing_cost: float = 0.0
    borrow_cost: float = 0.0
    execution_risk_buffer: float = 0.0
    per_leg: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_costs(self) -> float:
        return (self.brokerage + self.statutory + self.slippage + self.bid_ask_spread
                + self.market_impact + self.financing_cost + self.borrow_cost
                + self.execution_risk_buffer)

    @property
    def net_edge(self) -> float:
        return self.gross_edge - self.total_costs

    def as_dict(self) -> dict[str, Any]:
        return {
            "gross_edge": round(self.gross_edge, 4),
            "brokerage": round(self.brokerage, 4),
            "statutory": round(self.statutory, 4),
            "slippage": round(self.slippage, 4),
            "bid_ask_spread": round(self.bid_ask_spread, 4),
            "market_impact": round(self.market_impact, 4),
            "financing_cost": round(self.financing_cost, 4),
            "borrow_cost": round(self.borrow_cost, 4),
            "execution_risk_buffer": round(self.execution_risk_buffer, 4),
            "total_costs": round(self.total_costs, 4),
            "net_edge": round(self.net_edge, 4),
            "per_leg": self.per_leg,
        }


def net_expected_edge(
    structure: TradeStructure,
    *,
    gross_edge: float,
    cost_model: CostModel,
    spreads_bps: dict[str, float] | None = None,
    adv_notional: dict[str, float] | None = None,
    financing_rate_annual: float = 0.09,
    borrow_rate_annual: float = 0.04,
    holding_days: float | None = None,
    impact_coef: float = _DEFAULT_IMPACT_COEF,
    daily_sigma_bps: float = _DEFAULT_SIGMA_BPS,
    exec_risk_buffer_bps: float = 3.0,
) -> NetEdgeBreakdown:
    spreads_bps = spreads_bps or {}
    adv_notional = adv_notional or {}
    hold = holding_days if holding_days is not None else structure.expected_holding_days

    b = NetEdgeBreakdown(gross_edge=gross_edge)
    total_notional = 0.0
    for leg in structure.legs:
        seg = _SEG_MAP.get(leg.segment, "equity_intraday")
        notional = abs(leg.price * leg.quantity)
        total_notional += notional

        # statutory: a round trip (entry + exit), each side priced with slippage
        entry_px = cost_model.fill_price_with_slippage(leg.side, leg.price, segment=seg)
        exit_side = "SELL" if leg.side.upper() == "BUY" else "BUY"
        exit_px = cost_model.fill_price_with_slippage(exit_side, leg.price, segment=seg)
        c_in = cost_model.charge(leg.side, entry_px, leg.quantity, seg, reference_price=leg.price)
        c_out = cost_model.charge(exit_side, exit_px, leg.quantity, seg, reference_price=leg.price)
        leg_brokerage = c_in.brokerage + c_out.brokerage
        leg_statutory = (c_in.statutory_total - c_in.brokerage) + (c_out.statutory_total - c_out.brokerage)
        leg_slippage = c_in.slippage + c_out.slippage

        sp_bps = spreads_bps.get(leg.instrument, _DEFAULT_SPREAD_BPS)
        leg_spread = sp_bps / 1e4 * notional  # cross the spread once per round trip

        adv = adv_notional.get(leg.instrument, _DEFAULT_ADV_NOTIONAL)
        impact_bps = impact_coef * daily_sigma_bps * math.sqrt(max(notional, 1.0) / max(adv, 1.0))
        leg_impact = impact_bps / 1e4 * notional

        leg_financing = 0.0
        if leg.is_financing_leg:
            leg_financing = notional * financing_rate_annual * hold / 365.0
        leg_borrow = 0.0
        if leg.borrow_required:
            leg_borrow = notional * borrow_rate_annual * hold / 365.0

        b.brokerage += leg_brokerage
        b.statutory += leg_statutory
        b.slippage += leg_slippage
        b.bid_ask_spread += leg_spread
        b.market_impact += leg_impact
        b.financing_cost += leg_financing
        b.borrow_cost += leg_borrow
        b.per_leg.append({
            "instrument": leg.instrument, "side": leg.side, "quantity": leg.quantity,
            "notional": round(notional, 2), "brokerage": round(leg_brokerage, 2),
            "statutory": round(leg_statutory, 2), "slippage": round(leg_slippage, 2),
            "bid_ask_spread": round(leg_spread, 2), "market_impact": round(leg_impact, 2),
            "financing": round(leg_financing, 2), "borrow": round(leg_borrow, 2),
        })

    b.execution_risk_buffer = exec_risk_buffer_bps / 1e4 * total_notional
    return b
