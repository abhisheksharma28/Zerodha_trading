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
    # a reported return can't be worse than -100% (total wipeout); a leveraged
    # book that goes negative would otherwise print numbers like -593%. The
    # `ruined` flag in RunDiagnostics carries the "it blew up" detail.
    total_return_pct = max(-100.0, (end / start - 1) * 100) if start and start > 0 else 0.0

    n_periods = len(values) - 1
    years = n_periods / trading_days_per_year if trading_days_per_year else 1
    if end <= 0:
        # equity was wiped out (or went negative on leverage) — CAGR of a
        # non-positive terminal value is undefined; report a total loss.
        # `negative ** fractional` would otherwise be a complex number and
        # blow up round().
        cagr_pct = -100.0
    elif start > 0 and years > 0:
        cagr_pct = ((end / start) ** (1 / years) - 1) * 100
    else:
        cagr_pct = 0.0

    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak
            max_dd = max(max_dd, min(1.0, dd))  # clamp: a >100% "drawdown" is nonsense

    returns = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        # only meaningful while the book is solvent; once equity <= 0 the
        # ratio explodes and pollutes vol / Sharpe. Clamp each period to -100%.
        if prev and prev > 0 and values[i] > 0:
            returns.append(max(-1.0, (values[i] - prev) / prev))

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
