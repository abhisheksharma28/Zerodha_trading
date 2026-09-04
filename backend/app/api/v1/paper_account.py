"""Paper trading account API - a discretionary demo Kite account.

  GET  /paper-account/summary                funds, margins, P&L, net worth
  GET  /paper-account/positions              open (or all) positions, marked live
  GET  /paper-account/holdings               delivered equity, marked live
  GET  /paper-account/orders                 order book
  GET  /paper-account/trades                 trade book
  GET  /paper-account/ledger                 funds statement
  GET  /paper-account/instrument/{ex}/{sym}  quote + lot/tick for the order pad
  POST /paper-account/orders                 place an order
  PUT  /paper-account/orders/{id}            modify a resting order
  DELETE /paper-account/orders/{id}          cancel a resting order
  POST /paper-account/positions/{id}/exit    square off a position at market
  POST /paper-account/funds                  add / adjust virtual cash
  POST /paper-account/reset                  wipe and reset the demo account
  GET  /paper-account/algo                   auto-trade config + live status
  PUT  /paper-account/algo                   edit the auto-trade rules
  POST /paper-account/from-idea              take one Trading Idea into the portfolio
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.paper_account import algo, engine, service, strategies
from app.paper_account.engine import OrderRequest

router = APIRouter(prefix="/paper-account", tags=["paper-account"])


@router.get("/summary")
def get_summary(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return service.summary(db, settings)


@router.get("/positions")
def get_positions(
    include_closed: bool = Query(False),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> list[dict[str, Any]]:
    return service.positions(db, settings, include_closed=include_closed)


@router.get("/holdings")
def get_holdings(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)) -> list[dict[str, Any]]:
    return service.holdings(db, settings)


@router.get("/orders")
def get_orders(status: str | None = Query(None), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service.orders(db, status=status)


@router.get("/trades")
def get_trades(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service.trades(db)


@router.get("/ledger")
def get_ledger(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service.ledger(db)


@router.get("/instrument/{exchange}/{tradingsymbol}")
def get_instrument(
    exchange: str, tradingsymbol: str,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.instrument_for_order(db, settings, exchange, tradingsymbol)


@router.post("/orders", status_code=201)
def post_order(
    exchange: str = Body(..., embed=True),
    tradingsymbol: str = Body(..., embed=True),
    side: str = Body(..., embed=True),
    quantity: int = Body(..., embed=True),
    order_type: str = Body("MARKET", embed=True),
    product: str = Body("CNC", embed=True),
    price: float | None = Body(None, embed=True),
    trigger_price: float | None = Body(None, embed=True),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    order = engine.place_order(db, settings, OrderRequest(
        exchange=exchange, tradingsymbol=tradingsymbol, side=side, quantity=quantity,
        order_type=order_type, product=product, price=price, trigger_price=trigger_price,
    ))
    return service._order_dict(order)  # noqa: SLF001


@router.put("/orders/{order_id}")
def put_order(
    order_id: str,
    price: float | None = Body(None, embed=True),
    trigger_price: float | None = Body(None, embed=True),
    quantity: int | None = Body(None, embed=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service._order_dict(  # noqa: SLF001
        engine.modify_order(db, order_id, price=price, trigger_price=trigger_price, quantity=quantity)
    )


@router.delete("/orders/{order_id}")
def delete_order(order_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service._order_dict(engine.cancel_order(db, order_id))  # noqa: SLF001


@router.post("/positions/{position_id}/exit")
def post_exit(
    position_id: str,
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service._order_dict(engine.exit_position(db, settings, position_id))  # noqa: SLF001


@router.post("/funds")
def post_funds(amount: float = Body(..., embed=True), db: Session = Depends(get_db)) -> dict[str, Any]:
    engine.add_funds(db, amount)
    return service.summary(db, get_settings())


@router.post("/reset")
def post_reset(
    opening_balance: float | None = Body(None, embed=True),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    engine.reset_account(db, opening_balance=opening_balance)
    return service.summary(db, settings)


@router.post("/reconcile")
def post_reconcile(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Rebuild cash + holdings from the trade log without wiping history —
    fixes drift from the old basket-deploy race."""
    from app.paper_account.reconcile import reconcile

    result = reconcile(db)
    result["summary"] = service.summary(db, settings)
    return result


# --- auto-trade bridge (algo toggle) ----------------------------------

@router.get("/algo")
def get_algo(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return algo.status(db, settings)


@router.put("/algo")
def put_algo(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    algo.set_config(db, payload)
    return algo.status(db, settings)


@router.post("/from-idea", status_code=201)
def post_from_idea(
    recommendation_id: str = Body(..., embed=True),
    quantity: int | None = Body(None, embed=True),
    pct: float | None = Body(None, embed=True),
    product: str | None = Body(None, embed=True),
    with_stop: bool = Body(True, embed=True),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return algo.take_idea(
        db, settings, recommendation_id,
        quantity=quantity, pct=pct, product=product, with_stop=with_stop,
    )


# --- strategies deployed inside the paper account -----------------------

@router.get("/strategies")
def get_strategy_runs(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return service.strategy_runs(db)


@router.get("/strategies/templates")
def get_strategy_templates() -> list[dict[str, Any]]:
    return strategies.templates()


@router.post("/strategies", status_code=201)
def post_strategy_run(
    slug: str = Body(..., embed=True),
    name: str = Body("", embed=True),
    instruments: list[str] = Body(..., embed=True),
    timeframe: str = Body("1d", embed=True),
    product: str = Body("CNC", embed=True),
    params: dict[str, Any] | None = Body(None, embed=True),
    flatten_on_stop: bool = Body(True, embed=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = strategies.create_run(
        db, slug=slug, name=name, instruments=instruments, timeframe=timeframe,
        product=product, params=params, flatten_on_stop=flatten_on_stop,
    )
    return next((r for r in service.strategy_runs(db) if r["id"] == str(run.id)), {"id": str(run.id)})


@router.patch("/strategies/{run_id}")
def patch_strategy_run(
    run_id: str,
    status: str = Body(..., embed=True),
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    strategies.set_status(db, settings, run_id, status)
    return next((r for r in service.strategy_runs(db) if r["id"] == run_id), {"id": run_id})


@router.delete("/strategies/{run_id}", status_code=204)
def delete_strategy_run(run_id: str, db: Session = Depends(get_db)) -> None:
    strategies.delete_run(db, run_id)
