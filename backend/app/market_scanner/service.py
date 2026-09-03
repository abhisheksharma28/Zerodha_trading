"""Read/serve layer for the Market Scanner API."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.market_scanner import scanner
from app.market_scanner.scheduler import market_phase
from app.models.market_scanner import ScannerAlert, ScanRecommendation, ScanRun

IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def _f(v: Any) -> float | None:
    return float(v) if v is not None else None


def rec_dict(r: ScanRecommendation) -> dict[str, Any]:
    entry, sl, t1 = _f(r.entry), _f(r.stop_loss), _f(r.target_1)
    ltp = _f(r.last_ltp)
    progress = None
    if ltp is not None and entry is not None and t1 is not None and t1 != entry:
        progress = max(-1.0, min(1.5, (ltp - entry) / (t1 - entry)))
    risk_pct = None
    if entry and sl is not None:
        risk_pct = round(abs(entry - sl) / entry * 100.0, 2)
    return {
        "id": str(r.id),
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "trading_day": r.trading_day,
        "exchange": r.exchange,
        "tradingsymbol": r.tradingsymbol,
        "name": r.name,
        "segment": r.segment,
        "asset_class": r.asset_class,
        "underlying": r.underlying,
        "instrument_token": r.instrument_token,
        "horizon": r.horizon,
        "trade_style": r.trade_style,
        "direction": r.direction,
        "setup_type": r.setup_type,
        "setup_tags": r.setup_tags or [],
        "ref_price": _f(r.ref_price),
        "entry": entry,
        "entry_type": r.entry_type,
        "stop_loss": sl,
        "target_1": t1,
        "target_2": _f(r.target_2),
        "rr": _f(r.rr),
        "risk_pct": risk_pct,
        "atr": _f(r.atr),
        "confidence": _f(r.confidence),
        "grade": (r.score_detail or {}).get("grade")
        or ("A" if (r.confidence or 0) >= 74 else "B" if (r.confidence or 0) >= 58 else "C"),
        "score_detail": r.score_detail,
        "context": r.context,
        "bias_score": _f(r.bias_score),
        "pop": _f(r.pop),
        "factors": r.factors or [],
        "option_overlay": r.option_overlay,
        "hedge": r.hedge,
        "pair_id": str(r.pair_id) if r.pair_id else None,
        "fundamentals": r.fundamentals,
        "status": r.status,
        "outcome": r.outcome,
        "entered_price": _f(r.entered_price),
        "exit_price": _f(r.exit_price),
        "exit_at": r.exit_at.isoformat() if r.exit_at else None,
        "result_pct": _f(r.result_pct),
        "result_r": _f(r.result_r),
        "result_points": _f(r.result_points),
        "mfe_pct": _f(r.mfe_pct),
        "mae_pct": _f(r.mae_pct),
        "last_ltp": ltp,
        "last_checked_at": r.last_checked_at.isoformat() if r.last_checked_at else None,
        "tracking_state": r.tracking_state,
        "progress": progress,
        "disclaimer": r.disclaimer,
    }


def _last_run(db: Session) -> ScanRun | None:
    return db.execute(
        select(ScanRun).order_by(ScanRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()


def recommendations(db: Session) -> dict[str, Any]:
    day = _today_ist()
    live = list(db.execute(
        select(ScanRecommendation)
        .where(ScanRecommendation.status == "LIVE")
        .order_by(ScanRecommendation.confidence.desc())
    ).scalars().all())
    expired = list(db.execute(
        select(ScanRecommendation)
        .where(ScanRecommendation.status == "EXPIRED", ScanRecommendation.trading_day == day)
        .order_by(ScanRecommendation.exit_at.desc())
    ).scalars().all())
    run = _last_run(db)
    by_outcome: dict[str, int] = {}
    for r in expired:
        by_outcome[r.outcome or "?"] = by_outcome.get(r.outcome or "?", 0) + 1
    available = bool(run and run.data_available) or bool(live)
    paper_taken: list[str] = []
    try:
        from app.paper_account import algo as paper_algo

        paper_taken = sorted(paper_algo.taken_rec_ids(db))
    except Exception:  # noqa: BLE001 - the "in portfolio" hint is best-effort
        pass
    return {
        "available": available,
        "paper_taken": paper_taken,
        "as_of": datetime.now(UTC).isoformat(),
        "market_phase": market_phase(),
        "reason": None if available else (run.reason if run else "No scan has run yet."),
        "last_scan": {
            "at": run.finished_at.isoformat() if run and run.finished_at else None,
            "scanned": run.scanned if run else 0,
            "produced": run.produced if run else 0,
            "universe_size": run.universe_size if run else 0,
            "elapsed_ms": run.elapsed_ms if run else None,
            "trigger": run.trigger if run else None,
        } if run else None,
        "summary": {
            "live": len(live),
            "expired_today": len(expired),
            "target": by_outcome.get("TARGET", 0),
            "sl": by_outcome.get("SL", 0),
            "neutral": by_outcome.get("NEUTRAL", 0),
            "invalidated": by_outcome.get("INVALIDATED", 0),
        },
        "live": [rec_dict(r) for r in live],
        "expired_today": [rec_dict(r) for r in expired],
    }


def recommendation_detail(db: Session, rec_id: str) -> dict[str, Any] | None:
    r = db.get(ScanRecommendation, rec_id)
    return rec_dict(r) if r else None


def _stats(rows: list[ScanRecommendation]) -> dict[str, Any]:
    resolved = [r for r in rows if r.outcome in ("TARGET", "SL", "NEUTRAL")]
    wins = [r for r in resolved if r.outcome == "TARGET"]
    losses = [r for r in resolved if r.outcome == "SL"]
    rs = [float(r.result_r) for r in resolved if r.result_r is not None]
    pcts = [float(r.result_pct) for r in resolved if r.result_pct is not None]
    win_rate = round(100.0 * len(wins) / len(resolved), 1) if resolved else None
    expectancy_r = round(sum(rs) / len(rs), 3) if rs else None
    by_setup: dict[str, dict[str, int]] = {}
    for r in resolved:
        b = by_setup.setdefault(r.setup_type, {"n": 0, "win": 0})
        b["n"] += 1
        if r.outcome == "TARGET":
            b["win"] += 1
    by_horizon: dict[str, dict[str, int]] = {}
    for r in resolved:
        b = by_horizon.setdefault(r.horizon, {"n": 0, "win": 0})
        b["n"] += 1
        if r.outcome == "TARGET":
            b["win"] += 1
    return {
        "resolved": len(resolved),
        "target": len(wins),
        "sl": len(losses),
        "neutral": len([r for r in resolved if r.outcome == "NEUTRAL"]),
        "win_rate_pct": win_rate,
        "expectancy_r": expectancy_r,
        "avg_win_pct": round(sum(p for p in pcts if p > 0) / max(1, len([p for p in pcts if p > 0])), 2)
        if any(p > 0 for p in pcts) else None,
        "avg_loss_pct": round(sum(p for p in pcts if p < 0) / max(1, len([p for p in pcts if p < 0])), 2)
        if any(p < 0 for p in pcts) else None,
        "total_pct": round(sum(pcts), 2) if pcts else None,
        "by_setup": by_setup,
        "by_horizon": by_horizon,
    }


def logbook(
    db: Session, *, date_from: str | None = None, date_to: str | None = None,
    outcome: str | None = None, symbol: str | None = None, horizon: str | None = None,
    setup: str | None = None, direction: str | None = None, trade_style: str | None = None,
    page: int = 1, page_size: int = 50,
) -> dict[str, Any]:
    stmt = select(ScanRecommendation).where(ScanRecommendation.status == "EXPIRED")
    if date_from:
        stmt = stmt.where(ScanRecommendation.trading_day >= date_from)
    if date_to:
        stmt = stmt.where(ScanRecommendation.trading_day <= date_to)
    if outcome:
        stmt = stmt.where(ScanRecommendation.outcome == outcome.upper())
    if symbol:
        stmt = stmt.where(ScanRecommendation.tradingsymbol.ilike(f"%{symbol.upper()}%"))
    if horizon:
        stmt = stmt.where(ScanRecommendation.horizon == horizon.upper())
    if trade_style:
        stmt = stmt.where(ScanRecommendation.trade_style == trade_style.upper())
    if setup:
        stmt = stmt.where(ScanRecommendation.setup_type == setup)
    if direction:
        stmt = stmt.where(ScanRecommendation.direction == direction.upper())

    all_rows = list(db.execute(stmt.order_by(ScanRecommendation.exit_at.desc())).scalars().all())
    total = len(all_rows)
    start = max(0, (page - 1) * page_size)
    page_rows = all_rows[start : start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "stats": _stats(all_rows),
        "rows": [rec_dict(r) for r in page_rows],
        "setups": sorted({r.setup_type for r in all_rows}),
    }


async def trigger_scan(db: Session, settings: Settings) -> dict[str, Any]:
    out = await asyncio.to_thread(scanner.run_scan, db, settings, trigger="manual")
    return {
        "run_id": out.run_id,
        "data_available": out.data_available,
        "reason": out.reason,
        "scanned": out.scanned,
        "produced": out.produced,
        "recommendation_ids": out.recommendation_ids,
    }


def status(db: Session, settings: Settings) -> dict[str, Any]:
    run = _last_run(db)
    live_n = db.execute(
        select(func.count()).select_from(ScanRecommendation).where(ScanRecommendation.status == "LIVE")
    ).scalar_one()
    ticker: dict[str, Any] = {"state": "unknown"}
    try:
        from app.live.engine import engine_status

        ticker = engine_status()
    except Exception:  # noqa: BLE001
        pass
    return {
        "enabled": settings.market_scanner_enabled,
        "market_phase": market_phase(),
        "scan_interval_s": settings.market_scanner_scan_interval_seconds,
        "track_interval_s": settings.market_scanner_track_interval_seconds,
        "live_count": live_n,
        "last_run": {
            "at": run.finished_at.isoformat() if run and run.finished_at else None,
            "trigger": run.trigger if run else None,
            "data_available": run.data_available if run else None,
            "reason": run.reason if run else None,
            "scanned": run.scanned if run else 0,
            "produced": run.produced if run else 0,
            "elapsed_ms": run.elapsed_ms if run else None,
            "skipped_sample": dict(list((run.skipped or {}).items())[:10]) if run else {},
        } if run else None,
        "tick_feed": {
            "state": ticker.get("state"),
            "seconds_since_any_tick": (ticker.get("market_state") or {}).get("seconds_since_any_tick"),
            "stale": (ticker.get("market_state") or {}).get("stale"),
        },
    }


def alerts(db: Session, *, limit: int = 50, unread_only: bool = False) -> dict[str, Any]:
    stmt = select(ScannerAlert).order_by(ScannerAlert.created_at.desc()).limit(min(limit, 200))
    if unread_only:
        stmt = stmt.where(ScannerAlert.read_at.is_(None))
    rows = list(db.execute(stmt).scalars().all())
    unread = db.execute(
        select(func.count()).select_from(ScannerAlert).where(ScannerAlert.read_at.is_(None))
    ).scalar_one()
    return {
        "unread": unread,
        "alerts": [
            {
                "id": str(a.id),
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "kind": a.kind,
                "title": a.title,
                "body": a.body,
                "payload": a.payload,
                "read": a.read_at is not None,
                "recommendation_id": str(a.recommendation_id) if a.recommendation_id else None,
            }
            for a in rows
        ],
    }


def mark_alerts_read(db: Session, ids: list[str] | None = None) -> dict[str, Any]:
    stmt = select(ScannerAlert).where(ScannerAlert.read_at.is_(None))
    if ids:
        stmt = stmt.where(ScannerAlert.id.in_(ids))
    now = datetime.now(UTC)
    n = 0
    for a in db.execute(stmt).scalars().all():
        a.read_at = now
        n += 1
    db.commit()
    return {"marked": n}


def cleanup_stale_live(db: Session, *, older_than_days: int = 3) -> int:
    """Safety net: LIVE rows from earlier days that the tracker never closed
    (e.g. the process was down at EOD) - expire them NEUTRAL with no result."""
    cutoff = (datetime.now(IST).date() - timedelta(days=older_than_days)).isoformat()
    rows = db.execute(
        select(ScanRecommendation).where(
            ScanRecommendation.status == "LIVE", ScanRecommendation.trading_day < cutoff
        )
    ).scalars().all()
    for r in rows:
        r.status = "EXPIRED"
        r.outcome = "NEUTRAL"
        r.exit_at = datetime.now(UTC)
    db.commit()
    return len(rows)
