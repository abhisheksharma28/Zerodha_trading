"""The research assistant: grounds a question in platform data, then asks
Claude for a curated multi-factor answer."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.assistant import context, llm
from app.config import Settings
from app.core.exceptions import ValidationError

_SYSTEM = """\
You are the research assistant inside a personal Indian-market (NSE) quant
platform. The user asks broad, long-horizon questions ("which stocks for the
next 5 years", "which sectors are India's future"). Answer like a careful
buy-side analyst, not a hype account.

Ground rules:
- Use the PLATFORM DATA block below as your primary evidence. When you cite a
  number, it should come from there. If the block lacks something, say so and
  reason from widely-known structural facts about the Indian economy.
- Assess each name/sector across several lenses and say which lens drove your
  view: balance sheet & financial health, earnings quality and growth,
  valuation (P/E, P/B, vs history), business moat / innovation, sector
  tailwinds, policy/regulation, and the platform engine's current signal.
- Structure a stock answer as: one-line thesis, the multi-lens assessment
  (bullets), key risks, and what would change your mind. For a sector answer:
  the structural driver, 2-4 ways to play it, and the main risk.
- Give 3-6 concrete names when asked "which stocks", with a one-line reason
  each, ranked. Prefer names that appear in the data block.
- Be explicit about uncertainty and time horizon. Never promise returns.
- Always end with: "Not investment advice. Do your own due diligence."
- Keep it tight: markdown, ~250-450 words unless the user asks for depth.
"""

_SUGGESTIONS = [
    "Which stocks could compound well over the next 5 years?",
    "Which sectors are the future of India?",
    "Is the private banking sector still a good long-term bet?",
    "Give me 5 quality small/mid-caps with strong balance sheets.",
    "How does the engine's current view line up with the fundamentals?",
    "What are the biggest risks to Indian equities over 3-5 years?",
]


def status(settings: Settings) -> dict[str, Any]:
    ok, reason, model = llm.configured(settings)
    return {
        "available": ok,
        "provider": settings.assistant_provider,
        "model": model if ok else None,
        "reason": reason,
    }


def suggestions() -> dict[str, Any]:
    return {"suggestions": _SUGGESTIONS}


def chat(db: Session, settings: Settings, messages: list[dict[str, str]]) -> dict[str, Any]:
    if not messages:
        raise ValidationError("messages is empty")
    convo = [
        {"role": "assistant" if m.get("role") == "assistant" else "user",
         "content": str(m.get("content", "")).strip()}
        for m in messages if str(m.get("content", "")).strip()
    ][-12:]
    if not convo or convo[-1]["role"] != "user":
        raise ValidationError("the last message must be from the user")

    ctx = context.build(db, settings, convo[-1]["content"])
    convo[-1] = {
        "role": "user",
        "content": f"{convo[-1]['content']}\n\n---\nPLATFORM DATA:\n{ctx['text']}",
    }

    reply = llm.complete(settings, system=_SYSTEM, messages=convo)
    return {
        "reply": reply,
        "model": llm.configured(settings)[2],
        "grounding": {"symbols": ctx["symbols"], "sectors": ctx["sectors"],
                      "had_data": ctx["text"] != "(no platform data matched this question)"},
    }
