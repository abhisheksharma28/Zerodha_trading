"""Thin Telegram Bot API client - just the three calls this subsystem needs.

No global state, no bot framework: one ``httpx.Client`` per call, the bot
token passed in. ``send_message`` retries transient failures (429 / 5xx /
network) a few times then raises :class:`TelegramError`; the caller in
``service.dispatch_pending`` turns that into a ``failed`` outbox row.
"""

from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT = 10.0


class TelegramError(RuntimeError):
    """A Telegram Bot API call failed (after retries)."""


def _base(token: str) -> str:
    return f"{get_settings().telegram_api_base.rstrip('/')}/bot{token}"


class _Retryable(Exception):
    pass


@retry(
    retry=retry_if_exception_type(_Retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
def _post(token: str, method: str, payload: dict[str, Any]) -> Any:
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{_base(token)}/{method}", json=payload)
    except httpx.HTTPError as exc:  # network / timeout
        raise _Retryable(str(exc)) from exc
    if resp.status_code == 429 or resp.status_code >= 500:
        raise _Retryable(f"HTTP {resp.status_code}: {resp.text[:200]}")
    body = resp.json()
    if not body.get("ok"):
        # 4xx / ok:false - a real problem (bad token, bad chat id, bot
        # blocked). Not worth retrying.
        raise TelegramError(body.get("description") or f"HTTP {resp.status_code}")
    return body["result"]


def send_message(token: str, chat_id: str, text: str) -> None:
    """Send one HTML message. Raises :class:`TelegramError` on failure."""
    try:
        _post(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except _Retryable as exc:
        raise TelegramError(str(exc)) from exc


def get_me(token: str) -> dict[str, Any]:
    """Bot identity - used for the "connected as @bot" status line."""
    try:
        return _post(token, "getMe", {})
    except _Retryable as exc:
        raise TelegramError(str(exc)) from exc


def get_updates(token: str, limit: int = 20) -> list[dict[str, str]]:
    """Recent chats that have messaged the bot, newest first - so the user
    can pick their chat id in the UI without hunting for it. De-duplicated
    by chat. Best-effort: returns ``[]`` on any error."""
    try:
        result = _post(token, "getUpdates", {"limit": limit, "timeout": 0})
    except (TelegramError, _Retryable) as exc:
        logger.info("telegram_get_updates_failed", error=str(exc))
        return []
    updates: list[dict[str, Any]] = result if isinstance(result, list) else []
    seen: dict[str, dict[str, str]] = {}
    for u in reversed(updates):  # newest first
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or str(cid) in seen:
            continue
        title = chat.get("title") or " ".join(
            p for p in (chat.get("first_name"), chat.get("last_name")) if p
        ) or chat.get("username") or "(chat)"
        seen[str(cid)] = {
            "chat_id": str(cid),
            "chat_title": title,
            "chat_type": chat.get("type") or "",
            "last_text": (msg.get("text") or "")[:80],
        }
    return list(seen.values())
