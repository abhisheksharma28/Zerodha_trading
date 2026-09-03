"""Context factors that sit *around* a single instrument's chart:

* sector strength - is this stock's sector leading or lagging today
* calendar bias   - the documented Indian monthly / turn-of-month effect
                    (Karmakar & Chakraborty, 2000)
* news signal     - a light headline heuristic from the free provider:
                    recency + a keyword lexicon, NOT sentiment analysis
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_scanner import knowledge as kb
from app.providers.fundamentals import get_fundamentals_provider
from app.services import market_data_service

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_sector_cache: tuple[float, dict[str, float], dict[str, str]] | None = None
_news_cache: dict[str, tuple[float, NewsSignal]] = {}
_SECTOR_TTL = 120.0
_NEWS_TTL = 3 * 3600.0

_POS_WORDS = {
    "upgrade", "raised", "beats", "beat", "record", "profit jumps", "profit rises",
    "order win", "bags order", "wins order", "new contract", "expansion", "buyback",
    "stake buy", "block deal buy", "dividend", "bonus", "acquisition", "partnership",
    "approval", "launch", "outperform", "target raised", "multibagger",
}
_NEG_WORDS = {
    "downgrade", "cut to", "misses", "miss", "profit falls", "loss widens", "fraud",
    "probe", "raid", "sebi", "penalty", "fine", "resigns", "resignation", "cfo exit",
    "ceo exit", "auditor", "default", "insolvency", "nclt", "pledge", "stake sale",
    "block deal sell", "downtrend", "recall", "ban", "lawsuit", "warning", "cut rating",
}


@dataclass
class NewsSignal:
    score: float          # -1..+1
    headlines: list[dict]
    note: str


def _sector_maps(db: Session, settings: Settings) -> tuple[dict[str, float], dict[str, str]]:
    """(sector_lower -> percentile 0..1 of today's move,
     symbol_upper -> sector_lower) - one market_overview call, cached."""
    global _sector_cache
    now = time.monotonic()
    if _sector_cache and now - _sector_cache[0] < _SECTOR_TTL:
        return _sector_cache[1], _sector_cache[2]
    pmap: dict[str, float] = {}
    smap: dict[str, str] = {}
    try:
        ov = market_data_service.market_overview(db, settings, universe="nifty200")
        rows = ov.get("sectors") or []
        if rows:
            ranked = sorted(rows, key=lambda r: r.get("avg_change_pct", 0.0))
            for i, r in enumerate(ranked):
                pmap[str(r["sector"]).strip().lower()] = i / max(1, len(ranked) - 1)
        for h in ov.get("heatmap") or []:
            sym, sec = h.get("symbol"), h.get("sector")
            if sym and sec:
                smap[str(sym).strip().upper()] = str(sec).strip().lower()
    except Exception as exc:  # noqa: BLE001
        logger.info("scanner_sector_map_failed", error=str(exc))
    _sector_cache = (now, pmap, smap)
    return pmap, smap


def _sector_map(db: Session, settings: Settings) -> dict[str, float]:
    return _sector_maps(db, settings)[0]


def _nudge_from_pct(pct: float, sector: str) -> tuple[float, str]:
    lead = float(kb.get("sector", "lead_percentile", default=0.75))
    lag = float(kb.get("sector", "lag_percentile", default=0.25))
    mag = float(kb.get("sector", "nudge", default=0.6))
    if pct >= lead:
        return mag, f"{sector} sector is leading the market today"
    if pct <= lag:
        return -mag, f"{sector} sector is lagging the market today"
    return 0.0, f"{sector} sector is mid-pack"


def sector_strength(db: Session, settings: Settings, sector: str | None) -> tuple[float, str] | None:
    """(-1..+1 nudge, reason) from where a named sector sits today."""
    if not sector:
        return None
    pct = _sector_map(db, settings).get(sector.strip().lower())
    if pct is None:
        return None
    return _nudge_from_pct(pct, sector.strip().lower())


def sector_nudge_for(
    db: Session, settings: Settings, symbol: str, *, fallback_sector: str | None = None
) -> tuple[float, str] | None:
    """Same as :func:`sector_strength` but resolves the stock's sector from
    the market-overview heat-map first, falling back to ``fallback_sector``."""
    pmap, smap = _sector_maps(db, settings)
    sector = smap.get(symbol.strip().upper()) or (fallback_sector or "").strip().lower() or None
    if not sector:
        return None
    pct = pmap.get(sector)
    if pct is None:
        return None
    return _nudge_from_pct(pct, sector)


def _trading_day_of_month(now: datetime) -> tuple[int, int]:
    """(approx trading day index in the month, approx trading days left).
    Weekends only - good enough for the calendar nudge."""
    d = now.date()
    first = d.replace(day=1)
    tdays = 0
    cur = first
    idx = 0
    while cur.month == d.month:
        if cur.weekday() < 5:
            tdays += 1
            if cur <= d:
                idx = tdays
        cur = cur.fromordinal(cur.toordinal() + 1)
    return idx, tdays - idx


def calendar_bias(now: datetime | None = None) -> tuple[float, str]:
    """Indian monthly / turn-of-month effect: long-favouring near the turn
    and in the first half, mildly negative deep in the second half."""
    now = now or datetime.now(IST)
    idx, left = _trading_day_of_month(now)
    c = kb.get("calendar", default={})
    if left <= 2 or idx <= 2:
        return float(c.get("turn_of_month", 0.7)), "turn-of-month window (historically higher mean returns)"
    if idx <= 8:
        return float(c.get("first_half", 0.35)), "first half of the month (historically firmer)"
    if idx >= 14:
        return float(c.get("deep_second_half", -0.3)), "deep second half of the month (historically softer)"
    return 0.0, ""


def news_signal(settings: Settings, symbol: str) -> NewsSignal:
    key = symbol.upper()
    hit = _news_cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _NEWS_TTL:
        return hit[1]
    sig = NewsSignal(0.0, [], "no recent headlines")
    try:
        res = get_fundamentals_provider(settings).get_news(symbol)
        items = res.data if res.available and res.data else []
        scored: list[dict] = []
        agg = 0.0
        wsum = 0.0
        nowsec = time.time()
        for it in items[:10]:
            title = (it.get("title") or "").lower()
            if not title:
                continue
            pub = it.get("published") or 0
            age_days = max(0.0, (nowsec - float(pub)) / 86400.0) if pub else 7.0
            recency = max(0.0, 1.0 - age_days / 5.0)  # 0 after ~5 days
            pos = sum(1 for w in _POS_WORDS if w in title)
            neg = sum(1 for w in _NEG_WORDS if w in title)
            s = (pos - neg)
            if s:
                agg += s * recency
                wsum += abs(s) * recency
            scored.append({"title": it.get("title"), "publisher": it.get("publisher"),
                           "score": s, "age_days": round(age_days, 1)})
        score = max(-1.0, min(1.0, agg / wsum)) if wsum else 0.0
        note = ("headline signal (keyword + recency, not sentiment analysis)"
                if scored else "no recent headlines")
        sig = NewsSignal(round(score, 2), scored[:5], note)
    except Exception as exc:  # noqa: BLE001
        logger.info("scanner_news_failed", symbol=symbol, error=str(exc))
    _news_cache[key] = (now, sig)
    return sig


def prime_sector_maps(db: Session, settings: Settings) -> None:
    """Build the sector maps once at the start of a scan so every instrument
    reads them from cache."""
    _sector_maps(db, settings)


def clear_caches() -> None:
    global _sector_cache
    _sector_cache = None
    _news_cache.clear()
