"""Gather grounding data for a research question so the assistant answers
from the platform's own numbers, not from memory.

Given the latest user message we detect NSE symbols / sector names, then
pull fundamentals + recent headlines + any live scanner idea for each, plus
today's sector performance and the engine's current top ideas. Everything
is best-effort and compact - it becomes context text in the prompt.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_data.nse_universe import NIFTY_50
from app.models.market_scanner import ScanRecommendation
from app.providers.fundamentals import get_fundamentals_provider
from app.services import market_data_service

logger = get_logger(__name__)

_NAME_BY_SYM = {s: n for s, n, _ in NIFTY_50}
_SECTOR_BY_SYM = {s: sec for s, _, sec in NIFTY_50}
_ALL_SECTORS = sorted({sec.lower() for _, _, sec in NIFTY_50})
# name -> symbol, longest names first so "bajaj finserv" beats "bajaj"
_SYM_BY_NAME = sorted(
    ((n.lower(), s) for s, n, _ in NIFTY_50),
    key=lambda kv: -len(kv[0]),
)
_STOPWORDS = {"the", "and", "for", "next", "year", "years", "which", "will", "india",
              "stock", "stocks", "sector", "sectors", "future", "good", "returns"}


def detect_symbols(text: str) -> list[str]:
    t = text.upper()
    hits: list[str] = []
    for sym in _NAME_BY_SYM:
        if re.search(rf"\b{re.escape(sym)}\b", t):
            hits.append(sym)
    low = text.lower()
    for name, sym in _SYM_BY_NAME:
        if sym not in hits and len(name) >= 4 and name in low:
            hits.append(sym)
    return hits[:6]


def detect_sectors(text: str) -> list[str]:
    low = text.lower()
    return [s for s in _ALL_SECTORS if s in low][:4]


def _fmt_metrics(m: dict[str, Any]) -> str:
    keys = [
        ("pe", "P/E"), ("pb", "P/B"), ("roe", "ROE%"), ("debtToEquity", "D/E"),
        ("currentRatio", "Current ratio"), ("operatingMargin", "Op margin"),
        ("revenueGrowth", "Rev growth%"), ("earningsGrowth", "EPS growth%"),
        ("marketCap", "Mkt cap"), ("dividendYield", "Div yield%"),
        ("week52High", "52w high"), ("week52Low", "52w low"), ("beta", "beta"),
    ]
    bits = []
    for k, label in keys:
        v = m.get(k) if isinstance(m, dict) else None
        if v is not None:
            bits.append(f"{label} {v}")
    return "; ".join(bits) or "no key metrics available"


def _symbol_block(db: Session, settings: Settings, sym: str) -> str:
    prov = get_fundamentals_provider(settings)
    name = _NAME_BY_SYM.get(sym, sym)
    lines = [f"### {sym} — {name} ({_SECTOR_BY_SYM.get(sym, 'n/a')})"]

    try:
        km = prov.get_key_metrics(sym)
        if km.available and km.data:
            lines.append("Fundamentals: " + _fmt_metrics(km.data))
        else:
            lines.append(f"Fundamentals: unavailable ({km.reason or 'no data'})")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Fundamentals: error ({exc})")

    try:
        prof = prov.get_company_profile(sym)
        if prof.available and prof.data:
            d = prof.data
            summary = str(d.get("longBusinessSummary") or d.get("summary") or "")[:400]
            if summary:
                lines.append(f"Business: {summary}")
    except Exception:  # noqa: BLE001
        pass

    try:
        news = prov.get_news(sym)
        items = news.data if news.available and news.data else []
        heads = [str(it.get("title")) for it in items[:4] if it.get("title")]
        if heads:
            lines.append("Recent headlines: " + " | ".join(heads))
    except Exception:  # noqa: BLE001
        pass

    rec = db.execute(
        select(ScanRecommendation)
        .where(ScanRecommendation.tradingsymbol == sym,
               ScanRecommendation.status == "LIVE")
        .order_by(ScanRecommendation.confidence.desc())
        .limit(1)
    ).scalar_one_or_none()
    if rec is not None:
        lines.append(
            f"Live engine idea: {rec.direction} {rec.trade_style} grade "
            f"{(rec.score_detail or {}).get('grade', '?')} conf {float(rec.confidence):.0f}, "
            f"setup '{rec.setup_type}', entry {float(rec.entry):.1f} SL {float(rec.stop_loss):.1f} "
            f"T1 {float(rec.target_1):.1f}"
        )
    return "\n".join(lines)


def build(db: Session, settings: Settings, question: str) -> dict[str, Any]:
    symbols = detect_symbols(question)
    sectors = detect_sectors(question)
    parts: list[str] = []

    if symbols:
        parts.append("## Company data (from the platform's fundamentals provider + engine)\n"
                     + "\n\n".join(_symbol_block(db, settings, s) for s in symbols))

    try:
        ov = market_data_service.market_overview(db, settings, universe="nifty200")
        secs = ov.get("sectors") or []
        if secs:
            ranked = sorted(secs, key=lambda r: r.get("avg_change_pct", 0.0), reverse=True)
            tbl = "; ".join(
                f"{r['sector']} {r.get('avg_change_pct', 0):+.2f}%" for r in ranked[:12]
            )
            parts.append(f"## Today's sector performance (NIFTY 200)\n{tbl}")
        b = ov.get("breadth")
        if b:
            parts.append(f"## Market breadth\n{b.get('advances')} advancing / "
                         f"{b.get('declines')} declining, A/D {b.get('ad_ratio')}")
    except Exception as exc:  # noqa: BLE001
        logger.info("assistant_overview_failed", error=str(exc))

    top = db.execute(
        select(ScanRecommendation)
        .where(ScanRecommendation.status == "LIVE")
        .order_by(ScanRecommendation.confidence.desc())
        .limit(8)
    ).scalars().all()
    if top:
        parts.append("## Engine's current top live ideas\n" + "\n".join(
            f"- {r.direction} {r.tradingsymbol} ({r.trade_style}), grade "
            f"{(r.score_detail or {}).get('grade', '?')}, conf {float(r.confidence):.0f}, {r.setup_type}"
            for r in top
        ))

    return {
        "symbols": symbols,
        "sectors": sectors,
        "text": "\n\n".join(parts) if parts else "(no platform data matched this question)",
    }
