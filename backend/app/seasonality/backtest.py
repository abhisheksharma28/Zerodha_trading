"""Walk-forward, strictly out-of-sample backtest of the seasonal sector
rankings.

At each test month the ranking is rebuilt from *prior* completed months
only (expanding or rolling window), sectors are picked long / short, and
the realised sector-index return for that month is booked with a
transaction-cost haircut. We report rank IC (did the predicted order
match the realised order?), the top-vs-bottom spread, and full
risk-adjusted stats — in-sample and out-of-sample kept separate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.seasonality.data import load_history
from app.seasonality.returns import build_panel

logger = get_logger(__name__)

_TDAYS_MONTH = 21
_MONTHS_YEAR = 12

STRATEGIES = {
    "A_long_best": {"long": 1, "short": 0},
    "B_short_worst": {"long": 0, "short": 1},
    "C_long_top3": {"long": 3, "short": 0},
    "D_short_bottom3": {"long": 0, "short": 3},
    "E_long_top3_short_bottom3": {"long": 3, "short": 3},
    "F_top20_bottom20": {"long": "20pct", "short": "20pct"},
}


@dataclass
class Trade:
    year: int
    month: int
    side: str        # LONG | SHORT
    sector: str
    predicted_rank: int
    gross_pct: float
    net_pct: float


@dataclass
class WalkForwardResult:
    strategy: str
    mode: str
    start_test: str
    end_test: str
    n_months: int
    long_cost_bps: float
    short_cost_bps: float
    equity_curve: list[tuple[str, float]]
    metrics: dict[str, float | None]
    rank_ic: dict[str, float | None]
    spread: dict[str, float | None]
    oos_split: dict[str, Any]
    trades: list[Trade] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy, "mode": self.mode,
            "start_test": self.start_test, "end_test": self.end_test,
            "n_months": self.n_months,
            "long_cost_bps": self.long_cost_bps, "short_cost_bps": self.short_cost_bps,
            "equity_curve": [[d, round(v, 4)] for d, v in self.equity_curve],
            "metrics": self.metrics, "rank_ic": self.rank_ic, "spread": self.spread,
            "oos_split": self.oos_split,
            "trades": [
                {"date": f"{t.year}-{t.month:02d}", "side": t.side, "sector": t.sector,
                 "predicted_rank": t.predicted_rank, "gross_pct": round(t.gross_pct, 3),
                 "net_pct": round(t.net_pct, 3)}
                for t in self.trades[-240:]
            ],
        }


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3 or len(a) != len(b):
        return None

    def _rank(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(xs):
            j = i
            while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = _rank(a), _rank(b)
    n = len(a)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def _metrics(monthly: list[float]) -> dict[str, float | None]:
    if len(monthly) < 6:
        return {"cagr_pct": None, "sharpe": None, "max_dd_pct": None}
    eq = [1.0]
    for r in monthly:
        eq.append(eq[-1] * (1.0 + r / 100.0))
    years = len(monthly) / _MONTHS_YEAR
    total = eq[-1] - 1.0
    cagr = eq[-1] ** (1.0 / max(years, 0.25)) - 1.0
    m, sd = _mean(monthly), _std(monthly)
    downs = [x for x in monthly if x < 0]
    dd_sd = math.sqrt(sum(x * x for x in downs) / len(downs)) if downs else 0.0
    peak, mdd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1.0)
    wins = [x for x in monthly if x > 0]
    return {
        "total_return_pct": round(total * 100.0, 2),
        "cagr_pct": round(cagr * 100.0, 2),
        "ann_vol_pct": round(sd * math.sqrt(_MONTHS_YEAR), 2),
        "sharpe": round((m / sd) * math.sqrt(_MONTHS_YEAR), 3) if sd > 1e-9 else None,
        "sortino": round((m / dd_sd) * math.sqrt(_MONTHS_YEAR), 3) if dd_sd > 1e-9 else None,
        "calmar": round((cagr) / abs(mdd), 3) if mdd < -1e-6 else None,
        "max_dd_pct": round(mdd * 100.0, 2),
        "monthly_win_rate_pct": round(len(wins) / len(monthly) * 100.0, 1),
        "avg_month_pct": round(m, 3),
        "median_month_pct": round(sorted(monthly)[len(monthly) // 2], 3),
        "best_month_pct": round(max(monthly), 2),
        "worst_month_pct": round(min(monthly), 2),
    }


def walk_forward(
    db: Session,
    settings: Settings,
    *,
    strategy: str = "E_long_top3_short_bottom3",
    mode: str = "expanding",           # expanding | rolling
    rolling_years: int = 12,
    start_test_year: int = 2012,
    min_train_years: int = 6,
    long_cost_bps: float = 30.0,
    short_cost_bps: float = 60.0,
    oos_frac: float = 0.4,
) -> WalkForwardResult:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy '{strategy}' (use {list(STRATEGIES)})")
    cfg = STRATEGIES[strategy]

    bars_by, audits = load_history(db, settings)
    usable = [s for s, a in audits.items()
              if a.status != "FAIL" and s not in ("NIFTY 50", "INDIA VIX") and s in bars_by]
    panel = build_panel(bars_by, sectors=usable)
    rets = panel["returns"]           # {sector: {(y,m): ret%}}
    own = panel["own"]               # {sector: {(y,m): own edge}}

    all_ym = sorted({ym for r in rets.values() for ym in r})
    if not all_ym:
        raise ValueError("no monthly returns available")
    last_y, _ = all_ym[-1]

    def _pick(n_spec: Any, ordered: list[str], *, bottom: bool) -> list[str]:
        if not n_spec:
            return []
        k = max(1, round(len(ordered) * 0.2)) if n_spec == "20pct" else int(n_spec)
        return ordered[-k:][::-1] if bottom else ordered[:k]

    monthly_returns: list[float] = []
    dates: list[str] = []
    ic_vals: list[float] = []
    spread_vals: list[float] = []
    trades: list[Trade] = []

    for (ty, tm) in all_ym:
        if ty < start_test_year:
            continue
        train_lo = (ty - rolling_years) if mode == "rolling" else 0
        # score = mean own-edge for calendar month tm over strictly earlier years
        scores: dict[str, float] = {}
        for s in usable:
            hist = [own[s][(y, m)] for (y, m) in own[s]
                    if m == tm and train_lo <= y < ty]
            if len(hist) >= min_train_years:
                scores[s] = sum(hist) / len(hist)
        if len(scores) < 4:
            continue
        ordered = sorted(scores, key=lambda s: scores[s], reverse=True)
        rank_of = {s: i + 1 for i, s in enumerate(ordered)}

        # realised returns this test month
        actual = {s: rets[s][(ty, tm)] for s in ordered if (ty, tm) in rets[s]}
        if len(actual) < 4:
            continue

        longs = [s for s in _pick(cfg["long"], ordered, bottom=False) if s in actual]
        shorts = [s for s in _pick(cfg["short"], ordered, bottom=True) if s in actual]

        leg_rets: list[float] = []
        for s in longs:
            g = actual[s]
            net = g - long_cost_bps / 100.0
            leg_rets.append(net)
            trades.append(Trade(ty, tm, "LONG", s, rank_of[s], g, net))
        for s in shorts:
            g = -actual[s]
            net = g - short_cost_bps / 100.0
            leg_rets.append(net)
            trades.append(Trade(ty, tm, "SHORT", s, rank_of[s], -actual[s], net))
        if not leg_rets:
            continue
        monthly_returns.append(sum(leg_rets) / len(leg_rets))
        dates.append(f"{ty}-{tm:02d}")

        # rank IC: predicted order vs realised order, over the common sectors
        common = [s for s in ordered if s in actual]
        ic = _spearman([float(rank_of[s]) for s in common],
                       [-actual[s] for s in common])  # negate: rank 1 should be best
        if ic is not None:
            ic_vals.append(ic)
        if longs and shorts:
            spread_vals.append(_mean([actual[s] for s in longs]) - _mean([actual[s] for s in shorts]))

    if len(monthly_returns) < 6:
        raise ValueError("not enough test months — widen the window")

    eq = [1.0]
    for r in monthly_returns:
        eq.append(eq[-1] * (1.0 + r / 100.0))
    curve = [(dates[i], eq[i + 1]) for i in range(len(dates))]

    cut = int(len(monthly_returns) * (1.0 - oos_frac))
    oos_split = {
        "in_sample": {**_metrics(monthly_returns[:cut]),
                      "start": dates[0] if dates else None,
                      "end": dates[cut - 1] if cut else None},
        "out_of_sample": {**_metrics(monthly_returns[cut:]),
                          "start": dates[cut] if cut < len(dates) else None,
                          "end": dates[-1] if dates else None},
    }

    pos_ic = sum(1 for x in ic_vals if x > 0)
    return WalkForwardResult(
        strategy=strategy, mode=mode,
        start_test=dates[0], end_test=dates[-1], n_months=len(monthly_returns),
        long_cost_bps=long_cost_bps, short_cost_bps=short_cost_bps,
        equity_curve=curve,
        metrics=_metrics(monthly_returns),
        rank_ic={
            "mean": round(_mean(ic_vals), 4) if ic_vals else None,
            "median": round(sorted(ic_vals)[len(ic_vals) // 2], 4) if ic_vals else None,
            "pct_positive_months": round(pos_ic / len(ic_vals) * 100.0, 1) if ic_vals else None,
            "n_months": len(ic_vals),
        },
        spread={
            "mean_pct": round(_mean(spread_vals), 3) if spread_vals else None,
            "median_pct": round(sorted(spread_vals)[len(spread_vals) // 2], 3) if spread_vals else None,
            "pct_positive_months": round(
                sum(1 for x in spread_vals if x > 0) / len(spread_vals) * 100.0, 1
            ) if spread_vals else None,
            "n_months": len(spread_vals),
        },
        oos_split=oos_split,
        trades=trades,
    )


def run_all_strategies(
    db: Session, settings: Settings, **kw: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(), "strategies": {}}
    for name in STRATEGIES:
        try:
            out["strategies"][name] = walk_forward(db, settings, strategy=name, **kw).to_dict()
        except Exception as exc:  # noqa: BLE001
            out["strategies"][name] = {"error": str(exc)}
            logger.warning("seasonality_wf_failed", strategy=name, err=str(exc))
    return out
