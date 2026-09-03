"""Research assistant (Claude) — long-horizon stock / sector questions
answered from the platform's own fundamentals + engine signals.

  GET  /assistant/status        is it configured (ANTHROPIC_API_KEY)?
  GET  /assistant/suggestions   placeholder prompts for the empty state
  POST /assistant/chat          {messages: [{role, content}]} -> {reply, grounding}
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.assistant import anthropic_client, service
from app.config import Settings, get_settings
from app.core.deps import get_db
from app.core.exceptions import ValidationError

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/status")
def get_status(settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return service.status(settings)


@router.get("/suggestions")
def get_suggestions() -> dict[str, Any]:
    return service.suggestions()


@router.post("/chat")
def post_chat(
    messages: list[dict[str, str]] = Body(..., embed=True),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    try:
        return service.chat(db, settings, messages)
    except anthropic_client.AssistantNotConfigured as exc:
        raise ValidationError(str(exc)) from exc
    except anthropic_client.AssistantError as exc:
        raise ValidationError(f"assistant upstream error: {exc}") from exc
