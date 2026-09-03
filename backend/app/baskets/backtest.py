"""Walk-forward backtest of a basket.

Daily bars, CNC (equity delivery) cost model, weights held between
rebalances and marked to market each day. Rebalances land on the first
trading day of each week / month / quarter once enough history exists for
the longest sleeve lookback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.adhoc import fetch_candles
from app.backtesting.costs import CostModel
from app.baskets.engine import _as_dt, plan_orders, resolve_targets
from app.baskets.spec import BasketSpec
from app.config import Settings
from app.core.exceptions import ValidationError

_COSTS = CostModel()
_TDAYS_YEAR = 252


@dataclass
class RebalanceSnapshot:
    as_of: str
    portfolio_value: float
    weights: dict[str, float]
    n_orders: int
    turnover_pct: float
    cash_pct: float
    notes: list[str] = field(default_factory=list)


@dataclass
class BasketBacktestResult:
    start: str
    end: str
    years: float
    capital: float
    benchmark: str
    frequency: str
    equity_curve: list[tuple[str, float]]
    benchmark_curve: list[tuple[str, float]]
    metrics: dict[str, float | None]
    rebalances: list[RebalanceSnapshot]
    final_holdings: dict[str, int]
    skipped: list[dict[str, str]]
    caveats: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start, "end": self.end, "years": self.years,
            "capital": self.capital, "benchmark": self.benchmark,
            "frequency": self.frequency,
            "equity_curve": [[d, round(v, 2)] for d, v in self.equity_curve],
            "benchmark_curve": [[d, round(v, 2)] for d, v in self.benchmark_curve],
            "metrics": self.metrics,
            "rebalances": [
                {
                    "as_of": r.as_of, "portfolio_value": round(r.portfolio_value, 2),
                    "weights": {k: round(v, 4) for k, v in r.weights.items()},
                    "n_orders": r.n_orders, "turnover_pct": round(r.turnover_pct, 2),
                    "cash_pct": round(r.cash_pct, 2), "notes": r.notes,
                }
                for r in self.rebalances
            ],
            "final_holdings": self.final_holdings,
            "skipped": self.skipped,
            "caveats": self.caveats,
        }


def _period_key(dt: datetime, freq: str) -> tuple:
    if freq == "weekly":
        iso = dt.isocalendar()
        return (iso[0], iso[1])
    if freq == "quarterly":
        return (dt.year, (dt.month - 1) // 3)
    return (dt.year, dt.month)  # monthly


def _warmup_bars(spec: BasketSpec) -> int:
    need = 30
    for s in spec.sleeves:
        if s.rule.active:
            need = max(need, s.rule.lookback + 5, s.rule.trend_ma + 5)
        if s.weighting in ("inverse_vol", "momentum_weighted"):
            need = max(need, 95)
    return need


def _annualised_stats(curve: list[tuple[str, float]]) -> dict[str, float | None]:
    if len(curve) < 3:
        return {"sharpe_ratio": None, "volatility_pct": None, "max_drawdown_pct": None}
    vals = [v for _, v in curve]
    rets = [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if len(rets) < 2:
        return {"sharpe_ratio": None, "volatility_pct": None, "max_drawdown_pct": None}
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    sharpe = (mean / sd) * math.sqrt(_TDAYS_YEAR) if sd > 1e-12 else None
    vol_pct = sd * math.sqrt(_TDAYS_YEAR) * 100.0
    peak = vals[0]
    max_dd = 0.0
    for v in vals:
        peak = max(peak, v)
        max_dd = min(max_dd, v / peak - 1.0)
    return {
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "volatility_pct": round(vol_pct, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
    }


def run_backtest(
    db: Session,
    settings: Settings,
    spec: BasketSpec,
    *,
    years: float = 5.0,
    capital: float = 500_000.0,
    benchmark: str = "NIFTY 50",
    frequency: str = "monthly",
    drift_band_pct: float = 3.0,
) -> BasketBacktestResult:
    if not spec.sleeves:
        raise ValidationError("basket has no sleeves")
    years = max(1.0, min(float(years), 12.0))
    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=int(years * 365.25) + 30)

    symbols = list(dict.fromkeys([*spec.symbols, benchmark]))
    candles, skipped = fetch_candles(
        db, settings, symbols=symbols, timeframe="1d",
        start=start_dt.date().isoformat(), end=end_dt.date().isoformat(),
    )
    if not candles:
        raise ValidationError("no price history for any basket member in the window")

    # normalise key casing: fetch_candles returns by tradingsymbol
    bars_by_symbol: dict[str, list[Any]] = {}
    for want in symbols:
        for got, bars in candles.items():
            if got.upper() == want.upper():
                bars_by_symbol[want] = bars
                break

    bench_bars = bars_by_symbol.get(benchmark) or []
    if len(bench_bars) < 60:
        raise ValidationError(f"benchmark {benchmark!r} has too little history")

    # master calendar = benchmark trading days
    dates = [_as_dt(b.timestamp) for b in bench_bars]
    dates.sort()

    # per-symbol close lookup: last close at or before a date (forward fill)
    close_series: dict[str, list[tuple[datetime, float]]] = {}
    for sym, bars in bars_by_symbol.items():
        rows = sorted(((_as_dt(b.timestamp), float(b.close)) for b in bars), key=lambda t: t[0])
        close_series[sym] = rows

    def price_on(sym: str, dt: datetime) -> float | None:
        rows = close_series.get(sym)
        if not rows:
            return None
        lo, hi, ans = 0, len(rows) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if rows[mid][0] <= dt:
                ans = rows[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return ans

    warmup = _warmup_bars(spec)
    if len(dates) <= warmup + 20:
        raise ValidationError(
            f"need > {warmup + 20} trading days of history, have {len(dates)}"
        )

    cash = float(capital)
    holdings: dict[str, int] = {}
    equity_curve: list[tuple[str, float]] = []
    bench_curve: list[tuple[str, float]] = []
    rebalances: list[RebalanceSnapshot] = []

    bench_p0 = price_on(benchmark, dates[warmup])
    seen_periods: set[tuple] = set()

    def mtm(dt: datetime, cash_now: float, held: dict[str, int]) -> float:
        v = cash_now
        for s, q in held.items():
            p = price_on(s, dt)
            if p:
                v += q * p
        return v

    for i in range(warmup, len(dates)):
        dt = dates[i]
        pv = mtm(dt, cash, holdings)
        pkey = _period_key(dt, frequency)
        is_rebalance = pkey not in seen_periods
        if is_rebalance:
            seen_periods.add(pkey)
            res = resolve_targets(spec, bars_by_symbol, dt)
            prices = {s: price_on(s, dt) or 0.0 for s in set(spec.symbols) | set(holdings)}
            intents = plan_orders(
                res.weights, holdings, prices, pv, drift_band_pct=drift_band_pct
            )
            traded_value = 0.0
            for it in intents:
                px_ref = prices.get(it.symbol) or 0.0
                if px_ref <= 0:
                    continue
                fill = _COSTS.fill_price_with_slippage(it.side, px_ref, segment="equity_delivery")
                br = _COSTS.charge(
                    it.side, fill, it.qty, "equity_delivery", reference_price=px_ref
                )
                notional = fill * it.qty
                traded_value += notional
                if it.side == "BUY":
                    cash -= notional + br.total
                    holdings[it.symbol] = holdings.get(it.symbol, 0) + it.qty
                else:
                    cash += notional - br.total
                    holdings[it.symbol] = holdings.get(it.symbol, 0) - it.qty
                if holdings.get(it.symbol, 0) <= 0:
                    holdings.pop(it.symbol, None)
            pv_after = mtm(dt, cash, holdings)
            rebalances.append(
                RebalanceSnapshot(
                    as_of=dt.date().isoformat(),
                    portfolio_value=pv_after,
                    weights={
                        s: (q * (price_on(s, dt) or 0.0)) / pv_after if pv_after > 0 else 0.0
                        for s, q in holdings.items()
                    },
                    n_orders=len(intents),
                    turnover_pct=(traded_value / pv * 100.0) if pv > 0 else 0.0,
                    cash_pct=(cash / pv_after * 100.0) if pv_after > 0 else 0.0,
                    notes=res.notes[:6],
                )
            )

        equity_curve.append((dt.date().isoformat(), mtm(dt, cash, holdings)))
        bp = price_on(benchmark, dt)
        if bench_p0 and bp:
            bench_curve.append((dt.date().isoformat(), capital * bp / bench_p0))

    total_ret = (equity_curve[-1][1] / capital - 1.0) * 100.0 if equity_curve else 0.0
    span_years = max((dates[-1] - dates[warmup]).days / 365.25, 0.25)
    cagr = ((equity_curve[-1][1] / capital) ** (1.0 / span_years) - 1.0) * 100.0 if equity_curve else 0.0
    bench_ret = (bench_curve[-1][1] / capital - 1.0) * 100.0 if bench_curve else None
    ann = _annualised_stats(equity_curve)
    # the first rebalance buys the whole basket from cash — exclude it so the
    # turnover numbers reflect ongoing churn, not the one-off deployment
    ongoing = [r.turnover_pct for r in rebalances[1:] if r.turnover_pct > 0]
    per_year = len(rebalances) / span_years if span_years > 0 else 0.0

    metrics: dict[str, float | None] = {
        "total_return_pct": round(total_ret, 2),
        "cagr_pct": round(cagr, 2),
        "benchmark_return_pct": round(bench_ret, 2) if bench_ret is not None else None,
        "excess_return_pct": round(total_ret - bench_ret, 2) if bench_ret is not None else None,
        "n_rebalances": len(rebalances),
        "rebalances_per_year": round(per_year, 1),
        "avg_turnover_pct": round(sum(ongoing) / len(ongoing), 2) if ongoing else 0.0,
        "annual_turnover_pct": round(
            (sum(ongoing) / len(ongoing)) * per_year, 1
        ) if ongoing else 0.0,
        **ann,
    }

    caveats = [
        "Daily close-to-close fills at the rebalance date's close, plus slippage + the "
        "Indian statutory cost stack (CNC / delivery).",
        "Member list and sleeve rules are fixed as written — survivorship bias if names "
        "were added or removed over the window.",
        "Sleeve rules use only causal data (bars at or before each rebalance date).",
    ]
    return BasketBacktestResult(
        start=dates[warmup].date().isoformat(),
        end=dates[-1].date().isoformat(),
        years=round(span_years, 2),
        capital=capital,
        benchmark=benchmark,
        frequency=frequency,
        equity_curve=equity_curve,
        benchmark_curve=bench_curve,
        metrics=metrics,
        rebalances=rebalances,
        final_holdings=dict(sorted(holdings.items())),
        skipped=skipped,
        caveats=caveats,
    )
