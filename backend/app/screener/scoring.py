"""Transparent cross-sectional scoring.

Four 0-100 pillars, each a blend of within-sector percentile ranks of
*real* metrics (falling back to a universe-wide rank when a sector has too
few names). The composite is their weighted mean over whichever pillars
had data; the verdict is a pure score cut. Nothing is generated prose and
nothing is invented — a name with thin inputs is capped at HOLD and
marked low-confidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.screener.metrics import StockMetrics

# pillar weights (renormalised over the pillars that actually scored)
_W = {"value": 0.30, "quality": 0.30, "growth": 0.20, "technical": 0.20}
_MIN_SECTOR_PEERS = 6


@dataclass
class Rating:
    symbol: str
    name: str | None
    sector: str | None
    composite: float
    value_score: float | None
    quality_score: float | None
    growth_score: float | None
    technical_score: float | None
    verdict: str
    confidence: str
    completeness: float
    factors: dict[str, Any]
    notes: str | None


def _pct_ranks(pairs: list[tuple[str, float | None]], *, lower_is_better: bool) -> dict[str, float]:
    vals = sorted((v for _s, v in pairs if v is not None))
    n = len(vals)
    if n < 2:
        return {}
    out: dict[str, float] = {}
    for sym, v in pairs:
        if v is None:
            continue
        # fraction of peers this value is >= (ascending percentile)
        below = sum(1 for x in vals if x < v)
        equal = sum(1 for x in vals if x == v)
        p = (below + 0.5 * (equal - 1)) / (n - 1) * 100.0
        p = max(0.0, min(100.0, p))
        out[sym] = 100.0 - p if lower_is_better else p
    return out


def _peer_groups(metrics: list[StockMetrics]) -> dict[str, list[StockMetrics]]:
    """symbol-key -> the peer list to rank it against (its sector, or the
    whole universe when the sector is too small / unknown)."""
    by_sector: dict[str, list[StockMetrics]] = {}
    for m in metrics:
        by_sector.setdefault(m.sector or "?", []).append(m)
    groups: dict[str, list[StockMetrics]] = {}
    for m in metrics:
        peers = by_sector.get(m.sector or "?", [])
        groups[m.symbol] = peers if len(peers) >= _MIN_SECTOR_PEERS else metrics
    return groups


def _rank_metric(
    subject: StockMetrics,
    peers: list[StockMetrics],
    attr: str,
    *,
    lower_is_better: bool,
    clip: tuple[float, float] | None = None,
) -> float | None:
    raw = getattr(subject, attr)
    if raw is None:
        return None

    def _clean(m: StockMetrics) -> float | None:
        v = getattr(m, attr)
        if v is None:
            return None
        if clip:
            v = max(clip[0], min(clip[1], v))
        return v

    pairs = [(m.symbol, _clean(m)) for m in peers]
    ranks = _pct_ranks(pairs, lower_is_better=lower_is_better)
    return ranks.get(subject.symbol)


def _blend(parts: list[tuple[str, float | None, Any]]) -> tuple[float | None, list[dict[str, Any]]]:
    got = [(name, score, raw) for name, score, raw in parts if score is not None]
    detail = [
        {"metric": name, "raw": raw, "score": round(score, 1) if score is not None else None}
        for name, score, raw in parts
    ]
    if not got:
        return None, detail
    return round(sum(s for _n, s, _r in got) / len(got), 1), detail


def score_universe(
    metrics: list[StockMetrics],
    *,
    buy_min: float,
    avoid_max: float,
    min_completeness: float,
) -> list[Rating]:
    groups = _peer_groups(metrics)
    out: list[Rating] = []

    for m in metrics:
        peers = groups[m.symbol]

        # --- Value: cheaper vs peers = higher. Loss-making P/E is not "cheap".
        pe_score = _rank_metric(m, peers, "pe", lower_is_better=True, clip=(0.0, 300.0))
        if m.pe is not None and m.pe <= 0:
            pe_score = 10.0  # negative earnings — a red flag, not a bargain
        value, value_detail = _blend([
            ("P/E", pe_score, m.pe),
            ("P/B", _rank_metric(m, peers, "pb", lower_is_better=True, clip=(0.0, 40.0)), m.pb),
            ("P/S", _rank_metric(m, peers, "ps", lower_is_better=True, clip=(0.0, 50.0)), m.ps),
            ("EV/EBITDA", _rank_metric(m, peers, "ev_ebitda", lower_is_better=True, clip=(0.0, 80.0)), m.ev_ebitda),
        ])

        # --- Quality
        quality, quality_detail = _blend([
            ("ROE %", _rank_metric(m, peers, "roe", lower_is_better=False, clip=(-50.0, 80.0)), m.roe),
            ("Op margin %", _rank_metric(m, peers, "operating_margin", lower_is_better=False, clip=(-50.0, 70.0)), m.operating_margin),
            ("Net margin %", _rank_metric(m, peers, "profit_margin", lower_is_better=False, clip=(-50.0, 60.0)), m.profit_margin),
            ("Debt/Equity", _rank_metric(m, peers, "debt_equity", lower_is_better=True, clip=(0.0, 400.0)), m.debt_equity),
            ("Current ratio", _rank_metric(m, peers, "current_ratio", lower_is_better=False, clip=(0.0, 5.0)), m.current_ratio),
        ])

        # --- Growth
        growth, growth_detail = _blend([
            ("Revenue YoY %", _rank_metric(m, peers, "revenue_growth", lower_is_better=False, clip=(-60.0, 150.0)), m.revenue_growth),
            ("Earnings YoY %", _rank_metric(m, peers, "earnings_growth", lower_is_better=False, clip=(-90.0, 200.0)), m.earnings_growth),
        ])

        # --- Technical
        tech, tech_detail = _technical(m, peers)

        pillars = {"value": value, "quality": quality, "growth": growth, "technical": tech}
        wsum = sum(_W[k] for k, v in pillars.items() if v is not None)
        composite = (
            round(sum(_W[k] * v for k, v in pillars.items() if v is not None) / wsum, 1)
            if wsum > 0
            else 0.0
        )

        completeness = m.completeness
        low_conf = completeness < min_completeness or wsum == 0
        if composite >= buy_min:
            verdict = "BUY"
        elif composite < avoid_max:
            verdict = "AVOID"
        else:
            verdict = "HOLD"
        notes = None
        if low_conf and verdict != "HOLD":
            notes = "Data too thin for a directional call — held at HOLD."
            verdict = "HOLD"
        confidence = "HIGH" if completeness >= 0.8 else "MEDIUM" if completeness >= min_completeness else "LOW"

        out.append(Rating(
            symbol=m.symbol, name=m.name, sector=m.sector,
            composite=composite,
            value_score=value, quality_score=quality,
            growth_score=growth, technical_score=tech,
            verdict=verdict, confidence=confidence, completeness=completeness,
            factors={
                "peer_basis": "sector" if len(peers) < len(metrics) else "universe",
                "peer_count": len(peers),
                "weights": _W,
                "value": value_detail,
                "quality": quality_detail,
                "growth": growth_detail,
                "technical": tech_detail,
            },
            notes=notes,
        ))
    return out


def _technical(m: StockMetrics, peers: list[StockMetrics]) -> tuple[float | None, list[dict[str, Any]]]:
    detail: list[dict[str, Any]] = []
    parts: list[float] = []

    # position in the 52-week range (0 = at the low, 100 = at the high)
    if m.ltp and m.week52_high and m.week52_low and m.week52_high > m.week52_low:
        pos = (m.ltp - m.week52_low) / (m.week52_high - m.week52_low) * 100.0
        pos = max(0.0, min(100.0, pos))
        parts.append(pos)
        detail.append({"metric": "52w range position", "raw": round(pos, 1), "score": round(pos, 1)})

    # trend: above the 50- and 200-day SMA
    trend = None
    if m.ltp and m.sma50 and m.sma200:
        trend = 0.0
        if m.ltp > m.sma50:
            trend += 35.0
        if m.ltp > m.sma200:
            trend += 40.0
        if m.sma50 > m.sma200:
            trend += 25.0
        parts.append(trend)
        detail.append({"metric": "vs 50/200 DMA", "raw": trend, "score": trend})

    # 6-month relative strength vs peers
    rs = _rank_metric(m, peers, "ret_6m", lower_is_better=False)
    if rs is not None:
        parts.append(rs)
    detail.append({"metric": "6m relative strength", "raw": m.ret_6m, "score": round(rs, 1) if rs is not None else None})

    if not parts:
        return None, detail
    return round(sum(parts) / len(parts), 1), detail
