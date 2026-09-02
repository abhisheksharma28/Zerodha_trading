"""Full backtest performance report: scalar metrics + chart series.

Builds on app.backtesting.metrics.compute_metrics (kept for backward
compatibility) and adds the trade-level and risk-adjusted statistics the
Strategy Library UI needs. Pure functions over an equity curve + a list of
ClosedTrade; no DB, no randomness -> deterministic.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from app.backtesting.metrics import compute_metrics
from app.backtesting.trades import ClosedTrade


def _to_dt(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    s = str(ts).strip().replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _sortino(returns: list[float], periods_per_year: int) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0
    dd = math.sqrt(sum(r * r for r in downside) / len(downside))
    return (mean / dd) * math.sqrt(periods_per_year) if dd > 0 else 0.0


def _max_consecutive_losses(trades: list[ClosedTrade]) -> int:
    worst = run = 0
    for t in trades:
        if t.net_pnl < 0:
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    return worst


def compute_performance(
    equity_curve: list[tuple[Any, float]],
    trades: list[ClosedTrade],
    *,
    initial_capital: float,
    total_costs: float,
    trading_days_per_year: int = 252,
) -> dict[str, Any]:
    base = compute_metrics([(str(ts), v) for ts, v in equity_curve],
                           trading_days_per_year=trading_days_per_year)

    values = [v for _, v in equity_curve]
    start = values[0] if values else initial_capital
    end = values[-1] if values else initial_capital
    net_pnl = end - start
    gross_pnl = net_pnl + total_costs

    rets = [
        max(-1.0, values[i] / values[i - 1] - 1.0)
        for i in range(1, len(values))
        if values[i - 1] > 0 and values[i] > 0
    ]
    sortino = _sortino(rets, trading_days_per_year)
    cagr = base["cagr_pct"]
    calmar = (cagr / base["max_drawdown_pct"]) if base["max_drawdown_pct"] > 0 else 0.0

    closed = [t for t in trades if not t.is_open]
    wins = [t for t in closed if t.net_pnl > 0]
    losses = [t for t in closed if t.net_pnl < 0]
    gross_win = sum(t.net_pnl for t in wins)
    gross_loss = -sum(t.net_pnl for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_win > 0 else 0.0
    )
    turnover_value = sum(t.entry_price * t.quantity for t in trades)

    metrics: dict[str, Any] = {
        **base,  # total_return_pct, cagr_pct, max_drawdown_pct, sharpe_ratio, num_bars
        "net_pnl": round(net_pnl, 2),
        "gross_pnl": round(gross_pnl, 2),
        "total_costs": round(total_costs, 2),
        "cost_drag_pct": round(total_costs / start * 100.0, 4) if start else 0.0,
        "return_pct": base["total_return_pct"],
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4),
        "profit_factor": round(profit_factor, 4) if math.isfinite(profit_factor) else None,
        "win_rate_pct": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
        "total_trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "avg_trade": round(sum(t.net_pnl for t in closed) / len(closed), 2) if closed else 0.0,
        "avg_winner": round(gross_win / len(wins), 2) if wins else 0.0,
        "avg_loser": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "largest_winner": round(max((t.net_pnl for t in wins), default=0.0), 2),
        "largest_loser": round(min((t.net_pnl for t in losses), default=0.0), 2),
        "max_consecutive_losses": _max_consecutive_losses(closed),
        "avg_bars_held": round(sum(t.bars_held for t in closed) / len(closed), 2) if closed else 0.0,
        "turnover_ratio": round(turnover_value / initial_capital, 4) if initial_capital else 0.0,
        "capital_utilization_pct": round(
            _avg_exposure_pct(equity_curve, trades, initial_capital), 2
        ),
    }
    return metrics


def _avg_exposure_pct(
    equity_curve: list[tuple[Any, float]], trades: list[ClosedTrade], initial_capital: float
) -> float:
    if not equity_curve or initial_capital <= 0:
        return 0.0
    curve = build_exposure_curve(equity_curve, trades, initial_capital)
    if not curve:
        return 0.0
    return sum(v for _, v in curve) / len(curve)


def build_drawdown_curve(equity_curve: list[tuple[Any, float]]) -> list[list[Any]]:
    out: list[list[Any]] = []
    peak = -math.inf
    for ts, v in equity_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100.0 if peak > 0 else 0.0
        out.append([str(ts), round(dd, 4)])
    return out


def build_monthly_returns(equity_curve: list[tuple[Any, float]]) -> dict[str, float]:
    by_month: dict[str, tuple[float, float]] = {}
    for ts, v in equity_curve:
        d = _to_dt(ts)
        if d is None:
            continue
        key = f"{d.year:04d}-{d.month:02d}"
        first, _ = by_month.get(key, (v, v))
        by_month[key] = (first, v)
    return {k: round((last / first - 1.0) * 100.0, 4) if first else 0.0
            for k, (first, last) in sorted(by_month.items())}


def build_daily_pnl(equity_curve: list[tuple[Any, float]]) -> list[list[Any]]:
    by_day: dict[str, tuple[float, float]] = {}
    order: list[str] = []
    for ts, v in equity_curve:
        d = _to_dt(ts)
        key = d.date().isoformat() if d else str(ts)
        if key not in by_day:
            by_day[key] = (v, v)
            order.append(key)
        else:
            by_day[key] = (by_day[key][0], v)
    out = []
    prev_close: float | None = None
    for key in order:
        first, last = by_day[key]
        ref = prev_close if prev_close is not None else first
        out.append([key, round(last - ref, 2)])
        prev_close = last
    return out


def build_exposure_curve(
    equity_curve: list[tuple[Any, float]], trades: list[ClosedTrade], initial_capital: float
) -> list[list[Any]]:
    """Approx gross exposure over time: for each equity point, sum the
    notional of trades open at that timestamp, as a % of initial capital."""
    if initial_capital <= 0:
        return []
    spans = []
    for t in trades:
        e = _to_dt(t.entry_time)
        x = _to_dt(t.exit_time) if t.exit_time is not None else None
        spans.append((e, x, abs(t.entry_price * t.quantity)))
    out: list[list[Any]] = []
    for ts, _v in equity_curve:
        d = _to_dt(ts)
        if d is None:
            out.append([str(ts), 0.0])
            continue
        gross = sum(
            notional
            for (e, x, notional) in spans
            if e is not None and e <= d and (x is None or d <= x)
        )
        out.append([str(ts), round(gross / initial_capital * 100.0, 2)])
    return out


def trade_return_histogram(trades: list[ClosedTrade], bins: int = 20) -> dict[str, Any]:
    returns = [t.return_pct for t in trades if not t.is_open]
    if not returns:
        return {"bins": [], "counts": [], "returns": []}
    lo, hi = min(returns), max(returns)
    if lo == hi:
        lo, hi = lo - 1.0, hi + 1.0
    width = (hi - lo) / bins
    edges = [lo + i * width for i in range(bins + 1)]
    counts = [0] * bins
    for r in returns:
        k = min(bins - 1, int((r - lo) / width))
        counts[k] += 1
    return {
        "bin_edges": [round(e, 4) for e in edges],
        "counts": counts,
        "returns": [round(r, 4) for r in returns],
    }


def build_charts(
    equity_curve: list[tuple[Any, float]], trades: list[ClosedTrade], initial_capital: float
) -> dict[str, Any]:
    return {
        "drawdown_curve": build_drawdown_curve(equity_curve),
        "monthly_returns": build_monthly_returns(equity_curve),
        "daily_pnl": build_daily_pnl(equity_curve),
        "exposure_curve": build_exposure_curve(equity_curve, trades, initial_capital),
        "trade_return_distribution": trade_return_histogram(trades),
    }
