"""Strategy-evaluation loop for RUNNING paper/simulation deployments.

One process, one thread, polling on a fixed interval. Each poll ("tick"):

  1. load every RUNNING / PAUSED deployment that isn't LIVE,
  2. for each RUNNING one, pull the trailing window of candles for its
     universe, feed only the bars it hasn't seen yet to its strategy
     instance, and route any resulting order intents through OrderRouter
     (which, for paper/simulation, structurally cannot reach a broker),
  3. tear down the in-memory runtime for anything no longer active.

LIVE deployments are skipped on purpose: live execution needs the broker
client wired through OrderRouter plus fill reconciliation, which is a
separate, higher-risk piece of work. A crash while evaluating one
deployment marks that deployment ERROR and is contained — it never stops
the loop or the other deployments.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.service import record as record_audit
from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.execution.guard import now_utc
from app.execution.router import OrderRouter
from app.market_data.live import LiveCandleFeed
from app.models.deployment import Deployment
from app.models.enums import (
    AuditAction,
    ChangeEntityType,
    DeploymentStatus,
    OrderStatus,
    OrderTransactionType,
    TradingMode,
)
from app.models.order import Order
from app.services import broker_service
from app.strategies.base import BaseStrategy, StrategyContext
from app.strategies.registry import load_strategy_class

logger = get_logger(__name__)

FeedFactory = Callable[[Session], LiveCandleFeed | None]


@dataclass
class DeploymentRuntime:
    strategy: BaseStrategy
    context: StrategyContext
    last_bar_ts: dict[str, Any] = field(default_factory=dict)


def _net_positions(db: Session, deployment_id) -> dict[str, int]:
    rows = db.execute(
        select(Order.tradingsymbol, Order.transaction_type, Order.quantity).where(
            Order.deployment_id == deployment_id,
            Order.status == OrderStatus.COMPLETE,
        )
    ).all()
    positions: dict[str, int] = {}
    for tradingsymbol, transaction_type, quantity in rows:
        signed = quantity if transaction_type == OrderTransactionType.BUY else -quantity
        positions[tradingsymbol] = positions.get(tradingsymbol, 0) + signed
    return positions


class DeploymentWorker:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        feed_factory: FeedFactory | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._feed_factory = feed_factory or self._default_feed_factory
        self._runtimes: dict[str, DeploymentRuntime] = {}
        self._logged_live_skip: set[str] = set()
        self._stop = False

    # --- lifecycle --------------------------------------------------------

    def request_stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        interval = self._settings.worker_poll_interval_seconds
        logger.info("worker_started", poll_interval_seconds=interval)
        while not self._stop:
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - one bad tick must not kill the loop
                logger.exception("worker_tick_failed")
            time.sleep(interval)
        logger.info("worker_stopped")

    # --- one poll -------------------------------------------------------

    def tick(self) -> None:
        db = self._session_factory()
        try:
            deployments = db.execute(
                select(Deployment).where(
                    Deployment.status.in_(
                        [DeploymentStatus.RUNNING, DeploymentStatus.PAUSED]
                    )
                )
            ).scalars().all()

            active_ids: set[str] = set()
            for deployment in deployments:
                deployment_id = str(deployment.id)
                if deployment.mode == TradingMode.LIVE:
                    if deployment_id not in self._logged_live_skip:
                        logger.warning("worker_skips_live_deployment", deployment_id=deployment_id)
                        self._logged_live_skip.add(deployment_id)
                    continue

                active_ids.add(deployment_id)
                if deployment.status == DeploymentStatus.RUNNING:
                    self._evaluate(db, deployment)

            for stale_id in list(self._runtimes):
                if stale_id not in active_ids:
                    self._teardown(stale_id)

            db.commit()
        finally:
            db.close()

        self._run_options_scheduler()

    def _run_options_scheduler(self) -> None:
        """Drive scheduled options-basket strategies (NIFTY Monthly HNI):
        enter qualifying paper instances at their entry minute, monitor
        ACTIVE ones for exits. Isolated from the bar loop above."""
        db = self._session_factory()
        try:
            from app.workers.options_scheduler import run_once

            result = run_once(db, self._settings)
            if result.get("entered") or result.get("exited"):
                logger.info("options_scheduler_tick", **{
                    k: v for k, v in result.items() if k in ("entered", "exited")
                })
        except Exception:  # noqa: BLE001 - never let this kill the worker loop
            logger.exception("options_scheduler_failed")
        finally:
            db.close()

    # --- internals ----------------------------------------------------

    def _default_feed_factory(self, db: Session) -> LiveCandleFeed | None:
        try:
            client = broker_service.build_authenticated_client(db, self._settings)
        except BrokerNotConnectedError:
            return None
        return LiveCandleFeed(client)

    def _teardown(self, deployment_id: str) -> None:
        runtime = self._runtimes.pop(deployment_id, None)
        if runtime is None:
            return
        try:
            runtime.strategy.on_stop()
        except Exception:  # noqa: BLE001
            logger.exception("worker_on_stop_failed", deployment_id=deployment_id)

    def _evaluate(self, db: Session, deployment: Deployment) -> None:
        deployment_id = str(deployment.id)
        try:
            runtime = self._runtimes.get(deployment_id)
            if runtime is None:
                runtime = self._start_runtime(db, deployment)
                self._runtimes[deployment_id] = runtime

            feed = self._feed_factory(db)
            if feed is None:
                logger.warning(
                    "worker_no_market_feed",
                    deployment_id=deployment_id,
                    detail="no active broker session; retrying next poll",
                )
                return

            interval = deployment.config.get("timeframe") or self._settings.worker_default_timeframe
            lookback = timedelta(minutes=self._settings.worker_candle_lookback_minutes)
            router = OrderRouter(db, deployment)
            orders_routed = 0

            for symbol in deployment.instrument_universe:
                bars = feed.recent_bars(symbol, interval, lookback)
                last_seen = runtime.last_bar_ts.get(symbol)
                new_bars = [
                    b for b in bars if last_seen is None or str(b.timestamp) > str(last_seen)
                ]
                # First time we ever see this instrument, anchor on the most
                # recent closed bar rather than replaying the whole window.
                if last_seen is None and new_bars:
                    new_bars = new_bars[-1:]

                for bar in new_bars:
                    runtime.context.positions = _net_positions(db, deployment.id)
                    runtime.strategy.on_bar(bar)
                    for order_request in runtime.context.drain_pending_orders():
                        result = router.submit(order_request)
                        orders_routed += 1
                        record_audit(
                            db,
                            action=AuditAction.ORDER_PLACED,
                            entity_type=ChangeEntityType.DEPLOYMENT,
                            entity_id=deployment.id,
                            mode=deployment.mode,
                            summary=(
                                f"{deployment.mode.value} order {order_request.transaction_type} "
                                f"{order_request.quantity} {order_request.tradingsymbol} "
                                f"from strategy on bar {bar.timestamp}"
                            ),
                            after={"order_id": str(result.order.id)},
                            actor="worker",
                        )
                    runtime.last_bar_ts[symbol] = bar.timestamp

            deployment.last_heartbeat_at = now_utc()
            if orders_routed:
                logger.info(
                    "worker_evaluated", deployment_id=deployment_id, orders_routed=orders_routed
                )
        except Exception as exc:  # noqa: BLE001 - contain to this deployment
            logger.exception("worker_deployment_error", deployment_id=deployment_id)
            deployment.status = DeploymentStatus.ERROR
            deployment.error_message = str(exc)[:2000]
            record_audit(
                db,
                action=AuditAction.UPDATE,
                entity_type=ChangeEntityType.DEPLOYMENT,
                entity_id=deployment.id,
                mode=deployment.mode,
                summary=f"Deployment '{deployment.name}' errored in worker: {exc}",
                before={"status": DeploymentStatus.RUNNING.value},
                after={"status": DeploymentStatus.ERROR.value},
                actor="worker",
            )
            self._runtimes.pop(deployment_id, None)

    def _start_runtime(self, db: Session, deployment: Deployment) -> DeploymentRuntime:
        from app.models.strategy import StrategyVersion

        version = db.get(StrategyVersion, deployment.strategy_version_id)
        if version is None:
            raise RuntimeError(
                f"Strategy version {deployment.strategy_version_id} for deployment "
                f"{deployment.id} not found"
            )
        strategy_cls = load_strategy_class(version.source_code, version.entry_point)
        context = StrategyContext(parameters=version.parameters or {})
        strategy = strategy_cls(context)
        strategy.on_start()
        logger.info("worker_runtime_started", deployment_id=str(deployment.id))
        return DeploymentRuntime(strategy=strategy, context=context)
