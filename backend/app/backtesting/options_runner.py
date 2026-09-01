"""Backtest driver for the NIFTY Monthly HNI strategy.

Iterates every qualifying entry day in a date range, runs the *same*
``evaluate_entry`` / ``evaluate_exit`` used by paper and live, steps the
position forward one calendar day at a time until an exit fires, prices
fills through the shared Indian cost model (options segment), and produces
the standard performance report.

DATA LIMITATION: a faithful run needs a real historical option chain (bid /
ask / last per strike per day for the relevant expiry). The platform does
not integrate an options-data vendor, so callers must supply a
``RecordedOptionData`` source. ``SyntheticOptionData`` (flat-vol
Black-Scholes) is accepted only for exercising the mechanics and the result
is flagged ``synthetic_data: true`` — never treat it as evidence the
strategy works.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.performance import build_charts
from app.backtesting.trades import ClosedTrade
from app.strategies.options.base import MarketData
from app.strategies.options.hni_monthly import HniConfig, evaluate_entry, evaluate_exit

_ENTRY_HOUR, _ENTRY_MIN = 15, 16


def _leg_fill(md: MarketData, cfg: HniConfig, leg, as_of: datetime, cm: CostModel) -> float:
    """Executable entry fill: BUY at ask, SELL at bid, then slippage."""
    q = md.option_quote(cfg.underlying, leg.expiry, leg.strike, "CE", as_of)
    if q is None:
        raise RuntimeError(f"no quote for leg {leg.label} on {as_of.date()}")
    raw = q.ask if leg.action == "BUY" else q.bid
    return cm.fill_price_with_slippage(leg.action, raw, segment="options")


def _leg_exit_fill(md: MarketData, cfg: HniConfig, leg, as_of: datetime, cm: CostModel) -> float:
    """Executable exit fill: close BUY leg by SELL at bid, close SELL leg by BUY at ask."""
    q = md.option_quote(cfg.underlying, leg.expiry, leg.strike, "CE", as_of)
    if q is None:
        raise RuntimeError(f"no exit quote for leg {leg.label} on {as_of.date()}")
    close_side = "SELL" if leg.action == "BUY" else "BUY"
    raw = q.bid if close_side == "SELL" else q.ask
    return cm.fill_price_with_slippage(close_side, raw, segment="options")


def _basket_costs(cm: CostModel, legs, prices: dict[str, float], opening: bool) -> float:
    total = 0.0
    for leg in legs:
        side = leg.action if opening else ("SELL" if leg.action == "BUY" else "BUY")
        px = prices[leg.label]
        total += cm.charge(side, px, leg.quantity, "options", reference_price=px).total
    return total


def run_hni_backtest(
    cfg: HniConfig,
    md: MarketData,
    *,
    start: date,
    end: date,
    cost_config: dict[str, float] | None = None,
) -> dict[str, Any]:
    cm = CostModel(CostConfig.from_dict(cost_config))
    synthetic = bool(getattr(md, "IS_SYNTHETIC", False))

    trades: list[ClosedTrade] = []
    skipped: list[dict[str, Any]] = []
    equity_points: list[tuple[str, float]] = []
    running = 0.0

    d = start
    step = 0
    while d <= end:
        if d.weekday() == cfg.entry_weekday_num:
            as_of = datetime(d.year, d.month, d.day, _ENTRY_HOUR, _ENTRY_MIN)
            dec = evaluate_entry(cfg, as_of, md)
            if not dec.eligible:
                skipped.append({"date": d.isoformat(), "reason": dec.reason})
            else:
                basket = dec.basket
                assert basket is not None
                try:
                    entry_prices = {
                        leg.label: _leg_fill(md, cfg, leg, as_of, cm) for leg in basket.legs
                    }
                    for leg in basket.legs:
                        leg.entry_price = entry_prices[leg.label]
                    open_cost = _basket_costs(cm, basket.legs, entry_prices, opening=True)

                    trade = _hold_to_exit(cfg, basket, md, cm, as_of, open_cost)
                    trades.append(trade)
                    running += trade.net_pnl
                    equity_points.append((trade.exit_time or d.isoformat(), running))
                except Exception as exc:  # noqa: BLE001
                    skipped.append({"date": d.isoformat(), "reason": f"execution: {exc}"})
        d += timedelta(days=1)
        step += 1

    dc_values = [dc for dc in (getattr(t, "_deployed_capital", None) for t in trades) if dc]
    avg_dc = sum(dc_values) / len(dc_values) if dc_values else 0.0

    from app.backtesting.performance import compute_performance

    equity_curve = [("start", 0.0), *equity_points] if equity_points else [("start", 0.0)]
    metrics = compute_performance(
        [(ts, v) for ts, v in equity_curve], trades,
        initial_capital=avg_dc or 1.0,
        total_costs=sum(t.costs for t in trades),
    )
    metrics.update(_hni_stats(trades))

    return {
        "synthetic_data": synthetic,
        "data_warning": (
            "SYNTHETIC option prices (flat-vol Black-Scholes). This is NOT a faithful "
            "historical backtest — supply RecordedOptionData from an option-chain vendor."
            if synthetic else ""
        ),
        "entries": len(trades),
        "skipped_days": skipped,
        "avg_deployed_capital": round(avg_dc, 2),
        "metrics": metrics,
        "trades": [_trade_dict(t) for t in trades],
        "charts": build_charts([(ts, v) for ts, v in equity_curve], trades, avg_dc or 1.0),
    }


def _hold_to_exit(cfg, basket, md, cm, entry_time, open_cost) -> ClosedTrade:
    day = entry_time.date() + timedelta(days=1)
    prev_spot: float | None = basket.spot_at_entry
    last_prices = {leg.label: leg.entry_price for leg in basket.legs}
    reason = "TIME_EXIT"
    exit_day = day

    for _ in range(cfg.max_holding_days + 45):
        as_of = datetime(day.year, day.month, day.day, _ENTRY_HOUR, _ENTRY_MIN)
        spot = md.spot(basket.underlying, as_of)
        if spot is None:
            day += timedelta(days=1)
            continue
        leg_prices: dict[str, float] = {}
        ok = True
        for leg in basket.legs:
            q = md.option_quote(basket.underlying, leg.expiry, leg.strike, "CE", as_of)
            if q is None:
                ok = False
                break
            leg_prices[leg.label] = q.mid
        if not ok:
            day += timedelta(days=1)
            continue
        last_prices = leg_prices
        dec = evaluate_exit(cfg, basket, now=as_of, entry_time=entry_time,
                            spot=spot, prev_spot=prev_spot, leg_prices=leg_prices)
        prev_spot = spot
        exit_day = day
        if dec.should_exit:
            reason = dec.reason
            break
        day += timedelta(days=1)

    exit_dt = datetime(exit_day.year, exit_day.month, exit_day.day, _ENTRY_HOUR, _ENTRY_MIN)
    exit_prices = {
        leg.label: _leg_exit_fill(md, cfg, leg, exit_dt, cm) for leg in basket.legs
    }
    close_cost = _basket_costs(cm, basket.legs, exit_prices, opening=False)

    gross = 0.0
    for leg in basket.legs:
        gross += leg.signed_dir * (exit_prices[leg.label] - leg.entry_price) * leg.quantity
    costs = open_cost + close_cost
    net = gross - costs
    notional = basket.deployed_capital or 1.0

    t = ClosedTrade(
        instrument=f"{basket.underlying} HNI {basket.expiry.isoformat()}",
        direction="ratio", quantity=1,
        entry_time=entry_time.isoformat(), exit_time=exit_dt.isoformat(),
        entry_price=basket.spot_at_entry, exit_price=last_prices.get("B", 0.0),
        gross_pnl=gross, costs=costs, net_pnl=net,
        bars_held=(exit_day - entry_time.date()).days,
        return_pct=net / notional * 100.0 if notional else 0.0,
    )
    t._deployed_capital = basket.deployed_capital  # type: ignore[attr-defined]
    t._exit_reason = reason  # type: ignore[attr-defined]
    t._credit_pct = basket.credit_pct  # type: ignore[attr-defined]
    return t


def _trade_dict(t: ClosedTrade) -> dict[str, Any]:
    d = t.to_dict()
    d["exit_reason"] = getattr(t, "_exit_reason", "")
    d["deployed_capital"] = round(getattr(t, "_deployed_capital", 0.0) or 0.0, 2)
    d["credit_pct"] = round(getattr(t, "_credit_pct", 0.0) or 0.0, 4)
    return d


def _hni_stats(trades: list[ClosedTrade]) -> dict[str, Any]:
    if not trades:
        return {"hni_entries": 0}
    reasons = [getattr(t, "_exit_reason", "") for t in trades]
    n = len(trades)
    return {
        "hni_entries": n,
        "target_hit_pct": round(reasons.count("TARGET") / n * 100, 2),
        "stop_loss_pct": round(reasons.count("STOP_LOSS") / n * 100, 2),
        "short_strike_exit_pct": round(reasons.count("SHORT_STRIKE_EXIT") / n * 100, 2),
        "time_or_expiry_exit_pct": round(
            (reasons.count("TIME_EXIT") + reasons.count("EXPIRY_EXIT")) / n * 100, 2
        ),
        "avg_holding_days": round(sum(t.bars_held for t in trades) / n, 2),
        "avg_credit_pct": round(
            sum(getattr(t, "_credit_pct", 0.0) or 0.0 for t in trades) / n, 4
        ),
        "return_on_deployed_capital_pct": round(
            sum(t.return_pct for t in trades), 4
        ),
    }
