"""Backtest performance metrics.

Kept dependency-light (pure Python, no numpy requirement for the core
metrics) so this module is trivially unit-testable — see
backend/tests/test_backtesting.py.
"""

import math


def compute_metrics(equity_curve: list[tuple[str, float]], *, trading_days_per_year: int = 252) -> dict:
    if len(equity_curve) < 2:
        return {
            "total_return_pct": 0.0,
            "cagr_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "num_bars": len(equity_curve),
        }

    values = [v for _, v in equity_curve]
    start, end = values[0], values[-1]
    total_return_pct = (end / start - 1) * 100 if start else 0.0

    n_periods = len(values) - 1
    years = n_periods / trading_days_per_year if trading_days_per_year else 1
    cagr_pct = ((end / start) ** (1 / years) - 1) * 100 if start > 0 and years > 0 else 0.0

    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, dd)

    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            returns.append((values[i] - prev) / prev)

    if returns:
        mean_r = sum(returns) / len(returns)
        variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
        std_r = math.sqrt(variance)
        sharpe = (mean_r / std_r) * math.sqrt(trading_days_per_year) if std_r > 0 else 0.0
    else:
        sharpe = 0.0

    return {
        "total_return_pct": round(total_return_pct, 4),
        "cagr_pct": round(cagr_pct, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "num_bars": len(equity_curve),
    }
