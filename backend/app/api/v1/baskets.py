"""Baskets API — smallcase-style portfolios of sleeves.

  GET    /baskets                 list baskets (+ cached backtest summary)
  POST   /baskets                 create a basket from a spec
  GET    /baskets/templates       starter basket definitions
  GET    /baskets/{id}            one basket, full spec + last backtest
  PUT    /baskets/{id}            edit name / weights / spec
  DELETE /baskets/{id}            delete (draft) or archive (deployed)
  POST   /baskets/{id}/backtest   walk-forward backtest, cached on the row
  GET    /baskets/{id}/deploy-preview  unit cost + affordable units
  POST   /baskets/{id}/deploy     deploy to the paper account + initial buy
  POST   /baskets/{id}/undeploy   stop (optionally liquidate)
  POST   /baskets/{id}/rebalance  rebalance now (cadence-gated unless force)
  GET    /baskets/{id}/preview    the rebalance diff, without placing anything
  GET    /baskets/{id}/status     live holdings, weights, drift, P&L
  GET    /baskets/{id}/events     rebalance history
  GET    /baskets/universes       named universes + metadata
  GET    /baskets/universes/{name}/screen  live eligibility screen for a universe
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.baskets import paper, service
from app.config import Settings, get_settings
from app.core.deps import get_db

router = APIRouter(prefix="/baskets", tags=["baskets"])


@router.get("")
def list_baskets(
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return service.list_baskets(db, include_archived=include_archived)


@router.post("")
def create_basket(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.create_basket(db, payload)


@router.get("/templates")
def starter_templates(include_internal: bool = Query(False)) -> dict[str, Any]:
    return service.starter_templates(include_internal=include_internal)


@router.get("/universes")
def universes() -> dict[str, Any]:
    return service.universe_catalog()


@router.get("/universes/{name}/screen")
def universe_screen(
    name: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.screen_universe(db, settings, name)


@router.get("/{basket_id}")
def get_basket(basket_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.serialize(service.get_basket(db, basket_id), full=True)


@router.put("/{basket_id}")
def update_basket(
    basket_id: str,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_basket(db, basket_id, payload)


@router.delete("/{basket_id}")
def delete_basket(basket_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return service.delete_basket(db, basket_id)


@router.post("/{basket_id}/backtest")
def backtest_basket(
    basket_id: str,
    years: float = Query(5.0, ge=1.0, le=12.0),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.run_backtest(db, settings, basket_id, years=years)


@router.get("/{basket_id}/deploy-preview")
def deploy_preview(
    basket_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return paper.deploy_preview(db, settings, basket_id)


@router.post("/{basket_id}/deploy")
def deploy_basket(
    basket_id: str,
    payload: dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    cap = payload.get("capital")
    if cap is None and payload.get("units") is not None:
        prev = paper.deploy_preview(db, settings, basket_id)
        cap = float(prev["unit_cost"]) * float(payload["units"])
    return paper.deploy(db, settings, basket_id, capital=cap)


@router.post("/{basket_id}/undeploy")
def undeploy_basket(
    basket_id: str,
    payload: dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return paper.undeploy(db, settings, basket_id, liquidate=bool(payload.get("liquidate")))


@router.post("/{basket_id}/rebalance")
def rebalance_basket(
    basket_id: str,
    force: bool = Query(False),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return paper.rebalance(db, settings, basket_id, force=force)


@router.get("/{basket_id}/preview")
def preview_basket(
    basket_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return paper.preview(db, settings, basket_id)


@router.get("/{basket_id}/status")
def basket_status(
    basket_id: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return paper.status(db, settings, basket_id)


@router.get("/{basket_id}/events")
def basket_events(
    basket_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    return paper.events(db, basket_id, limit=limit)
