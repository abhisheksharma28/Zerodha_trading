"""Options-strategy scheduler — one pass per worker tick.

For each non-terminal OptionsStrategyInstance:

* CREATED / ENTRY_PENDING: if `now` is the configured entry weekday and time
  (default Friday 15:16 IST) and the DTE window qualifies, run `enter`
  (paper/simulation only — live is not enabled).
* ACTIVE: run `monitor` (target / stop / short-strike / time / expiry exits).

Also runs LIVE restart recovery once per process so a crash mid-position
never re-enters a duplicate. Everything is driven by the same
`evaluate_entry` / `evaluate_exit` the backtest uses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.models.enums import OptionsStrategyStatus, TradingMode
from app.models.options_strategy import OptionsStrategyInstance
from app.services import broker_service, options_strategy_service
from app.strategies.options.hni_monthly import HniConfig
from app.strategies.options.market_data import KiteMarketData

logger = get_logger(__name__)

_ACTIONABLE = {
    OptionsStrategyStatus.CREATED,
    OptionsStrategyStatus.VALIDATING,
    OptionsStrategyStatus.ENTRY_PENDING,
    OptionsStrategyStatus.ACTIVE,
}
_recovered_once = False


def run_once(db: Session, settings: Settings, *, now: datetime | None = None) -> dict[str, Any]:
    global _recovered_once
    now = now or datetime.now()

    try:
        client = broker_service.build_authenticated_client(db, settings)
        md = KiteMarketData(client)
    except BrokerNotConnectedError:
        return {"skipped": "no broker session", "entered": [], "exited": [], "monitored": 0}

    if not _recovered_once:
        try:
            recon = options_strategy_service.recover_live_instances(db, client)
            if recon:
                logger.info("hni_restart_recovery", reconciled=recon)
        finally:
            _recovered_once = True

    rows = db.execute(
        select(OptionsStrategyInstance).where(
            OptionsStrategyInstance.status.in_(list(_ACTIONABLE))
        )
    ).scalars().all()

    entered: list[str] = []
    exited: list[str] = []
    monitored = 0

    for inst in rows:
        if inst.mode == TradingMode.LIVE:
            continue  # live entry/monitoring not enabled
        cfg = HniConfig.from_dict(inst.config)
        try:
            if inst.status == OptionsStrategyStatus.ACTIVE:
                out = options_strategy_service.monitor(db, inst.id, md, now=now)
                monitored += 1
                if out.status not in _ACTIONABLE:
                    exited.append(f"{inst.basket_id}:{out.exit_reason}")
            elif _is_entry_moment(cfg, now):
                out = options_strategy_service.enter(db, inst.id, md, as_of=now)
                if out.status == OptionsStrategyStatus.ACTIVE:
                    entered.append(inst.basket_id)
        except Exception:  # noqa: BLE001 - contain to this instance
            logger.exception("hni_scheduler_instance_error", instance_id=str(inst.id))

    return {"entered": entered, "exited": exited, "monitored": monitored}


def _is_entry_moment(cfg: HniConfig, now: datetime) -> bool:
    hh, mm = cfg.entry_time
    return now.weekday() == cfg.entry_weekday_num and (now.hour, now.minute) == (hh, mm)
