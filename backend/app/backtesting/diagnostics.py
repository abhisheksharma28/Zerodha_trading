"""Backtest run diagnostics — the "why did this produce N trades?" record.

The engine populates a ``RunDiagnostics`` while it runs: how much data it
saw, how many order intents the strategy emitted, how many became fills, and
how many were rejected and why. Strategies may additionally call
``context.note_signal(...)`` to report their own signal counts (entirely
optional — a strategy that never calls it just contributes nothing here).

``explain_no_trades`` turns that record, plus the data-quality report, into
an ordered list of plain-language candidate reasons so a zero-trade backtest
is never a dead end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunDiagnostics:
    instruments: list[str] = field(default_factory=list)
    bars_by_instrument: dict[str, int] = field(default_factory=dict)
    total_bars: int = 0
    first_bar_ts: str | None = None
    last_bar_ts: str | None = None
    orders_submitted: int = 0
    fills: int = 0
    rejected_orders: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    signals: dict[str, int] = field(default_factory=dict)
    # risk / solvency
    ruined: bool = False
    ruin_ts: str | None = None
    peak_gross_exposure_pct: float = 0.0  # max Σ|qty·price| as % of initial capital
    exposure_capped_orders: int = 0

    def reject(self, reason: str) -> None:
        self.rejected_orders += 1
        self.rejection_reasons[reason] = self.rejection_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "instruments": self.instruments,
            "bars_by_instrument": self.bars_by_instrument,
            "total_bars": self.total_bars,
            "first_bar_ts": self.first_bar_ts,
            "last_bar_ts": self.last_bar_ts,
            "orders_submitted": self.orders_submitted,
            "fills": self.fills,
            "rejected_orders": self.rejected_orders,
            "rejection_reasons": self.rejection_reasons,
            "signals": self.signals,
            "ruined": self.ruined,
            "ruin_ts": self.ruin_ts,
            "peak_gross_exposure_pct": round(self.peak_gross_exposure_pct, 2),
            "exposure_capped_orders": self.exposure_capped_orders,
        }


def explain_no_trades(
    diag: RunDiagnostics,
    data_quality: dict[str, Any] | None,
    *,
    timeframe: str,
    min_bars_required: int | None = None,
) -> list[str]:
    """Ordered, most-likely-first candidate reasons a run produced 0 trades."""
    reasons: list[str] = []
    dq = data_quality or {}

    empty = [s["symbol"] for s in dq.get("per_symbol", []) if s.get("bars", 0) == 0]
    if empty or diag.total_bars == 0:
        which = ", ".join(empty) if empty else "the selected universe"
        reasons.append(
            f"No candle data was available for {which} in this date range / timeframe "
            f"({timeframe}). Check the instrument symbols and that history exists for the period."
        )
        return reasons

    if min_bars_required and diag.bars_by_instrument:
        thin = [s for s, n in diag.bars_by_instrument.items() if n < min_bars_required]
        if thin:
            reasons.append(
                f"Only {min(diag.bars_by_instrument.values())} bars for some instruments "
                f"({', '.join(thin)}); this strategy needs at least {min_bars_required} "
                f"{timeframe} bars of warm-up before it can signal. Widen the date range."
            )

    if diag.orders_submitted == 0:
        if diag.signals and sum(diag.signals.values()) > 0:
            reasons.append(
                "The strategy generated signals but never sized a position — check "
                "position-sizing parameters (capital, risk %, max position size) and any "
                "eligibility filters."
            )
        else:
            reasons.append(
                "The strategy's entry conditions were never satisfied over this data. "
                "Try a different timeframe, a longer date range, a more liquid instrument, "
                "or looser entry parameters."
            )
    elif diag.fills == 0:
        pretty = "; ".join(f"{k} ({v})" for k, v in diag.rejection_reasons.items()) or "unknown"
        reasons.append(
            f"The strategy emitted {diag.orders_submitted} order intent(s) but all were "
            f"rejected before fill: {pretty}."
        )

    for w in dq.get("warnings", []):
        reasons.append(f"Data-quality note: {w}")

    if not reasons:
        reasons.append(
            "No trades were generated and no specific cause was detected. Open the raw "
            "diagnostics to inspect signal and order counts."
        )
    return reasons
