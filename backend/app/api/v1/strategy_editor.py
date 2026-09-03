"""In-app Python strategy editor.

  GET  /strategy-editor/starter    a working starter strategy + the API cheat-sheet
  POST /strategy-editor/validate   AST check + load the class in a sandbox, report its schema
  POST /strategy-editor/backtest   run the strategy through the backtest engine in a sandbox
  POST /strategy-editor/save       persist a validated strategy as a normal Strategy row
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.strategy_editor import service

router = APIRouter(prefix="/strategy-editor", tags=["strategy-editor"])


@router.get("/starter")
def get_starter() -> dict[str, Any]:
    return service.starter()


@router.post("/validate")
def post_validate(
    source: str = Body(..., embed=True),
    entry_point: str = Body("Strategy", embed=True),
) -> dict[str, Any]:
    return service.validate(source, entry_point)


@router.post("/backtest")
def post_backtest(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return service.backtest(payload)


@router.post("/save", status_code=201)
def post_save(
    source: str = Body(..., embed=True),
    entry_point: str = Body("Strategy", embed=True),
    name: str = Body("", embed=True),
    description: str = Body("", embed=True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.save(db, source=source, entry_point=entry_point, name=name,
                        description=description)
