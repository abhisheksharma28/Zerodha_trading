"""Minimal Anthropic Messages API client over httpx (no SDK dependency)."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_API_VERSION = "2023-06-01"


class AssistantNotConfigured(RuntimeError):
    """No ANTHROPIC_API_KEY set."""


class AssistantError(RuntimeError):
    """The upstream call failed."""


def is_configured(settings: Settings) -> bool:
    return bool(settings.anthropic_api_key)


def complete(
    settings: Settings,
    *,
    system: str,
    messages: list[dict[str, Any]],
    max_tokens: int | None = None,
) -> str:
    """One non-streaming completion. ``messages`` are Anthropic-shaped
    ({"role": "user"|"assistant", "content": "..."})."""
    if not settings.anthropic_api_key:
        raise AssistantNotConfigured("ANTHROPIC_API_KEY is not set")

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens or settings.assistant_max_tokens,
        "system": system,
        "messages": messages,
    }
    try:
        resp = httpx.post(
            f"{settings.anthropic_base_url.rstrip('/')}/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": _API_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(90.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise AssistantError(f"could not reach Anthropic: {exc}") from exc

    if resp.status_code != 200:
        body = resp.text[:500]
        logger.warning("assistant_upstream_error", status=resp.status_code, body=body)
        raise AssistantError(f"Anthropic returned {resp.status_code}: {body}")

    data = resp.json()
    parts = [blk.get("text", "") for blk in data.get("content", []) if blk.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise AssistantError("empty response from Anthropic")
    return text
