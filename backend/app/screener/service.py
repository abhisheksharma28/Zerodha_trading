"""Read side of the Stock Screener — shapes ``screener_ratings`` for the
Insights tab (BUY / HOLD / AVOID lists + a summary + last-sweep meta)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.screener import ScreenerRating, ScreenerRun

_SORTS: dict[str, ColumnElement[Any]] = {
    "score": ScreenerRating.composite.desc(),
    "value": ScreenerRating.value_score.desc(),
    "quality": ScreenerRating.quality_score.desc(),
    "growth": ScreenerRating.growth_score.desc(),
    "technical": ScreenerRating.technical_score.desc(),
    "symbol": ScreenerRating.symbol.asc(),
}


def _row(r: ScreenerRating) -> dict[str, Any]:
    return {
        "symbol": r.symbol,
        "name": r.name,
        "sector": r.sector,
        "verdict": r.verdict,
        "confidence": r.confidence,
        "composite": r.composite,
        "scores": {
            "value": r.value_score,
            "quality": r.quality_score,
            "growth": r.growth_score,
            "technical": r.technical_score,
        },
        "data_completeness": r.data_completeness,
        "ltp": r.ltp,
        "pct_from_52w_high": r.pct_from_52w_high,
        "pct_from_52w_low": r.pct_from_52w_low,
        "notes": r.notes,
        "as_of": r.as_of.isoformat() if r.as_of else None,
    }


def _last_run(db: Session) -> dict[str, Any] | None:
    run = db.execute(
        select(ScreenerRun).order_by(ScreenerRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    return {
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "trigger": run.trigger,
        "universe_size": run.universe_size,
        "scored": run.scored,
        "buy": run.buy,
        "hold": run.hold,
        "avoid": run.avoid,
        "error": run.error,
    }


def ratings(
    db: Session,
    *,
    verdict: str | None = None,
    sector: str | None = None,
    sort: str = "score",
    limit: int = 500,
) -> dict[str, Any]:
    counts: dict[str, int] = dict(
        db.execute(
            select(ScreenerRating.verdict, func.count()).group_by(ScreenerRating.verdict)
        ).tuples().all()
    )
    total = sum(counts.values())
    if total == 0:
        return {
            "available": False,
            "reason": "No screener sweep has completed yet.",
            "summary": {"buy": 0, "hold": 0, "avoid": 0, "total": 0},
            "last_run": _last_run(db),
            "ratings": [],
        }

    q = select(ScreenerRating)
    if verdict:
        q = q.where(ScreenerRating.verdict == verdict.upper())
    if sector:
        q = q.where(ScreenerRating.sector == sector)
    q = q.order_by(_SORTS.get(sort, _SORTS["score"])).limit(limit)
    rows = db.execute(q).scalars().all()

    as_of = max((r.as_of for r in rows), default=None) if rows else None
    return {
        "available": True,
        "as_of": as_of.isoformat() if as_of else None,
        "summary": {
            "buy": counts.get("BUY", 0),
            "hold": counts.get("HOLD", 0),
            "avoid": counts.get("AVOID", 0),
            "total": total,
        },
        "sectors": sorted(
            s for (s,) in db.execute(
                select(ScreenerRating.sector).distinct().where(ScreenerRating.sector.is_not(None))
            ).all()
        ),
        "last_run": _last_run(db),
        "ratings": [_row(r) for r in rows],
    }


def rating_detail(db: Session, symbol: str) -> dict[str, Any]:
    r = db.execute(
        select(ScreenerRating).where(ScreenerRating.symbol == symbol.strip().upper())
    ).scalar_one_or_none()
    if r is None:
        return {"available": False, "reason": f"{symbol} is not in the latest screen."}
    return {
        "available": True,
        **_row(r),
        "metrics": r.metrics,
        "factors": r.factors,
    }


def status(db: Session) -> dict[str, Any]:
    counts: dict[str, int] = dict(
        db.execute(
            select(ScreenerRating.verdict, func.count()).group_by(ScreenerRating.verdict)
        ).tuples().all()
    )
    return {
        "rated": sum(counts.values()),
        "buy": counts.get("BUY", 0),
        "hold": counts.get("HOLD", 0),
        "avoid": counts.get("AVOID", 0),
        "last_run": _last_run(db),
    }
