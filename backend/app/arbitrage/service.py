"""Arbitrage Lab orchestration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.arbitrage import store
from app.arbitrage.data_sync import SyncMode
from app.arbitrage.engine import ArbitrageBacktestEngine
from app.arbitrage.futures_data import expiry_epoch_for
from app.arbitrage.pair_discovery import discover_pairs
from app.arbitrage.registry import ARB_STRATEGIES, FUTURES_SLUGS, get_arb_strategy
from app.arbitrage.types import ArbCategory
from app.backtesting.adhoc import fetch_candles
from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.timeframes import bars_per_year
from app.config import Settings
from app.core.exceptions import ValidationError
from app.strategies.library.base import ParamError

_CATEGORY_HELP = {
    ArbCategory.TRUE_ARBITRAGE.value: "Locked-in profit if executed simultaneously and held to "
    "settlement — rare and small after costs.",
    ArbCategory.STATISTICAL_ARBITRAGE.value: "Historical mean reversion, not guaranteed; the "
    "relationship can break permanently.",
    ArbCategory.RELATIVE_VALUE.value: "A view that two things are mispriced relative to each "
    "other; directional risk remains.",
    ArbCategory.BASIS_ARBITRAGE.value: "Spot-vs-derivative convergence at expiry; carry, "
    "dividends and margin drive the real edge.",
    ArbCategory.LATENCY_DEPENDENT.value: "Only real for participants faster than the opportunity "
    "decays — needs colo / direct feeds.",
    ArbCategory.RESEARCH_ONLY.value: "Studied for signal, not executable on this platform's "
    "infrastructure.",
}

_NET_EDGE_RULE = (
    "NET_EXPECTED_EDGE = GROSS_EDGE - brokerage - exchange/taxes - bid/ask spread - slippage - "
    "market impact - financing - borrow - execution-risk buffer. An opportunity is only "
    "executable when NET_EXPECTED_EDGE exceeds the strategy's configured minimum."
)


def arb_library() -> dict[str, Any]:
    return {
        "strategies": [s.detail() for s in ARB_STRATEGIES],
        "categories": _CATEGORY_HELP,
        "net_edge_rule": _NET_EDGE_RULE,
        "roadmap": {
            "implemented": [s.SPEC.slug for s in ARB_STRATEGIES],
            "planned": [
                "put-call-parity", "conversion-reversal", "etf-nav-dislocation",
                "index-component-dislocation", "volatility-relative-value", "lead-lag-research",
                "cross-exchange", "triangular", "adr-gdr-research", "dual-listing",
            ],
        },
    }


def _resolve_params(cls, preset: str, overrides: dict[str, Any] | None) -> dict[str, Any]:
    presets = cls.PRESETS
    if preset not in presets:
        raise ValidationError(f"Unknown preset '{preset}' — {sorted(presets)}")
    try:
        return cls.resolve_params({**presets[preset], **(overrides or {})})
    except ParamError as exc:
        raise ValidationError(f"Invalid parameters: {exc}") from exc


def run_arb_backtest(
    db: Session,
    settings: Settings,
    *,
    slug: str,
    symbol_a: str,
    symbol_b: str,
    timeframe: str = "1d",
    start: str | None = None,
    end: str | None = None,
    preset: str = "balanced",
    overrides: dict[str, Any] | None = None,
    sync_mode: str = SyncMode.REJECT_STALE_DATA.value,
    max_data_age_seconds: float = 300.0,
) -> dict[str, Any]:
    try:
        cls = get_arb_strategy(slug)
    except KeyError as exc:
        raise ValidationError(str(exc)) from exc
    if timeframe not in cls.SPEC.supported_timeframes:
        raise ValidationError(
            f"{cls.SPEC.name} supports {', '.join(cls.SPEC.supported_timeframes)}, not {timeframe}."
        )

    # for basis / carry / calendar strategies, derive expiry epochs from the
    # instrument master when the caller didn't pass them explicitly.
    ov = dict(overrides or {})
    if slug in FUTURES_SLUGS:
        if slug == "calendar-spread":
            ov.setdefault("near_expiry_ts", expiry_epoch_for(db, symbol_a))
            ov.setdefault("far_expiry_ts", expiry_epoch_for(db, symbol_b))
        else:
            ov.setdefault("expiry_ts", expiry_epoch_for(db, symbol_b))
    params = _resolve_params(cls, preset, ov)

    to_dt = datetime.now()
    from_dt = (datetime.fromisoformat(start) if start else to_dt - timedelta(days=800))
    s0 = from_dt.date().isoformat()
    e0 = (datetime.fromisoformat(end).date().isoformat() if end else to_dt.date().isoformat())
    candles, skipped = fetch_candles(
        db, settings, symbols=[symbol_a, symbol_b], timeframe=timeframe, start=s0, end=e0,
    )
    if len(candles) < 2:
        raise ValidationError(f"Need price history for both legs. skipped={skipped}")

    try:
        smode = SyncMode(sync_mode)
    except ValueError as exc:
        raise ValidationError(f"Bad sync_mode '{sync_mode}'.") from exc
    try:
        ppy = round(bars_per_year(timeframe))
    except Exception:  # noqa: BLE001
        ppy = 252

    result = ArbitrageBacktestEngine(
        cls, params, capital=float(params["capital"]),
        cost_model=CostModel(CostConfig()), sync_mode=smode,
        max_data_age_seconds=max_data_age_seconds, periods_per_year=ppy,
    ).run(candles)

    legs = list(candles)
    payload = {
        "slug": slug,
        "strategy_name": cls.SPEC.name,
        "category": cls.SPEC.category.value,
        "legs": legs,
        "preset": preset,
        "timeframe": timeframe,
        "start": s0,
        "end": e0,
        "sync_mode": smode.value,
        "params": params,
        "metrics": result.metrics,
        "data_quality": result.data_quality,
        "diagnostics": result.diagnostics,
        "opportunities_seen": result.opportunities_seen,
        "opportunities_executed": result.opportunities_executed,
        "equity_curve": _downsample(result.equity_curve),
        "trades": [t.as_dict() for t in result.trades][:200],
        "warning": cls.SPEC.warning,
        "infra_note": cls.SPEC.infra_note,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    store.save("backtest", f"{slug}__{legs[0]}__{legs[1]}", payload)
    return payload


def _downsample(curve: list[list[Any]], n: int = 400) -> list[list[Any]]:
    if len(curve) <= n:
        return curve
    step = len(curve) / n
    return [curve[min(len(curve) - 1, int(i * step))] for i in range(n)] + [curve[-1]]


def discover_pairs_for_universe(
    db: Session,
    settings: Settings,
    *,
    symbols: list[str],
    timeframe: str = "1d",
    days: int = 500,
    adf_threshold: float = -3.0,
    top_n: int = 40,
) -> dict[str, Any]:
    if len(symbols) < 2:
        raise ValidationError("Need at least 2 symbols.")
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=days)
    candles, skipped = fetch_candles(
        db, settings, symbols=symbols, timeframe=timeframe,
        start=from_dt.date().isoformat(), end=to_dt.date().isoformat(),
    )
    if len(candles) < 2:
        raise ValidationError(f"No usable history. skipped={skipped}")
    rows = discover_pairs(candles, adf_threshold=adf_threshold, top_n=top_n,
                          min_bars=min(250, max(60, days // 2)))
    payload = {
        "universe_size": len(candles),
        "requested": len(symbols),
        "skipped": skipped,
        "timeframe": timeframe,
        "days": days,
        "adf_threshold": adf_threshold,
        "pairs": rows,
        "tradeable_count": sum(1 for r in rows if r["tradeable"]),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    store.save("discovery", f"{timeframe}__{len(candles)}syms__{days}d", payload)
    return payload


def arb_portfolio() -> dict[str, Any]:
    runs = store.list_kind("backtest")
    rows = []
    total_net = 0.0
    for r in runs:
        m = r.get("metrics", {})
        total_net += float(m.get("net_pnl") or 0.0)
        rows.append({
            "slug": r["slug"], "strategy_name": r["strategy_name"], "category": r["category"],
            "legs": r["legs"], "preset": r["preset"],
            "opportunities": r.get("opportunities_seen", 0),
            "executed": r.get("opportunities_executed", 0),
            "net_pnl": m.get("net_pnl"),
            "return_on_capital_pct": m.get("return_on_capital_pct"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "avg_net_edge": m.get("avg_net_edge"),
            "edge_capture_rate": m.get("edge_capture_rate"),
            "convergence_rate": m.get("convergence_rate"),
            "arbitrage_quality_score": m.get("arbitrage_quality_score"),
            "data_quality_score": (r.get("data_quality") or {}).get("data_quality_score"),
            "generated_at": r.get("generated_at"),
        })
    rows.sort(key=lambda x: x.get("arbitrage_quality_score") or -1, reverse=True)
    return {
        "runs": rows,
        "run_count": len(rows),
        "combined_net_pnl": round(total_net, 2),
        "note": "Arbitrage runs only — completely separate from the Quant Strategy Leaderboard.",
    }
