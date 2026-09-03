"""Baskets API — smallcase-style portfolios of sleeves.

  GET    /baskets                 list baskets (+ cached backtest summary)
  POST   /baskets                 create a basket from a spec
  GET    /baskets/templates       starter basket definitions
  GET    /baskets/{id}            one basket, full spec + last backtest
  PUT    /baskets/{id}            edit name / weights / spec
  DELETE /baskets/{id}            delete (draft) or archive (deployed)
  POST   /baskets/{id}/backtest   walk-forward backtest, cached on the row
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.baskets import service
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
def starter_templates() -> list[dict[str, Any]]:
    return service.starter_templates()


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
