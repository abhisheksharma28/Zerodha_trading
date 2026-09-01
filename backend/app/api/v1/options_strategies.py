"""NIFTY Monthly HNI (1:3:2 CALL ratio) — scheduled options-basket strategy.

Catalogue + instance lifecycle + a backtest endpoint. Live basket execution
is not enabled; instances are created in paper/simulation mode and driven by
the options scheduler in the worker.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import BrokerNotConnectedError, ValidationError
from app.schemas.options_strategy import (
    CreateOptionsInstance,
    OptionsBacktestRequest,
    OptionsInstanceRead,
    OptionsTemplate,
)
from app.services import broker_service, options_strategy_service
from app.strategies.options.hni_monthly import HniConfig
from app.strategies.options.market_data import (
    KiteMarketData,
    RecordedOptionData,
    SyntheticOptionData,
)

router = APIRouter(prefix="/options-strategies", tags=["options-strategies"])


def _read(inst) -> dict:
    return OptionsInstanceRead.model_validate(inst).model_dump(mode="json")


def _live_md(db: Session, settings: Settings) -> KiteMarketData:
    client = broker_service.build_authenticated_client(db, settings)
    return KiteMarketData(client)


@router.get("/template", response_model=OptionsTemplate)
def get_template():
    return options_strategy_service.template_info()


@router.get("", response_model=list[OptionsInstanceRead])
def list_instances(db: Session = Depends(get_db)):
    return [_read(i) for i in options_strategy_service.list_instances(db)]


@router.post("", response_model=OptionsInstanceRead, status_code=201)
def create_instance(payload: CreateOptionsInstance, db: Session = Depends(get_db)):
    inst = options_strategy_service.create_instance(
        db, mode=payload.mode, preset=payload.preset, overrides=payload.parameters
    )
    return _read(inst)


@router.get("/{instance_id}", response_model=OptionsInstanceRead)
def get_instance(instance_id: str, db: Session = Depends(get_db)):
    return _read(options_strategy_service._get(db, instance_id))  # noqa: SLF001


@router.post("/{instance_id}/evaluate")
def evaluate_instance(
    instance_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    """Dry-run the entry gates right now (15:16 today) and report the reason."""
    try:
        md = _live_md(db, settings)
    except BrokerNotConnectedError as exc:
        raise ValidationError(
            "Connect a Zerodha session to evaluate this strategy against the live chain."
        ) from exc
    return options_strategy_service.evaluate(db, instance_id, md)


@router.post("/{instance_id}/enter", response_model=OptionsInstanceRead)
def enter_instance(
    instance_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    """Force a paper/simulation entry now (normally the scheduler does this at
    15:16 on a qualifying Friday). Refused for live."""
    md = _live_md(db, settings)
    return _read(options_strategy_service.enter(db, instance_id, md))


@router.post("/{instance_id}/exit", response_model=OptionsInstanceRead)
def exit_instance(
    instance_id: str, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)
):
    md = _live_md(db, settings)
    return _read(options_strategy_service.manual_exit(db, instance_id, md))


@router.post("/backtest")
def backtest(payload: OptionsBacktestRequest):
    """Run the HNI backtest. With ``recorded_quotes`` a faithful
    RecordedOptionData run; otherwise a SYNTHETIC flat-vol run flagged
    ``synthetic_data: true`` — mechanics only, not evidence of an edge."""
    from app.backtesting.options_runner import run_hni_backtest

    data = payload.parameters or {}
    if "fallback_margin_per_short_lot" not in data:
        data = {**data, "fallback_margin_per_short_lot": payload.fallback_margin_per_short_lot}
    cfg_dict = {}
    from app.strategies.options.hni_monthly import PRESETS

    if payload.preset:
        cfg_dict.update(PRESETS.get(payload.preset, {}))
    cfg_dict.update(data)
    cfg = HniConfig.from_dict(cfg_dict)

    spot_path: dict[date, float] = {
        date.fromisoformat(k): float(v) for k, v in (payload.spot_path or {}).items()
    }
    md: RecordedOptionData | SyntheticOptionData
    if payload.recorded_quotes:
        quotes = {
            (d, float(s)): row
            for d, by_strike in payload.recorded_quotes.items()
            for s, row in by_strike.items()
        }
        md = RecordedOptionData(spot_path, quotes)
    elif not spot_path:
        raise ValidationError("Provide spot_path (or recorded_quotes) for the backtest.")
    else:
        md = SyntheticOptionData(spot_path, vol=payload.synthetic_vol, margin=None)
    return run_hni_backtest(cfg, md, start=payload.start, end=payload.end,
                            cost_config=payload.costs)


@router.post("/scheduler/tick")
def scheduler_tick(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """Manually run one options-scheduler pass (the worker does this on its
    own loop). Enters qualifying paper instances at 15:16 and monitors
    ACTIVE ones."""
    from app.workers.options_scheduler import run_once

    now = datetime.now()
    return run_once(db, settings, now=now)
