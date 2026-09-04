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
    regime: str = "normal"
    changes: list[dict[str, Any]] = field(default_factory=list)  # per-name change log
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
    oos: dict[str, Any] = field(default_factory=dict)
    regime_breakdown: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start, "end": self.end, "years": self.years,
            "capital": self.capital, "benchmark": self.benchmark,
            "frequency": self.frequency,
            "equity_curve": [[d, round(v, 2)] for d, v in self.equity_curve],
            "benchmark_curve": [[d, round(v, 2)] for d, v in self.benchmark_curve],
            "metrics": self.metrics,
            "oos": self.oos,
            "regime_breakdown": self.regime_breakdown,
            "rebalances": [
                {
                    "as_of": r.as_of, "portfolio_value": round(r.portfolio_value, 2),
                    "weights": {k: round(v, 4) for k, v in r.weights.items()},
                    "n_orders": r.n_orders, "turnover_pct": round(r.turnover_pct, 2),
                    "cash_pct": round(r.cash_pct, 2), "regime": r.regime,
                    "changes": r.changes, "notes": r.notes,
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
        if s.weighting in ("inverse_vol", "momentum_weighted", "score_weighted"):
            need = max(need, 95)
    if spec.risk.regime is not None:
        # the 5-state regime engine wants ~1y for its trend / vol-percentile signals
        need = max(need, spec.risk.regime.ma + 5, 260)
    return need


def _daily_rets(curve: list[tuple[str, float]]) -> list[float]:
    vals = [v for _, v in curve]
    return [vals[i] / vals[i - 1] - 1.0 for i in range(1, len(vals)) if vals[i - 1] > 0]


def _max_dd(vals: list[float]) -> float:
    peak, mdd = (vals[0] if vals else 1.0), 0.0
    for v in vals:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    return mdd


def _mean_sd(xs: list[float]) -> tuple[float, float]:
    if len(xs) < 2:
        return (xs[0] if xs else 0.0), 0.0
    m = sum(xs) / len(xs)
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _annualised_stats(curve: list[tuple[str, float]]) -> dict[str, float | None]:
    if len(curve) < 3:
        return {"sharpe_ratio": None, "volatility_pct": None, "max_drawdown_pct": None}
    rets = _daily_rets(curve)
    if len(rets) < 2:
        return {"sharpe_ratio": None, "volatility_pct": None, "max_drawdown_pct": None}
    mean, sd = _mean_sd(rets)
    sharpe = (mean / sd) * math.sqrt(_TDAYS_YEAR) if sd > 1e-12 else None
    return {
        "sharpe_ratio": round(sharpe, 3) if sharpe is not None else None,
        "volatility_pct": round(sd * math.sqrt(_TDAYS_YEAR) * 100.0, 2),
        "max_drawdown_pct": round(_max_dd([v for _, v in curve]) * 100.0, 2),
    }


def _extended_stats(
    curve: list[tuple[str, float]], bench: list[tuple[str, float]], capital: float
) -> dict[str, float | None]:
    """Sortino, Calmar, beta, alpha, tracking error, information ratio,
    monthly win rate, best/worst month & year."""
    out: dict[str, float | None] = {
        "sortino_ratio": None, "calmar_ratio": None, "beta": None, "alpha_pct": None,
        "tracking_error_pct": None, "information_ratio": None, "monthly_win_rate_pct": None,
        "best_month_pct": None, "worst_month_pct": None, "best_year_pct": None,
        "worst_year_pct": None,
    }
    rets = _daily_rets(curve)
    if len(rets) < 20:
        return out
    mean, sd = _mean_sd(rets)
    downs = [r for r in rets if r < 0]
    dd_sd = math.sqrt(sum(r * r for r in downs) / len(downs)) if downs else 0.0
    if dd_sd > 1e-12:
        out["sortino_ratio"] = round((mean / dd_sd) * math.sqrt(_TDAYS_YEAR), 3)
    span_years = max(len(rets) / _TDAYS_YEAR, 0.25)
    cagr = (curve[-1][1] / capital) ** (1.0 / span_years) - 1.0
    mdd = abs(_max_dd([v for _, v in curve]))
    if mdd > 1e-6:
        out["calmar_ratio"] = round(cagr / mdd, 3)

    # align benchmark daily returns to the same dates
    bmap = dict(bench)
    pv = dict(curve)
    dts = [d for d, _ in curve]
    pr, br = [], []
    for i in range(1, len(dts)):
        d0, d1 = dts[i - 1], dts[i]
        if d0 in bmap and d1 in bmap and bmap[d0] > 0 and pv[d0] > 0:
            pr.append(pv[d1] / pv[d0] - 1.0)
            br.append(bmap[d1] / bmap[d0] - 1.0)
    if len(pr) > 20:
        bmean, bsd = _mean_sd(br)
        cov = sum((pr[i] - mean) * (br[i] - bmean) for i in range(len(pr))) / (len(pr) - 1)
        if bsd > 1e-12:
            beta = cov / (bsd * bsd)
            out["beta"] = round(beta, 3)
            out["alpha_pct"] = round((mean - beta * bmean) * _TDAYS_YEAR * 100.0, 2)
        diff = [pr[i] - br[i] for i in range(len(pr))]
        dmean, dsd = _mean_sd(diff)
        te = dsd * math.sqrt(_TDAYS_YEAR)
        out["tracking_error_pct"] = round(te * 100.0, 2)
        if te > 1e-9:
            out["information_ratio"] = round((dmean * _TDAYS_YEAR) / te, 3)

    # calendar-month and calendar-year returns
    def _bucketed(key_len: int) -> list[float]:
        by: dict[str, list[float]] = {}
        prev_v = curve[0][1]
        for d, v in curve[1:]:
            by.setdefault(d[:key_len], []).append(v / prev_v - 1.0 if prev_v > 0 else 0.0)
            prev_v = v
        res = []
        for _k, rs in by.items():
            comp = 1.0
            for r in rs:
                comp *= 1.0 + r
            res.append(comp - 1.0)
        return res

    months = _bucketed(7)
    years = _bucketed(4)
    if months:
        wins = [m for m in months if m > 0]
        out["monthly_win_rate_pct"] = round(len(wins) / len(months) * 100.0, 1)
        out["best_month_pct"] = round(max(months) * 100.0, 2)
        out["worst_month_pct"] = round(min(months) * 100.0, 2)
    if years:
        out["best_year_pct"] = round(max(years) * 100.0, 2)
        out["worst_year_pct"] = round(min(years) * 100.0, 2)
    return out


def _split_stats(
    curve: list[tuple[str, float]], bench: list[tuple[str, float]], oos_frac: float = 0.35
) -> dict[str, Any]:
    """In-sample vs out-of-sample return / Sharpe / max-DD, so a strong
    number is not just an artefact of the first half of the window."""
    if len(curve) < 60:
        return {}
    cut = int(len(curve) * (1.0 - oos_frac))
    if cut < 20 or len(curve) - cut < 20:
        return {}

    def _seg(c: list[tuple[str, float]]) -> dict[str, float | None]:
        if len(c) < 3 or c[0][1] <= 0:
            return {"return_pct": None, "sharpe_ratio": None, "max_drawdown_pct": None}
        rets = _daily_rets(c)
        m, sd = _mean_sd(rets)
        return {
            "start": c[0][0], "end": c[-1][0],
            "return_pct": round((c[-1][1] / c[0][1] - 1.0) * 100.0, 2),
            "sharpe_ratio": round((m / sd) * math.sqrt(_TDAYS_YEAR), 3) if sd > 1e-12 else None,
            "max_drawdown_pct": round(_max_dd([v for _, v in c]) * 100.0, 2),
        }

    bmap = dict(bench)

    def _bench_seg(c: list[tuple[str, float]]) -> float | None:
        ds = [d for d, _ in c if d in bmap]
        if len(ds) < 2 or bmap[ds[0]] <= 0:
            return None
        return round((bmap[ds[-1]] / bmap[ds[0]] - 1.0) * 100.0, 2)

    is_c, oos_c = curve[:cut], curve[cut:]
    return {
        "in_sample": {**_seg(is_c), "benchmark_return_pct": _bench_seg(is_c)},
        "out_of_sample": {**_seg(oos_c), "benchmark_return_pct": _bench_seg(oos_c)},
    }


def _regime_breakdown(
    curve: list[tuple[str, float]], bench: list[tuple[str, float]]
) -> dict[str, Any]:
    """Split the equity curve's daily returns by whether the benchmark was
    above or below its own 200-day average that day (bull vs bear tape)."""
    if len(bench) < 210 or len(curve) < 60:
        return {}
    bvals = [v for _, v in bench]
    bdates = [d for d, _ in bench]
    ma_state: dict[str, bool] = {}
    for i in range(len(bvals)):
        if i < 200:
            continue
        ma = sum(bvals[i - 200:i]) / 200.0
        ma_state[bdates[i]] = bvals[i] >= ma
    pv = dict(curve)
    dts = [d for d, _ in curve]
    bull, bear = [], []
    for i in range(1, len(dts)):
        d0, d1 = dts[i - 1], dts[i]
        if d0 not in ma_state or pv[d0] <= 0:
            continue
        r = pv[d1] / pv[d0] - 1.0
        (bull if ma_state[d0] else bear).append(r)

    def _agg(rs: list[float]) -> dict[str, float | None]:
        if len(rs) < 10:
            return {"days": len(rs), "return_pct": None, "ann_vol_pct": None}
        comp = 1.0
        for r in rs:
            comp *= 1.0 + r
        _m, sd = _mean_sd(rs)
        return {
            "days": len(rs),
            "return_pct": round((comp - 1.0) * 100.0, 2),
            "ann_vol_pct": round(sd * math.sqrt(_TDAYS_YEAR) * 100.0, 2),
        }

    return {"bull_tape": _agg(bull), "bear_tape": _agg(bear)}


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
    entry_dt: dict[str, datetime] = {}     # first bar we opened each name
    hold_spans: list[float] = []           # days held, on close
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
            res = resolve_targets(
                spec, bars_by_symbol, dt, current_holdings=holdings,
                market_bars=bench_bars,
            )
            prices = {s: price_on(s, dt) or 0.0 for s in set(spec.symbols) | set(holdings)}
            reasons: dict[str, str] = {}
            for sym in set(res.weights) | set(holdings):
                sc = res.score_of(sym)
                if sym in res.weights and sym not in holdings:
                    reasons[sym] = (
                        f"added — composite score {sc:.0f}/100" if sc is not None
                        else "added — cleared the rule"
                    )
                elif sym in holdings and sym not in res.weights:
                    reasons[sym] = (
                        f"removed — score {sc:.0f}/100 below the hold buffer" if sc is not None
                        else "removed — fell below the rank / trend gate"
                    )
            if res.regime not in ("normal", "strong_bull", "bull"):
                reasons["_regime"] = f"regime {res.regime}: risk-asset exposure trimmed"
            intents = plan_orders(
                res.weights, holdings, prices, pv,
                drift_band_pct=drift_band_pct, reasons=reasons,
            )
            traded_value = 0.0
            changes: list[dict[str, Any]] = []
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
                    if it.symbol not in holdings:
                        entry_dt[it.symbol] = dt
                    holdings[it.symbol] = holdings.get(it.symbol, 0) + it.qty
                else:
                    cash += notional - br.total
                    holdings[it.symbol] = holdings.get(it.symbol, 0) - it.qty
                if holdings.get(it.symbol, 0) <= 0:
                    holdings.pop(it.symbol, None)
                    if it.symbol in entry_dt:
                        hold_spans.append((dt - entry_dt.pop(it.symbol)).days)
                changes.append(it.to_dict())
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
                    regime=res.regime,
                    changes=changes[:24],
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
    ext = _extended_stats(equity_curve, bench_curve, capital)
    # the first rebalance buys the whole basket from cash — exclude it so the
    # turnover numbers reflect ongoing churn, not the one-off deployment
    ongoing = [r.turnover_pct for r in rebalances[1:] if r.turnover_pct > 0]
    per_year = len(rebalances) / span_years if span_years > 0 else 0.0
    open_spans = [(dates[-1] - e).days for e in entry_dt.values()]
    all_spans = hold_spans + open_spans

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
        "avg_holding_days": round(sum(all_spans) / len(all_spans), 0) if all_spans else None,
        **ann,
        **ext,
    }
    oos = _split_stats(equity_curve, bench_curve)
    regime_breakdown = _regime_breakdown(equity_curve, bench_curve)

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
        oos=oos,
        regime_breakdown=regime_breakdown,
    )
