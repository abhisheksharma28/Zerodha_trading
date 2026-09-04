"""Market Insights — one briefing that pulls the whole platform together.

A single ``GET /insights`` call assembles: the index + breadth + volatility
pulse, sector rotation, what the scanner is seeing, the state of the
user's paper book, seasonality context, and a plain-English narrative —
so the user doesn't have to walk every tab.

Deterministic, template-built narrative (no LLM). SWR-cached.
"""

from app.insights.briefing import build

__all__ = ["build"]
