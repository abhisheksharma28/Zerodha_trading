"""On-demand narrative deep-dive for one screened stock.

The screener's numbers (metrics + pillar breakdown) plus the fundamentals
provider's statement bundle and recent news are handed to the configured
assistant LLM, which writes eleven sections. The prompt is strict: use
ONLY the supplied facts, write "Not enough data." for anything it can't
support, and be blunt about risk. Result is cached per symbol and only
regenerated on request or when a day stale.

If no LLM provider is configured the endpoint still returns the raw
`facts` blob (so the UI can show the numbers) with ``available: False``
and the configuration hint.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant import llm
from app.config import Settings
from app.core.logging import get_logger
from app.models.screener import ScreenerDeepDive, ScreenerRating
from app.providers.fundamentals import get_fundamentals_provider

logger = get_logger(__name__)

_TTL = timedelta(hours=24)
_MAX_TOKENS = 4500  # 11 sections; input is trimmed to ~2k so this stays inside an 8k TPM cap

# statement line-items worth sending (yfinance row labels vary — match loosely)
_STATEMENT_ROWS = (
    "total revenue", "revenue", "gross profit", "operating income", "ebitda",
    "net income", "diluted eps", "basic eps",
    "total assets", "total liab", "total debt", "long term debt",
    "cash and cash equivalents", "cash cash equivalents", "stockholders equity",
    "total equity", "operating cash flow", "free cash flow", "capital expenditure",
)


def _num3(v: Any) -> Any:
    """Round big numbers to 3 significant figures to shrink the payload."""
    if not isinstance(v, (int, float)) or v != v:
        return v
    if v == 0:
        return 0
    import math

    mag = math.floor(math.log10(abs(v)))
    return round(v, max(0, 2 - mag))


def _slim_statement(rows: list[dict[str, Any]] | None, periods: int) -> list[dict[str, Any]] | None:
    if not rows:
        return None
    out: list[dict[str, Any]] = []
    for row in rows[:periods]:
        kept = {"period": row.get("period")}
        for k, v in row.items():
            if k == "period":
                continue
            kl = str(k).lower()
            if any(want in kl for want in _STATEMENT_ROWS):
                kept[k] = _num3(v)
        out.append(kept)
    return out or None

_SECTION_KEYS = [
    "business_model",
    "quarterly_results",
    "balance_sheet",
    "competitive_position",
    "management_quality",
    "technical_setup",
    "catalysts",
    "bull_case",
    "bear_case",
    "valuation",
    "verdict",
]

_SYSTEM = (
    "You are a sober, sceptical Indian equity analyst. You write for a "
    "retail investor who explicitly asked you NOT to sugar-coat. "
    "Rules you must follow exactly:\n"
    "1. Use ONLY the FACTS provided in the user message. Do not use outside "
    "knowledge, do not guess, do not invent order wins, management quotes, "
    "guidance, partnerships or policy news.\n"
    "2. If the facts do not support a section, write exactly: "
    '"Not enough data." — nothing more for that section.\n'
    "3. Give specific numbers from the facts wherever you make a claim.\n"
    "4. The bear_case must be genuinely adversarial — the strongest reason "
    "NOT to buy — not a softened footnote.\n"
    "5. valuation: compare the stock's P/E, P/B, P/S (and EV/EBITDA if "
    "present) to the peer-rank sub-scores given; a high sub-score means "
    "cheap vs peers, a low one means expensive. Say plainly whether it "
    "looks cheap, fair or expensive and on what.\n"
    "6. verdict: exactly one of BUY, HOLD or AVOID, then one paragraph. "
    "State the screener's composite score, say whether your reading of the "
    "qualitative picture agrees or disagrees with it, and if the data is "
    "thin say the verdict is low-confidence.\n"
    "7. Keep every section to at most ~110 words.\n"
    "Return ONLY a JSON object with these keys (all strings): "
    + ", ".join(_SECTION_KEYS)
    + ". No markdown, no preamble."
)


def _facts(db: Session, settings: Settings, rating: ScreenerRating) -> dict[str, Any]:
    provider = get_fundamentals_provider(settings)
    sym = rating.symbol

    def _data(res: Any) -> Any:
        return res.data if getattr(res, "available", False) else None

    profile = _data(provider.get_company_profile(sym)) or {}
    desc = str(profile.get("description") or "")[:900]
    quarterly = _slim_statement(_data(provider.get_quarterly_results(sym)), 3)
    balance = _slim_statement(_data(provider.get_balance_sheet(sym)), 2)
    cash_flow = _slim_statement(_data(provider.get_cash_flow(sym)), 2)
    shareholding = _data(provider.get_shareholding(sym))
    news_raw = _data(provider.get_news(sym))
    news = (
        [str(n.get("title")) for n in news_raw[:5] if isinstance(n, dict) and n.get("title")]
        if isinstance(news_raw, list)
        else None
    )

    m = rating.metrics or {}
    keep_m = (
        # dividend_yield is deliberately omitted — the free feed frequently
        # returns it off by 100x, and it would poison the narrative.
        "market_cap", "pe", "forward_pe", "pb", "ps", "ev_ebitda",
        "roe", "debt_equity", "current_ratio", "operating_margin", "profit_margin",
        "revenue_growth", "earnings_growth", "ltp", "week52_high", "week52_low",
        "sma50", "sma200", "ret_1m", "ret_6m",
    )

    return {
        "symbol": sym,
        "name": rating.name,
        "sector_yahoo": rating.sector,
        "profile": {
            "industry": profile.get("industry"),
            "employees": profile.get("employees"),
            "country": profile.get("country"),
            "description": desc or None,
        },
        "screener_scores": {
            "verdict": rating.verdict,
            "confidence": rating.confidence,
            "composite_0_100": rating.composite,
            "value": rating.value_score,
            "quality": rating.quality_score,
            "growth": rating.growth_score,
            "technical": rating.technical_score,
            "data_completeness_0_1": rating.data_completeness,
            "note": rating.notes,
        },
        "metrics": {k: _num3(m.get(k)) for k in keep_m if m.get(k) is not None},
        "quarterly_results_recent": quarterly,
        "balance_sheet_recent": balance,
        "cash_flow_recent": cash_flow,
        "shareholding_approx": shareholding,
        "recent_news_headlines": news,
        "as_of": rating.as_of.isoformat() if rating.as_of else None,
        "data_source_note": (
            "Free Yahoo feed — can be stale/mislabelled; no Indian promoter "
            "pledge / FII-DII / segment / order-book detail."
        ),
    }


_KEY_RE = None  # built lazily below


def _salvage_sections(text: str) -> dict[str, str] | None:
    """Tolerant fallback for a truncated / slightly malformed JSON object:
    pull each `"key": "value"` pair with a regex so the sections that did
    complete are still usable."""
    import re

    global _KEY_RE
    if _KEY_RE is None:
        keys = "|".join(re.escape(k) for k in _SECTION_KEYS)
        _KEY_RE = re.compile(
            rf'"({keys})"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL
        )
    found: dict[str, str] = {}
    for m in _KEY_RE.finditer(text):
        try:
            found[m.group(1)] = json.loads(f'"{m.group(2)}"')
        except json.JSONDecodeError:
            found[m.group(1)] = m.group(2)
    if not found:
        return None
    return {k: (found.get(k) or "Not enough data.").strip() for k in _SECTION_KEYS}


def _parse_sections(text: str) -> dict[str, str] | None:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t.lstrip("`")
        t = t.removeprefix("json").strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        try:
            obj = json.loads(t[start : end + 1])
            if isinstance(obj, dict):
                return {k: str(obj.get(k, "Not enough data.")).strip() for k in _SECTION_KEYS}
        except json.JSONDecodeError:
            pass
    return _salvage_sections(t)


def _cached(db: Session, symbol: str) -> ScreenerDeepDive | None:
    return db.execute(
        select(ScreenerDeepDive).where(ScreenerDeepDive.symbol == symbol)
    ).scalar_one_or_none()


def _shape(dd: ScreenerDeepDive, *, stale: bool) -> dict[str, Any]:
    return {
        "available": bool(dd.sections) and dd.error is None,
        "symbol": dd.symbol,
        "verdict": dd.verdict,
        "model": dd.model,
        "sections": dd.sections,
        "facts": dd.facts,
        "error": dd.error,
        "generated_at": dd.generated_at.isoformat() if dd.generated_at else None,
        "stale": stale,
    }


def generate(db: Session, settings: Settings, symbol: str, *, refresh: bool = False) -> dict[str, Any]:
    sym = symbol.strip().upper()
    rating = db.execute(
        select(ScreenerRating).where(ScreenerRating.symbol == sym)
    ).scalar_one_or_none()
    if rating is None:
        return {
            "available": False,
            "symbol": sym,
            "reason": f"{sym} is not in the latest screen — run a screener sweep first.",
        }

    existing = _cached(db, sym)
    if existing and not refresh and existing.error is None and existing.sections:
        age = datetime.now(UTC) - existing.generated_at
        if age < _TTL:
            return _shape(existing, stale=False)

    facts = _facts(db, settings, rating)

    ok, reason, model_label = llm.configured(settings)
    if not ok:
        return {
            "available": False,
            "symbol": sym,
            "reason": reason or "No assistant LLM provider is configured.",
            "hint": "Set an assistant provider in .env (ASSISTANT_PROVIDER + its key) and restart the backend.",
            "facts": facts,
        }

    user_msg = (
        "FACTS (JSON):\n"
        + json.dumps(facts, default=str, ensure_ascii=False)
        + "\n\nWrite the deep-dive now as the JSON object described in your instructions."
    )
    try:
        raw = llm.complete(
            settings,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user_msg}],
            max_tokens=_MAX_TOKENS,
        )
    except llm.AssistantNotConfigured as exc:
        return {"available": False, "symbol": sym, "reason": str(exc), "facts": facts}
    except llm.AssistantError as exc:
        logger.warning("screener_deepdive_llm_failed", symbol=sym, error=str(exc))
        _upsert(db, sym, sections={}, verdict=None, model=model_label, facts=facts, error=str(exc)[:2000])
        return {"available": False, "symbol": sym, "reason": f"The LLM call failed: {exc}", "facts": facts}

    sections = _parse_sections(raw)
    if sections is None:
        _upsert(db, sym, sections={}, verdict=None, model=model_label, facts=facts,
                error="Could not parse the model's response as JSON.")
        return {
            "available": False,
            "symbol": sym,
            "reason": "The model did not return parseable JSON.",
            "raw": raw[:6000],
            "facts": facts,
        }

    verdict = _extract_verdict(sections.get("verdict", ""))
    dd = _upsert(db, sym, sections=sections, verdict=verdict, model=model_label, facts=facts, error=None)
    return _shape(dd, stale=False)


def _extract_verdict(text: str) -> str | None:
    up = text.strip().upper()
    for v in ("AVOID", "BUY", "HOLD"):
        if up.startswith(v) or f" {v}" in up[:40]:
            return v
    return None


def _upsert(
    db: Session,
    symbol: str,
    *,
    sections: dict[str, str],
    verdict: str | None,
    model: str | None,
    facts: dict[str, Any],
    error: str | None,
) -> ScreenerDeepDive:
    dd = _cached(db, symbol)
    now = datetime.now(UTC)
    if dd is None:
        dd = ScreenerDeepDive(symbol=symbol)
        db.add(dd)
    dd.sections = sections
    dd.verdict = verdict
    dd.model = model
    dd.facts = facts
    dd.error = error
    dd.generated_at = now
    db.commit()
    db.refresh(dd)
    return dd
