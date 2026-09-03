"""Ad-hoc strategy backtest — run a library template over a chosen set of
symbols with no database row.

This powers the downloadable "backtest report" on the Strategy Library
detail page: the user picks a strategy, one or more NIFTY 200 symbols, a
window and a preset, and gets metrics + charts on screen and a one-click
PDF. It reuses the exact same BacktestEngine / cost model / performance
code as the persisted backtests, so the numbers match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.engine import BacktestEngine
from app.backtesting.performance import build_charts, compute_performance
from app.backtesting.timeframes import (
    UnknownTimeframeError,
    bars_per_year,
    canonical,
    kite_interval,
    resolve,
)
from app.backtesting.trades import ClosedTrade, reconstruct_trades
from app.config import Settings
from app.core.exceptions import ValidationError
from app.market_data.cache import get_candles
from app.market_data.instruments import resolve_instrument_token
from app.services import broker_service
from app.strategies.library import get_template
from app.strategies.library.base import ParamError, TemplateStrategy

_MAX_SYMBOLS = 30
_DEFAULT_DAYS = {"1m": 20, "3m": 40, "5m": 120, "15m": 250, "30m": 400, "1h": 500, "1d": 900}

_STANDING_CAVEATS = [
    "Research report — mechanics only, not investment advice or a performance guarantee.",
    "Universe is the current NIFTY 200 list; historical runs therefore carry survivorship "
    "bias (names added/removed over the window are not reflected).",
    "Position sizing across many concurrent instruments in one run is still being validated; "
    "single-symbol and small baskets are reliable, large baskets may over-state leverage.",
]


@dataclass
class SymbolStat:
    symbol: str
    trades: int
    net_pnl: float
    win_rate_pct: float
    avg_trade: float
    largest_winner: float
    largest_loser: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "trades": self.trades,
            "net_pnl": round(self.net_pnl, 2),
            "win_rate_pct": round(self.win_rate_pct, 2),
            "avg_trade": round(self.avg_trade, 2),
            "largest_winner": round(self.largest_winner, 2),
            "largest_loser": round(self.largest_loser, 2),
        }


@dataclass
class AdhocReport:
    slug: str
    strategy_name: str
    preset: str
    timeframe: str
    start: str
    end: str
    capital: float
    requested_symbols: list[str]
    used_symbols: list[str]
    skipped: list[dict[str, str]]
    parameters: dict[str, Any]
    metrics: dict[str, Any]
    charts: dict[str, Any]
    equity_curve: list[list[Any]]
    per_symbol: list[SymbolStat]
    trades: list[dict[str, Any]]
    data_quality: dict[str, Any]
    caveats: list[str] = field(default_factory=list)
    generated_at: str = ""
    trade_pnls: list[float] = field(default_factory=list)  # full, uncapped — for Monte Carlo

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "strategy_name": self.strategy_name,
            "preset": self.preset,
            "timeframe": self.timeframe,
            "start": self.start,
            "end": self.end,
            "capital": self.capital,
            "requested_symbols": self.requested_symbols,
            "used_symbols": self.used_symbols,
            "skipped": self.skipped,
            "parameters": self.parameters,
            "metrics": self.metrics,
            "charts": self.charts,
            "equity_curve": self.equity_curve,
            "per_symbol": [s.as_dict() for s in self.per_symbol],
            "trades": self.trades,
            "data_quality": self.data_quality,
            "caveats": self.caveats,
            "generated_at": self.generated_at,
        }


def _window(timeframe: str, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    def _parse(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise ValidationError(f"Bad date '{s}' — use ISO (YYYY-MM-DD).") from exc

    fd, td = _parse(start), _parse(end)
    to_dt = td or datetime.now()
    if fd:
        from_dt = fd
    else:
        span = _DEFAULT_DAYS.get(canonical(timeframe), 250)
        from_dt = to_dt - timedelta(days=span)
    if from_dt >= to_dt:
        raise ValidationError("start must be before end.")
    return from_dt, to_dt


def fetch_candles(
    db: Session, settings: Settings, *, symbols: list[str], timeframe: str,
    start: str | None, end: str | None,
) -> tuple[dict[str, list], list[dict[str, str]]]:
    """Resolve + fetch OHLCV bars for a symbol list over a window. Returns
    ``(candles_by_tradingsymbol, skipped)``. Reused by the parameter-sim and
    other batch tools so they don't reimplement the fetch loop."""
    from app.backtesting.timeframes import resolve

    tf = resolve(timeframe)
    client = broker_service.build_authenticated_client(db, settings)
    from_dt, to_dt = _window(tf.token, start, end)
    interval = kite_interval(tf.token)
    candles: dict[str, list] = {}
    skipped: list[dict[str, str]] = []
    for sym in symbols:
        try:
            token, tradingsymbol = resolve_instrument_token(sym)
        except Exception:  # noqa: BLE001
            skipped.append({"symbol": sym, "reason": "not found in instrument master"})
            continue
        try:
            bars = get_candles(client, token, tradingsymbol, interval, from_dt, to_dt)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"symbol": sym, "reason": f"history unavailable: {exc}"})
            continue
        if bars:
            candles[tradingsymbol] = bars
        else:
            skipped.append({"symbol": sym, "reason": "no candles in window"})
    return candles, skipped


def _per_symbol(trades: list[ClosedTrade]) -> list[SymbolStat]:
    by: dict[str, list[ClosedTrade]] = {}
    for t in trades:
        if t.is_open:
            continue
        by.setdefault(t.instrument, []).append(t)
    out: list[SymbolStat] = []
    for sym, ts in sorted(by.items()):
        wins = [t for t in ts if t.net_pnl > 0]
        out.append(SymbolStat(
            symbol=sym,
            trades=len(ts),
            net_pnl=sum(t.net_pnl for t in ts),
            win_rate_pct=len(wins) / len(ts) * 100.0 if ts else 0.0,
            avg_trade=sum(t.net_pnl for t in ts) / len(ts) if ts else 0.0,
            largest_winner=max((t.net_pnl for t in ts), default=0.0),
            largest_loser=min((t.net_pnl for t in ts), default=0.0),
        ))
    return out


def run_adhoc(
    db: Session,
    settings: Settings,
    *,
    slug: str,
    symbols: list[str],
    timeframe: str = "1d",
    start: str | None = None,
    end: str | None = None,
    preset: str = "balanced",
    capital: float = 1_000_000.0,
    overrides: dict[str, Any] | None = None,
    max_gross_exposure: float = 4.0,
    max_symbols: int = _MAX_SYMBOLS,
    template_cls: type[TemplateStrategy] | None = None,
) -> AdhocReport:
    """``slug`` names a library template; pass ``template_cls`` to run an
    arbitrary ``TemplateStrategy`` subclass instead (the Python editor path)."""
    if template_cls is not None:
        template = template_cls
    else:
        try:
            template = get_template(slug)
        except KeyError as exc:
            raise ValidationError(str(exc)) from exc

    try:
        tf = resolve(timeframe)
    except UnknownTimeframeError as exc:
        raise ValidationError(str(exc)) from exc
    if tf.token not in template.SUPPORTED_TIMEFRAMES:
        raise ValidationError(
            f"{template.NAME} does not support {tf.token} — "
            f"supported: {', '.join(template.SUPPORTED_TIMEFRAMES)}"
        )

    clean = [s.strip().upper() for s in symbols if s and s.strip()]
    if not clean:
        raise ValidationError("Pick at least one symbol.")
    if len(clean) > max_symbols:
        raise ValidationError(f"At most {max_symbols} symbols per report (got {len(clean)}).")

    presets = template.presets()
    if preset not in presets:
        raise ValidationError(f"Unknown preset '{preset}' — {sorted(presets)}")
    raw_params = {**presets[preset], **(overrides or {})}
    try:
        params = template.resolve_params(raw_params)
    except ParamError as exc:
        raise ValidationError(f"Invalid parameters: {exc}") from exc

    client = broker_service.build_authenticated_client(db, settings)
    from_dt, to_dt = _window(tf.token, start, end)
    interval = kite_interval(tf.token)

    candles: dict[str, list] = {}
    skipped: list[dict[str, str]] = []
    for sym in clean:
        try:
            token, tradingsymbol = resolve_instrument_token(sym)
        except Exception:  # noqa: BLE001
            skipped.append({"symbol": sym, "reason": "not found in instrument master"})
            continue
        try:
            bars = get_candles(client, token, tradingsymbol, interval, from_dt, to_dt)
        except Exception as exc:  # noqa: BLE001
            skipped.append({"symbol": sym, "reason": f"history unavailable: {exc}"})
            continue
        if not bars:
            skipped.append({"symbol": sym, "reason": "no candles in window"})
            continue
        candles[tradingsymbol] = bars

    if not candles:
        raise ValidationError(
            "No usable price history for the chosen symbols/window. "
            + (f"Skipped: {skipped}" if skipped else "")
        )

    dq = validate_candles(candles, timeframe=tf.token)

    engine = BacktestEngine(
        template, params, float(capital), cost_model=CostModel(CostConfig()),
        max_gross_exposure=max_gross_exposure,
    )
    result = engine.run(candles)

    mark = {s: float(b[-1].close) for s, b in candles.items() if b}
    trades = reconstruct_trades(
        result.fills, fill_costs=[f.cost for f in result.fills], mark_prices=mark
    )
    try:
        ppy = round(bars_per_year(tf.token))
    except UnknownTimeframeError:
        ppy = 252
    metrics = compute_performance(
        result.equity_curve, trades, initial_capital=float(capital),
        total_costs=result.total_costs, trading_days_per_year=ppy,
    )
    metrics["cost_breakdown"] = result.cost_breakdown
    metrics["timeframe"] = tf.token
    charts = build_charts(result.equity_curve, trades, float(capital))

    diag = result.diagnostics.to_dict()
    metrics["diagnostics"] = diag
    caveats = list(_STANDING_CAVEATS)
    for w in dq.get("warnings", []):
        caveats.append(f"Data quality: {w}")
    if metrics.get("total_trades", 0) == 0:
        caveats.append("Zero trades — the strategy/preset produced no entries in this window.")
    if diag.get("ruined"):
        caveats.append(
            f"RUINED — mark-to-market equity hit zero at {diag.get('ruin_ts')}; the engine "
            "stopped trading there. Returns are floored at -100%; this preset is over-leveraged "
            "for this universe."
        )
    if diag.get("exposure_capped_orders"):
        caveats.append(
            f"{diag['exposure_capped_orders']} order(s) were scaled down by the "
            f"{max_gross_exposure:g}x gross-exposure cap (peak exposure "
            f"{diag.get('peak_gross_exposure_pct', 0):.0f}% of capital)."
        )

    return AdhocReport(
        slug=slug,
        strategy_name=template.NAME,
        preset=preset,
        timeframe=tf.token,
        start=from_dt.date().isoformat(),
        end=to_dt.date().isoformat(),
        capital=float(capital),
        requested_symbols=clean,
        used_symbols=sorted(candles),
        skipped=skipped,
        parameters=params,
        metrics=metrics,
        charts=charts,
        equity_curve=[[str(ts), round(v, 2)] for ts, v in result.equity_curve],
        per_symbol=_per_symbol(trades),
        trades=[t.to_dict() for t in trades][:500],
        trade_pnls=[round(float(t.net_pnl), 2) for t in trades if not t.is_open],
        data_quality=dq,
        caveats=caveats,
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )
