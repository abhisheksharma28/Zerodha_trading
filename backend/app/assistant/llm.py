"""Provider-agnostic LLM call for the research assistant.

Switch with ``ASSISTANT_PROVIDER``:

* ``openai``   - any OpenAI-compatible ``/chat/completions`` endpoint. Defaults
                 to Groq (free tier, no card): set ``ASSISTANT_OPENAI_API_KEY``
                 from https://console.groq.com/keys. Point the base URL at
                 OpenRouter / OpenAI / a local vLLM to use those instead.
* ``gemini``   - Google Gemini free tier: ``GEMINI_API_KEY`` from
                 https://aistudio.google.com/apikey.
* ``ollama``   - a local Ollama server (``ollama serve`` + ``ollama pull ...``).
                 No key, fully offline; must be running.
* ``anthropic``- Claude (paid): ``ANTHROPIC_API_KEY``.

All calls go over httpx (no SDKs). Non-streaming.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_ANTHROPIC_VERSION = "2023-06-01"
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class AssistantNotConfigured(RuntimeError):
    """The active provider has no key / endpoint configured."""


class AssistantError(RuntimeError):
    """The upstream LLM call failed."""


def _provider(settings: Settings) -> str:
    return (settings.assistant_provider or "openai").strip().lower()


def configured(settings: Settings) -> tuple[bool, str | None, str]:
    """(ok, reason_if_not_ok, model_label) for the active provider."""
    p = _provider(settings)
    if p == "anthropic":
        ok = bool(settings.anthropic_api_key)
        return ok, None if ok else "Set ANTHROPIC_API_KEY.", settings.anthropic_model
    if p == "openai":
        ok = bool(settings.assistant_openai_api_key)
        host = settings.assistant_openai_base_url
        hint = ("Set ASSISTANT_OPENAI_API_KEY — a free key from "
                "https://console.groq.com/keys works with the default endpoint.")
        return ok, None if ok else hint, f"{settings.assistant_openai_model} @ {host}"
    if p == "gemini":
        ok = bool(settings.gemini_api_key)
        return ok, None if ok else "Set GEMINI_API_KEY (free at https://aistudio.google.com/apikey).", settings.gemini_model
    if p == "ollama":
        return True, None, f"{settings.ollama_model} (local Ollama — must be running)"
    return False, f"Unknown ASSISTANT_PROVIDER '{p}'. Use openai | gemini | ollama | anthropic.", ""


def is_configured(settings: Settings) -> bool:
    return configured(settings)[0]


def complete(
    settings: Settings, *, system: str, messages: list[dict[str, Any]],
    max_tokens: int | None = None,
) -> str:
    p = _provider(settings)
    mt = max_tokens or settings.assistant_max_tokens
    ok, reason, _ = configured(settings)
    if not ok:
        raise AssistantNotConfigured(reason or "assistant provider not configured")
    try:
        if p == "anthropic":
            return _anthropic(settings, system, messages, mt)
        if p == "openai":
            return _openai(settings, system, messages, mt)
        if p == "gemini":
            return _gemini(settings, system, messages, mt)
        if p == "ollama":
            return _ollama(settings, system, messages, mt)
    except httpx.HTTPError as exc:
        raise AssistantError(f"could not reach the {p} endpoint: {exc}") from exc
    raise AssistantError(f"unknown provider '{p}'")


# --- adapters --------------------------------------------------------------

def _post(url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
    resp = httpx.post(url, headers=headers, json=body, timeout=_TIMEOUT)
    if resp.status_code != 200:
        snippet = resp.text[:600]
        logger.warning("assistant_upstream_error", url=url, status=resp.status_code, body=snippet)
        raise AssistantError(f"provider returned {resp.status_code}: {snippet}")
    return resp.json()


def _anthropic(s: Settings, system: str, msgs: list[dict[str, Any]], mt: int) -> str:
    data = _post(
        f"{s.anthropic_base_url.rstrip('/')}/v1/messages",
        {"x-api-key": s.anthropic_api_key, "anthropic-version": _ANTHROPIC_VERSION,
         "content-type": "application/json"},
        {"model": s.anthropic_model, "max_tokens": mt, "system": system, "messages": msgs},
    )
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return _need(text)


def _openai(s: Settings, system: str, msgs: list[dict[str, Any]], mt: int) -> str:
    data = _post(
        f"{s.assistant_openai_base_url.rstrip('/')}/chat/completions",
        {"Authorization": f"Bearer {s.assistant_openai_api_key}", "content-type": "application/json"},
        {"model": s.assistant_openai_model, "max_tokens": mt,
         "messages": [{"role": "system", "content": system}, *msgs]},
    )
    choices = data.get("choices") or [{}]
    return _need((choices[0].get("message") or {}).get("content", ""))


def _gemini(s: Settings, system: str, msgs: list[dict[str, Any]], mt: int) -> str:
    contents = [
        {"role": "model" if m.get("role") == "assistant" else "user",
         "parts": [{"text": str(m.get("content", ""))}]}
        for m in msgs
    ]
    data = _post(
        f"{s.gemini_base_url.rstrip('/')}/v1beta/models/{s.gemini_model}:generateContent"
        f"?key={s.gemini_api_key}",
        {"content-type": "application/json"},
        {"system_instruction": {"parts": [{"text": system}]},
         "contents": contents, "generationConfig": {"maxOutputTokens": mt}},
    )
    cands = data.get("candidates") or [{}]
    parts = (cands[0].get("content") or {}).get("parts") or [{}]
    return _need("".join(p.get("text", "") for p in parts))


def _ollama(s: Settings, system: str, msgs: list[dict[str, Any]], mt: int) -> str:
    data = _post(
        f"{s.ollama_base_url.rstrip('/')}/api/chat",
        {"content-type": "application/json"},
        {"model": s.ollama_model, "stream": False,
         "messages": [{"role": "system", "content": system}, *msgs],
         "options": {"num_predict": mt}},
    )
    return _need((data.get("message") or {}).get("content", ""))


def _need(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise AssistantError("empty response from the LLM provider")
    return text
