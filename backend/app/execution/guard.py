"""THE single choke point that decides whether a real order is allowed to
reach Zerodha.

This module exists to satisfy requirement #14 directly: "Make it impossible
for an accidental UI action or code path to send live orders when the
strategy is not explicitly deployed in Live Trading Mode."

Design rules that make this hold (read before touching this file):

1. `assert_live_trading_authorized` re-reads the Deployment row from the
   database every single call. It NEVER trusts an in-memory flag, a cached
   object, or a value passed in by the caller — those can all be stale or
   wrong. The database row, freshly read, is the only source of truth for
   "is this deployment currently, actually, LIVE".
2. There is exactly ONE code path in the whole backend that is allowed to
   call KiteClient.place_order with real money semantics:
   app.execution.router.OrderRouter._execute_live. Every other execution
   path (backtest engine, simulation executor, paper executor) is
   structurally incapable of reaching the broker client at all — they don't
   hold a reference to it.
3. This function is called on every order-intent, not once per deployment
   lifecycle. A deployment being LIVE five minutes ago does not authorize an
   order now — pause/stop/risk-breach can and must interrupt mid-stream.
4. Any exception raised here (UnsafeModeTransitionError) must propagate all
   the way up and abort the order. It must never be caught-and-ignored,
   caught-and-retried, or caught-and-defaulted to a "safe" simulated fill
   without that fallback being an explicit, separately-reviewed decision —
   silently downgrading a rejected live order to a fake fill would hide a
   real bug from the user.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import UnsafeModeTransitionError
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, TradingMode


def assert_live_trading_authorized(db: Session, deployment_id: str) -> Deployment:
    """Raise UnsafeModeTransitionError unless `deployment_id` is, right now,
    according to the database, a RUNNING deployment explicitly in LIVE mode
    with a recorded live-trading confirmation. Returns the fresh Deployment
    row on success so the caller doesn't need a second read."""

    deployment = db.get(Deployment, deployment_id)

    if deployment is None:
        raise UnsafeModeTransitionError(f"Deployment {deployment_id} does not exist.")

    if deployment.mode != TradingMode.LIVE:
        raise UnsafeModeTransitionError(
            f"Deployment {deployment_id} is in {deployment.mode.value} mode, not LIVE. "
            "Refusing to place a real order."
        )

    if deployment.status != DeploymentStatus.RUNNING:
        raise UnsafeModeTransitionError(
            f"Deployment {deployment_id} is {deployment.status.value}, not RUNNING. "
            "Refusing to place a real order."
        )

    if not deployment.live_trading_confirmed or deployment.live_trading_confirmed_at is None:
        raise UnsafeModeTransitionError(
            f"Deployment {deployment_id} has no recorded live-trading confirmation. "
            "Refusing to place a real order. This should be structurally "
            "impossible — a LIVE deployment cannot be created without "
            "confirmation (see app.services.deployment_service.create_deployment)."
        )

    return deployment


def assert_mode_matches_deployment(deployment: Deployment, expected_mode: TradingMode) -> None:
    """Defence in depth for the paper/simulation executors too: even though
    they can never reach the broker, this catches a caller that mixed up
    which deployment/executor pairing it's using before any state is
    mutated."""
    if deployment.mode != expected_mode:
        raise UnsafeModeTransitionError(
            f"Deployment {deployment.id} is mode={deployment.mode.value}, but "
            f"the {expected_mode.value} executor was invoked for it."
        )


def now_utc() -> datetime:
    return datetime.now(UTC)
