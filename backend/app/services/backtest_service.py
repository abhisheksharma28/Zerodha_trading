"""Backtest creation + execution.

`run_backtest` executes synchronously in-process for now — for a
single-user local deployment this is fine for reasonably sized universes;
the natural follow-up is moving this onto app.workers so long backtests
don't block a request. It's structured as a plain function specifically so
that migration is a call-site change, not a rewrite.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.backtesting.costs import CostConfig, CostModel
from app.backtesting.data_quality import validate_candles
from app.backtesting.diagnostics import explain_no_trades
from app.backtesting.engine import BacktestEngine, SimulatedFill
from app.backtesting.performance import build_charts, compute_performance
from app.backtesting.timeframes import UnknownTimeframeError, bars_per_year, kite_interval, resolve
from app.backtesting.trades import reconstruct_trades
from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.market_data.cache import get_candles
from app.market_data.instruments import resolve_instrument_token
from app.models.backtest import Backtest
from app.models.enums import (
    AuditAction,
    BacktestStatus,
    ChangeEntityType,
    OrderStatus,
    OrderType,
    ProductType,
    TradingMode,
)
from app.models.enums import OrderTransactionType as TxnType
from app.models.order import Order, Trade
from app.models.strategy import StrategyVersion
from app.repositories.backtest_repository import BacktestRepository
from app.schemas.backtest import BacktestCreate
from app.services import broker_service
from app.strategies.base import Bar
from app.strategies.registry import load_strategy_class

_MAX_PERSISTED_ORDERS = 5000

logger = get_logger(__name__)


def create_backtest(db: Session, payload: BacktestCreate) -> Backtest:
    version = db.get(StrategyVersion, payload.strategy_version_id)
    if version is None:
        raise NotFoundError(f"Strategy version {payload.strategy_version_id} not found")
    if payload.end_date <= payload.start_date:
        raise ValidationError("end_date must be after start_date")

    try:
        canonical_tf = resolve(payload.timeframe).token
    except UnknownTimeframeError as exc:
        raise ValidationError(str(exc)) from exc
    _validate_timeframe_supported(version, canonical_tf)

    backtest = Backtest(
        strategy_version_id=payload.strategy_version_id,
        instrument_universe=payload.instrument_universe,
        start_date=payload.start_date,
        end_date=payload.end_date,
        initial_capital=payload.initial_capital,
        timeframe=canonical_tf,
        status=BacktestStatus.PENDING,
    )
    db.add(backtest)
    db.flush()

    record_audit(
        db,
        action=AuditAction.CREATE,
        entity_type=ChangeEntityType.STRATEGY_VERSION,
        entity_id=backtest.id,
        summary=f"Created backtest for strategy version {version.version_number}",
    )
    db.commit()
    db.refresh(backtest)
    return backtest


def _validate_timeframe_supported(version: StrategyVersion, canonical_tf: str) -> None:
    """Refuse a timeframe the strategy was not designed for, with a reason —
    never run it and return misleading numbers. Hand-written user strategies
    (no SUPPORTED_TIMEFRAMES declaration) are not restricted."""
    try:
        strategy_cls = load_strategy_class(version.source_code, version.entry_point)
    except Exception:  # noqa: BLE001 - compile errors surface elsewhere
        return
    supported = getattr(strategy_cls, "SUPPORTED_TIMEFRAMES", None)
    if supported and canonical_tf not in supported:
        raise ValidationError(
            f"This strategy does not support the {canonical_tf} timeframe. "
            f"Supported: {', '.join(supported)}. "
            "Intraday strategies need intraday bars; end-of-day strategies expect daily bars — "
            "running on the wrong timeframe would produce misleading results."
        )


def _bars_from_rows(tradingsymbol: str, rows: list[list[Any]]) -> list[Bar]:
    """Rows are ``[timestamp, open, high, low, close, volume]`` (Kite's shape)."""
    bars: list[Bar] = []
    for row in rows:
        ts, o, hi, lo, c, v = row[0], row[1], row[2], row[3], row[4], row[5]
        bars.append(
            Bar(timestamp=ts, open=o, high=hi, low=lo, close=c, volume=v, instrument=tradingsymbol)
        )
    return bars


def _fetch_candles_via_broker(db: Session, settings: Settings, backtest: Backtest) -> dict[str, list[Bar]]:
    client = broker_service.build_authenticated_client(db, settings)
    interval = kite_interval(backtest.timeframe)  # canonical token -> Kite's interval string
    candles_by_instrument: dict[str, list[Bar]] = {}
    for symbol in backtest.instrument_universe:
        token, tradingsymbol = resolve_instrument_token(symbol)
        candles_by_instrument[tradingsymbol] = get_candles(
            client,
            token,
            tradingsymbol,
            interval,
            backtest.start_date,
            backtest.end_date,
        )
    return candles_by_instrument


def execute_backtest(
    db: Session,
    backtest_id,
    *,
    settings: Settings,
    inline_candles: dict[str, list[list[Any]]] | None = None,
    cost_config: dict[str, Any] | None = None,
) -> Backtest:
    """Resolve candle data for a PENDING/FAILED backtest, then run the engine.

    Candles come either from ``inline_candles`` (client-supplied, the only
    path available on the free Kite tier) or from the connected broker
    session. Any failure is recorded on the row as ``status=FAILED`` with a
    human-readable ``error_message`` and the refreshed row is returned rather
    than raised — the caller is an API endpoint whose client polls the row.
    """

    backtest = db.get(Backtest, backtest_id)
    if backtest is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    if backtest.status == BacktestStatus.RUNNING:
        raise ValidationError("Backtest is already running.")

    try:
        if inline_candles:
            candles_by_instrument = {
                tradingsymbol: _bars_from_rows(tradingsymbol, rows)
                for tradingsymbol, rows in inline_candles.items()
            }
        else:
            candles_by_instrument = _fetch_candles_via_broker(db, settings, backtest)

        if not any(candles_by_instrument.values()):
            raise ValidationError(
                "No candles to run against. Supply `candles` in the request body, "
                "or connect a broker session on the paid Kite Connect plan."
            )

        dq = validate_candles(candles_by_instrument, timeframe=backtest.timeframe)
        if not dq["ok"]:
            raise ValidationError(
                "Data-quality check failed — refusing to backtest on bad candles: "
                + "; ".join(dq["errors"])
            )
    except Exception as exc:  # noqa: BLE001 - surface every failure onto the row
        backtest.status = BacktestStatus.FAILED
        backtest.error_message = str(exc)[:2000]
        backtest.completed_at = datetime.now(UTC)
        db.commit()
        db.refresh(backtest)
        logger.warning("backtest_execute_failed", backtest_id=str(backtest_id), error=str(exc))
        return backtest

    try:
        return run_backtest(
            db, backtest_id, candles_by_instrument,
            cost_config=cost_config, data_quality=dq,
        )
    except Exception:  # noqa: BLE001 - run_backtest already recorded FAILED + committed
        db.refresh(backtest)
        return backtest


def _persist_backtest_orders(db: Session, backtest: Backtest, fills: list[SimulatedFill]) -> bool:
    """Write one COMPLETE Order + matching Trade per fill, tagged with this
    backtest_id, so the unified trade log spans backtests too. Skipped for
    very large runs to keep a single request responsive."""
    if len(fills) > _MAX_PERSISTED_ORDERS:
        return False
    for f in fills:
        placed = _parse_ts(f.bar_timestamp)
        try:
            product = ProductType(f.product)
        except ValueError:
            product = ProductType.CNC
        order = Order(
            mode=TradingMode.BACKTEST,
            backtest_id=backtest.id,
            tradingsymbol=f.instrument,
            exchange=f.exchange,
            transaction_type=TxnType(f.transaction_type),
            order_type=OrderType.MARKET,
            product=product,
            quantity=int(f.quantity),
            price=round(float(f.price), 4),
            status=OrderStatus.COMPLETE,
            placed_at=placed,
            raw_request={"segment": f.segment, "reference_price": round(f.reference_price, 4),
                         "cost": round(f.cost, 4)},
        )
        db.add(order)
        db.flush()
        db.add(Trade(
            order_id=order.id,
            mode=TradingMode.BACKTEST,
            fill_price=round(float(f.price), 4),
            fill_quantity=int(f.quantity),
            fill_time=placed or datetime.now(UTC),
        ))
    return True


def _parse_ts(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts
    s = str(ts).strip().replace("Z", "+00:00")
    if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def run_backtest(
    db: Session,
    backtest_id,
    candles_by_instrument: dict[str, list],
    *,
    cost_config: dict[str, Any] | None = None,
    data_quality: dict[str, Any] | None = None,
) -> Backtest:
    """`candles_by_instrument` is pre-fetched by the caller (typically via
    app.market_data.cache.get_candles per instrument) so this function has
    no direct broker dependency and is easy to unit test with synthetic
    data — see backend/tests/test_backtesting.py.

    A realistic Indian cost model is applied by default; pass an explicit
    `cost_config` (e.g. all-zero rates) to see gross P&L instead."""

    backtest = db.get(Backtest, backtest_id)
    if backtest is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")

    version = db.get(StrategyVersion, backtest.strategy_version_id)
    if version is None:
        raise NotFoundError(f"Strategy version {backtest.strategy_version_id} not found")
    strategy_cls = load_strategy_class(version.source_code, version.entry_point)

    try:
        cost_model = CostModel(CostConfig.from_dict(cost_config))
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    backtest.status = BacktestStatus.RUNNING
    backtest.started_at = datetime.now(UTC)
    db.commit()

    try:
        initial_capital = float(backtest.initial_capital)
        engine = BacktestEngine(strategy_cls, version.parameters, initial_capital,
                                cost_model=cost_model)
        result = engine.run(candles_by_instrument)

        mark_prices = {
            sym: float(bars[-1].close) for sym, bars in candles_by_instrument.items() if bars
        }
        trades = reconstruct_trades(
            result.fills,
            fill_costs=[f.cost for f in result.fills],
            mark_prices=mark_prices,
        )
        try:
            periods_per_year = round(bars_per_year(backtest.timeframe))
        except UnknownTimeframeError:
            periods_per_year = 252
        metrics = compute_performance(
            result.equity_curve, trades,
            initial_capital=initial_capital, total_costs=result.total_costs,
            trading_days_per_year=periods_per_year,
        )
        metrics["cost_breakdown"] = result.cost_breakdown
        metrics["timeframe"] = backtest.timeframe
        metrics["periods_per_year"] = periods_per_year
        charts = build_charts(result.equity_curve, trades, initial_capital)

        dq = data_quality or {"ok": True, "errors": [], "warnings": [], "per_symbol": []}
        diagnostics = result.diagnostics.to_dict()
        no_trades_analysis: list[str] = []
        if metrics.get("total_trades", 0) == 0:
            no_trades_analysis = explain_no_trades(
                result.diagnostics, dq,
                timeframe=backtest.timeframe,
                min_bars_required=getattr(strategy_cls, "MIN_BARS_REQUIRED", 0) or None,
            )

        orders_persisted = _persist_backtest_orders(db, backtest, result.fills)

        backtest.equity_curve = [[str(ts), value] for ts, value in result.equity_curve]
        backtest.metrics = {
            **metrics,
            "charts": charts,
            "trades": [t.to_dict() for t in trades][:2000],
            "cost_config": cost_model.config.to_dict(),
            "orders_persisted": orders_persisted,
            "data_quality": dq,
            "diagnostics": diagnostics,
            "no_trades_analysis": no_trades_analysis,
        }
        backtest.status = BacktestStatus.COMPLETED
        backtest.completed_at = datetime.now(UTC)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        backtest = db.get(Backtest, backtest_id)
        assert backtest is not None  # committed row survives the rollback
        backtest.status = BacktestStatus.FAILED
        backtest.error_message = str(exc)[:2000]
        backtest.completed_at = datetime.now(UTC)
        db.commit()
        raise

    record_audit(
        db,
        action=AuditAction.UPDATE,
        entity_type=ChangeEntityType.STRATEGY_VERSION,
        entity_id=backtest.id,
        summary=(
            f"Backtest completed: {metrics['total_trades']} trades, "
            f"net {metrics['net_pnl']:.0f} ({metrics['return_pct']:.2f}%), "
            f"costs {metrics['total_costs']:.0f}"
        ),
        after={"status": "completed", "total_trades": metrics["total_trades"]},
    )
    db.commit()
    db.refresh(backtest)
    return backtest


def backtest_report(db: Session, backtest_id) -> dict[str, Any]:
    """Assemble the full report from the stored metrics blob + equity curve."""
    backtest = get_backtest(db, backtest_id)
    m = dict(backtest.metrics or {})
    charts = m.pop("charts", {})
    trades = m.pop("trades", [])
    cost_config = m.pop("cost_config", {})
    cost_breakdown = m.pop("cost_breakdown", {})
    data_quality = m.pop("data_quality", {"ok": True, "errors": [], "warnings": [], "per_symbol": []})
    diagnostics = m.pop("diagnostics", {})
    no_trades_analysis = m.pop("no_trades_analysis", [])
    return {
        "backtest_id": str(backtest.id),
        "status": backtest.status.value,
        "instrument_universe": backtest.instrument_universe,
        "timeframe": backtest.timeframe,
        "initial_capital": float(backtest.initial_capital),
        "error_message": backtest.error_message,
        "metrics": m,
        "cost_config": cost_config,
        "cost_breakdown": cost_breakdown,
        "data_quality": data_quality,
        "diagnostics": diagnostics,
        "no_trades_analysis": no_trades_analysis,
        "equity_curve": backtest.equity_curve or [],
        "charts": charts,
        "trades": trades,
    }


def get_backtest(db: Session, backtest_id) -> Backtest:
    backtest = BacktestRepository(db).get(backtest_id)
    if backtest is None:
        raise NotFoundError(f"Backtest {backtest_id} not found")
    return backtest


def list_backtests(db: Session) -> list[Backtest]:
    return BacktestRepository(db).list()
