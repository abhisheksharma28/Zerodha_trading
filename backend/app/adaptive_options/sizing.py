"""Phase 11a — Position sizing.

Defined-risk structures are sized so one structure's worst case is at most
``max_loss_per_trade_pct`` of ``account_capital``. Naked structures are
sized by margin (``max_margin_usage_pct``) and additionally capped by a
notional risk proxy. Everything is capped by ``max_lots_per_trade`` and
halved from ``expiry_reduce_dte`` DTE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.strategy_library import BuiltPosition


@dataclass
class SizedPosition:
    lots: int
    per_lot_max_loss: float
    capital_at_risk: float
    margin: float
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "lots": self.lots,
            "per_lot_max_loss": round(self.per_lot_max_loss, 2),
            "capital_at_risk": round(self.capital_at_risk, 2),
            "margin": round(self.margin, 0),
            "notes": self.notes,
        }


def size(pos: BuiltPosition, cfg: AdaptiveConfig, *, dte: float) -> SizedPosition:
    """``pos`` must be built with ``lots=1`` — its max_loss / margin are per
    lot-set."""
    notes: list[str] = []
    risk_budget = cfg.account_capital * cfg.max_loss_per_trade_pct / 100.0

    if pos.undefined_risk:
        margin_budget = cfg.account_capital * cfg.max_margin_usage_pct / 100.0
        by_margin = int(margin_budget // max(pos.margin_estimate, 1.0))
        # notional risk proxy: assume a 3-sigma-ish adverse ~ 4% of short notional per lot
        short_notional = sum(lg.strike * lg.lots * pos.lot_size
                             for lg in pos.legs if lg.side == "SELL")
        proxy_loss = short_notional * 0.04
        by_proxy = int(risk_budget // max(proxy_loss, 1.0)) if proxy_loss > 0 else by_margin
        lots = max(0, min(by_margin, by_proxy))
        notes.append("Naked structure: sized by margin + a notional risk proxy, not a fixed max loss.")
        per_lot = proxy_loss
    else:
        per_lot = max(pos.max_loss, 1.0)
        lots = int(risk_budget // per_lot)
        if lots == 0:
            notes.append(f"Even one lot risks ₹{per_lot:,.0f} > budget ₹{risk_budget:,.0f} — "
                         "narrow the wings or lower max_loss_per_trade_pct.")

    if lots > cfg.max_lots_per_trade:
        notes.append(f"Capped at max_lots_per_trade ({cfg.max_lots_per_trade}).")
        lots = cfg.max_lots_per_trade

    if dte <= cfg.expiry_reduce_dte and lots > 0:
        lots = max(1, lots // 2)
        notes.append(f"{dte:.0f} DTE ≤ {cfg.expiry_reduce_dte}: size halved for gamma risk.")

    return SizedPosition(
        lots=lots,
        per_lot_max_loss=per_lot,
        capital_at_risk=per_lot * lots,
        margin=pos.margin_estimate * lots,
        notes=notes,
    )
