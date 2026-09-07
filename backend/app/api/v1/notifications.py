"""Notifications API - Settings ▸ Notifications.

  GET  /notifications/config            toggles + Telegram connection status
  PUT  /notifications/config            edit toggles / chat id / min grade
  POST /notifications/test              send a test message now
  GET  /notifications/telegram/updates  chats that have messaged the bot (chat-id picker)
  GET  /notifications/log               recent delivery records
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.deps import get_db
from app.notifications import service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/config")
def get_config(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.config_status(db, settings)


@router.put("/config")
def put_config(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    service.set_config(db, payload)
    return service.config_status(db, settings)


@router.post("/test")
def post_test(
    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return service.send_test(db, settings)


@router.get("/telegram/updates")
def get_telegram_updates(
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return {"chats": service.detect_chats(settings)}


@router.get("/log")
def get_log(
    limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"items": service.recent(db, limit)}
