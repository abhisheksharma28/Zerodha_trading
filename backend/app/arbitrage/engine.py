"""Dedicated multi-leg arbitrage backtest engine.

Distinct from the single-instrument :class:`app.backtesting.engine.BacktestEngine`:
every leg is tracked and priced independently, execution is never assumed
simultaneous or perfect, costs land on every leg entry AND exit, financing
and borrow accrue while a structure is open, and stale / skewed data is
rejected up front (see :mod:`app.arbitrage.data_sync`).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from app.arbitrage.base import ArbitrageStrategy, OpenState
from app.arbitrage.data_sync import SyncMode, SyncResult, synchronize
from app.arbitrage.net_edge import net_expected_edge
from app.arbitrage.risk import ArbRiskEngine, ArbRiskLimits
from app.arbitrage.types import Leg
from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.metrics import compute_metrics
from app.strategies.base import Bar


@dataclass
class ArbFillLeg:
    instrument: str
    side: str
    target_qty: int
    filled_qty: int
    entry_price: float
    exit_price: float = 0.0
    entry_cost: float = 0.0
    exit_cost: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument": self.instrument, "side": self.side, "target_qty": self.target_qty,
            "filled_qty": self.filled_qty, "entry_price": round(self.entry_price, 4),
            "exit_price": round(self.exit_price, 4),
            "entry_cost": round(self.entry_cost, 2), "exit_cost": round(self.exit_cost, 2),
        }


@dataclass
class ArbTrade:
    strategy: str
    direction: str
    legs: list[ArbFillLeg]
    entry_ts: Any
    exit_ts: Any
    bars_held: int
    gross_pnl: float
    total_costs: float
    financing_cost: float
    net_pnl: float
    entry_net_edge: float
    realized_edge: float
    edge_capture_rate: float
    leg_imbalance: float
    partial_fill: bool
    converged: bool
    exit_reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy, "direction": self.direction,
            "legs": [leg.as_dict() for leg in self.legs],
            "entry_ts": str(self.entry_ts), "exit_ts": str(self.exit_ts),
            "bars_held": self.bars_held, "gross_pnl": round(self.gross_pnl, 2),
            "total_costs": round(self.total_costs, 2),
            "financing_cost": round(self.financing_cost, 2), "net_pnl": round(self.net_pnl, 2),
            "entry_net_edge": round(self.entry_net_edge, 2),
            "realized_edge": round(self.realized_edge, 2),
            "edge_capture_rate": round(self.edge_capture_rate, 4),
            "leg_imbalance": round(self.leg_imbalance, 4), "partial_fill": self.partial_fill,
            "converged": self.converged, "exit_reason": self.exit_reason,
        }


@dataclass
class ArbBacktestResult:
    equity_curve: list[list[Any]]
    trades: list[ArbTrade]
    opportunities_seen: int
    opportunities_executed: int
    metrics: dict[str, Any]
    data_quality: dict[str, Any]
    config: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class ArbitrageBacktestEngine:
    def __init__(
        self,
        strategy_cls: type[ArbitrageStrategy],
        params: dict[str, Any],
        *,
        capital: float = 1_000_000.0,
        cost_model: CostModel | None = None,
        sync_mode: SyncMode = SyncMode.REJECT_STALE_DATA,
        max_data_age_seconds: float = 300.0,
        full_fill_prob: float = 0.9,
        min_partial_frac: float = 0.6,
        periods_per_year: int = 252,
        seed: int = 7,
        risk_limits: ArbRiskLimits | None = None,
    ) -> None:
        self.strategy_cls = strategy_cls
        self.params = params
        self.capital = capital
        self.cost_model = cost_model or CostModel(CostConfig())
        self.sync_mode = sync_mode
        self.max_data_age = max_data_age_seconds
        self.full_fill_prob = full_fill_prob
        self.min_partial_frac = min_partial_frac
        self.ppy = periods_per_year
        self.rng = random.Random(seed)
        self.risk_limits = risk_limits

    # --- leg execution ---------------------------------------

    def _fill(self, leg: Leg, ref_price: float) -> tuple[int, float, float]:
        """Return (filled_qty, fill_price, cost) for one leg on one side."""
        seg = {"equity": "equity_intraday", "futures": "futures", "options": "options"}.get(
            leg.segment, "equity_intraday")
        px = self.cost_model.fill_price_with_slippage(leg.side, ref_price, segment=seg)
        frac = 1.0 if self.rng.random() < self.full_fill_prob else self.rng.uniform(
            self.min_partial_frac, 1.0)
        qty = max(0, int(round(leg.quantity * frac)))
        cb = self.cost_model.charge(leg.side, px, qty, seg, reference_price=ref_price)
        return qty, px, cb.total

    def _signed(self, side: str, qty: int) -> int:
        return qty if side.upper() == "BUY" else -qty

    # --- run ------------------------------------------------

    def run(self, candles_by_instrument: dict[str, list[Bar]]) -> ArbBacktestResult:
        sync: SyncResult = synchronize(
            candles_by_instrument, mode=self.sync_mode,
            max_age_seconds=self.max_data_age,
        )
        strat = self.strategy_cls(self.params)
        risk = ArbRiskEngine(self.capital, self.risk_limits)

        cash = self.capital
        equity_curve: list[list[Any]] = []
        trades: list[ArbTrade] = []
        opps_seen = opps_exec = 0
        min_edge_bps = float(strat.p["min_net_edge_bps"])
        fin_rate = float(strat.p["financing_rate_annual"])
        borrow_rate = float(strat.p["borrow_rate_annual"])

        open_legs: list[ArbFillLeg] = []
        open_fin_accrued = 0.0
        rejected: dict[str, int] = {}

        for pt in sync.points:
            strat.ingest(pt)
            last = {inst: bar.close for inst, bar in pt.bars.items()}

            if strat.open is None:
                sig = strat.discover_opportunity(pt)
                if sig is None:
                    equity_curve.append([pt.ts, cash])
                    continue
                opps_seen += 1
                structure = strat.build_structure(sig, pt)
                if structure is None:
                    rejected["no_structure"] = rejected.get("no_structure", 0) + 1
                    equity_curve.append([pt.ts, cash])
                    continue
                breakdown = net_expected_edge(
                    structure, gross_edge=float(sig["gross_edge_bps"]) / 1e4
                    * structure.notional_per_unit, cost_model=self.cost_model,
                    spreads_bps={leg.instrument: float(strat.p["spread_bps"])
                                 for leg in structure.legs},
                    financing_rate_annual=fin_rate, borrow_rate_annual=borrow_rate,
                    holding_days=structure.expected_holding_days,
                    exec_risk_buffer_bps=float(strat.p["exec_risk_buffer_bps"]),
                )
                net_edge_bps = breakdown.net_edge / structure.notional_per_unit * 1e4 \
                    if structure.notional_per_unit else 0.0
                dq = sync.data_quality_score
                decision = risk.check_open(
                    structure, net_edge_bps=net_edge_bps, min_net_edge_bps=min_edge_bps,
                    data_quality=dq, liquidity_score=float(sig.get("liquidity_score", 60.0)),
                    viability_score=float(sig.get("viability_score", 70.0)),
                    latency_sensitivity=strat.SPEC.latency_sensitivity,
                )
                if not decision.ok:
                    key = decision.reason.value if decision.reason else "rejected"
                    rejected[key] = rejected.get(key, 0) + 1
                    equity_curve.append([pt.ts, cash])
                    continue

                # --- open: fill every leg independently ---
                filled: list[ArbFillLeg] = []
                for leg in structure.legs:
                    q, px, cost = self._fill(leg, last[leg.instrument])
                    cash -= self._signed(leg.side, q) * px + cost
                    filled.append(ArbFillLeg(
                        instrument=leg.instrument, side=leg.side, target_qty=leg.quantity,
                        filled_qty=q, entry_price=px, entry_cost=cost))
                fracs = [f.filled_qty / f.target_qty if f.target_qty else 0.0 for f in filled]
                open_legs = filled
                open_fin_accrued = 0.0
                strat.open = OpenState(structure=structure, entry_ts=pt.ts,
                                       entry_index=strat._i, entry_signal=dict(sig))
                strat.open.entry_signal["_net_edge"] = breakdown.net_edge
                strat.open.entry_signal["_leg_imbalance"] = (max(fracs) - min(fracs)) if fracs else 0.0
                strat.open.entry_signal["_partial"] = any(f < 0.999 for f in fracs)
                risk.on_open(structure)
                opps_exec += 1
                equity_curve.append([pt.ts, cash + self._mtm(open_legs, last)])
                continue

            # --- position open: accrue financing, check exit ---
            for f in open_legs:
                notional = f.filled_qty * last.get(f.instrument, f.entry_price)
                rate = borrow_rate if f.side.upper() == "SELL" else fin_rate * 0.0
                open_fin_accrued += notional * rate / self.ppy

            should_exit, reason = strat.check_exit(pt)
            if not should_exit:
                equity_curve.append([pt.ts, cash + self._mtm(open_legs, last) - open_fin_accrued])
                continue

            gross = 0.0
            costs = 0.0
            for f in open_legs:
                seg = {"equity": "equity_intraday", "futures": "futures", "options": "options"}.get(
                    "equity", "equity_intraday")
                exit_side = "SELL" if f.side.upper() == "BUY" else "BUY"
                px = self.cost_model.fill_price_with_slippage(
                    exit_side, last.get(f.instrument, f.entry_price), segment=seg)
                cb = self.cost_model.charge(exit_side, px, f.filled_qty, seg,
                                            reference_price=last.get(f.instrument, f.entry_price))
                f.exit_price = px
                f.exit_cost = cb.total
                cash -= self._signed(exit_side, f.filled_qty) * px + cb.total
                leg_gross = self._signed(f.side, f.filled_qty) * (px - f.entry_price)
                gross += leg_gross
                costs += f.entry_cost + cb.total

            net = gross - costs - open_fin_accrued
            entry_edge = float(strat.open.entry_signal.get("_net_edge", 0.0))
            risk.on_close(strat.open.structure, net)
            trades.append(ArbTrade(
                strategy=strat.SPEC.slug, direction=strat.open.structure.direction,
                legs=open_legs, entry_ts=strat.open.entry_ts, exit_ts=pt.ts,
                bars_held=strat._i - strat.open.entry_index, gross_pnl=gross,
                total_costs=costs, financing_cost=open_fin_accrued, net_pnl=net,
                entry_net_edge=entry_edge, realized_edge=net,
                edge_capture_rate=(net / entry_edge) if entry_edge > 0 else 0.0,
                leg_imbalance=float(strat.open.entry_signal.get("_leg_imbalance", 0.0)),
                partial_fill=bool(strat.open.entry_signal.get("_partial", False)),
                converged=reason == "converged", exit_reason=reason,
            ))
            strat.open = None
            open_legs = []
            open_fin_accrued = 0.0
            equity_curve.append([pt.ts, cash])

        result = self._finalize(equity_curve, trades, opps_seen, opps_exec, sync, rejected, strat)
        result.diagnostics["risk"] = risk.summary()
        return result

    def _mtm(self, legs: list[ArbFillLeg], last: dict[str, float]) -> float:
        return sum(
            self._signed(f.side, f.filled_qty) * last.get(f.instrument, f.entry_price)
            for f in legs
        )

    def _finalize(
        self, equity_curve, trades, opps_seen, opps_exec, sync, rejected, strat,
    ) -> ArbBacktestResult:
        base = compute_metrics([(str(t), v) for t, v in equity_curve],
                               trading_days_per_year=self.ppy) if len(equity_curve) > 1 else {}
        closed = trades
        wins = [t for t in closed if t.net_pnl > 0]
        losses = [t for t in closed if t.net_pnl < 0]
        gross_win = sum(t.net_pnl for t in wins)
        gross_loss = -sum(t.net_pnl for t in losses)
        net_pnl = sum(t.net_pnl for t in closed)
        total_costs = sum(t.total_costs for t in closed)
        conv = [t for t in closed if t.converged]
        partial = [t for t in closed if t.partial_fill]
        ecr = [t.edge_capture_rate for t in closed if t.entry_net_edge > 0]
        avg_hold = sum(t.bars_held for t in closed) / len(closed) if closed else 0.0

        metrics = {
            "net_pnl": round(net_pnl, 2),
            "gross_pnl": round(sum(t.gross_pnl for t in closed), 2),
            "total_costs": round(total_costs, 2),
            "financing_cost": round(sum(t.financing_cost for t in closed), 2),
            "return_on_capital_pct": round(net_pnl / self.capital * 100.0, 4) if self.capital else 0.0,
            "sharpe_ratio": base.get("sharpe_ratio", 0.0),
            "max_drawdown_pct": base.get("max_drawdown_pct", 0.0),
            "cagr_pct": base.get("cagr_pct", 0.0),
            "win_rate_pct": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
            "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else None,
            "opportunities_seen": opps_seen,
            "opportunities_executed": opps_exec,
            "executed_trades": len(closed),
            "avg_net_edge": round(sum(t.entry_net_edge for t in closed) / len(closed), 2)
            if closed else 0.0,
            "avg_holding_bars": round(avg_hold, 2),
            "avg_slippage_per_trade": round(total_costs / len(closed), 2) if closed else 0.0,
            "partial_fill_rate": round(len(partial) / len(closed), 4) if closed else 0.0,
            "leg_imbalance_rate": round(
                sum(1 for t in closed if t.leg_imbalance > 0.02) / len(closed), 4)
            if closed else 0.0,
            "convergence_rate": round(len(conv) / len(closed), 4) if closed else 0.0,
            "failed_convergence_rate": round(1 - len(conv) / len(closed), 4) if closed else 0.0,
            "avg_convergence_bars": round(sum(t.bars_held for t in conv) / len(conv), 2)
            if conv else 0.0,
            "edge_capture_rate": round(sum(ecr) / len(ecr), 4) if ecr else 0.0,
        }
        metrics["arbitrage_quality_score"] = _quality_score(metrics, sync.data_quality_score, strat)
        return ArbBacktestResult(
            equity_curve=[[str(t), round(v, 2)] for t, v in equity_curve],
            trades=closed, opportunities_seen=opps_seen, opportunities_executed=opps_exec,
            metrics=metrics, data_quality=sync.summary(),
            config={
                "strategy": strat.SPEC.slug, "capital": self.capital,
                "sync_mode": self.sync_mode.value, "params": dict(strat.p),
            },
            diagnostics={"rejected": rejected},
        )


def _quality_score(m: dict[str, Any], data_quality: float, strat) -> float:
    """0-100: net profitability, stability, liquidity/data, execution feasibility,
    latency, drawdown."""
    if m["executed_trades"] == 0:
        return 0.0
    score = 0.0
    score += 25.0 * max(0.0, min(1.0, m["edge_capture_rate"]))              # captured the edge
    score += 15.0 * max(0.0, min(1.0, (m["profit_factor"] or 0.0) / 2.0))  # net profitable
    score += 15.0 * max(0.0, min(1.0, m["convergence_rate"]))              # convergence
    score += 15.0 * (data_quality / 100.0)                                # data quality
    score += 10.0 * (1.0 - min(1.0, m["partial_fill_rate"]))              # execution feasibility
    score += 10.0 * max(0.0, 1.0 - m["max_drawdown_pct"] / 25.0)         # drawdown
    lat = {"none": 1.0, "low": 0.9, "medium": 0.6, "high": 0.3, "extreme": 0.0}
    score += 10.0 * lat.get(strat.SPEC.latency_sensitivity, 0.5)          # latency robustness
    return round(max(0.0, min(100.0, score)), 1)


def compute_arb_metrics(result: ArbBacktestResult) -> dict[str, Any]:
    return result.metrics
