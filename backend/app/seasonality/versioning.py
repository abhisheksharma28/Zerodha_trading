"""Model freeze / version control + point-in-time signal snapshots.

A frozen version captures the methodology string, the parameter set, and
the full report + backtest it was built from — nothing about it changes
afterwards. Each month a signal snapshot is written from the *frozen*
version's rankings and never edited; once the month completes it can be
reviewed (predicted vs actual, rank IC) without touching the signal.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.seasonality import SeasonalityModelVersion, SeasonalitySignal
from app.seasonality.backtest import _spearman
from app.seasonality.engine import METHOD, analyze
from app.seasonality.store import load as load_report

logger = get_logger(__name__)

_DEFAULT_PARAMS = {
    "edge_measure": "own (de-meaned within year)",
    "min_years": 3,
    "horizons": ["max", "20y", "15y", "10y", "5y", "3y"],
    "fdr": "benjamini-hochberg q<0.10",
    "bootstrap_iters": 10_000,
    "backtest_strategy": "E_long_top3_short_bottom3",
    "long_cost_bps": 30.0,
    "short_cost_bps": 60.0,
    "universe": "18 NSE sectoral indices",
}


def _methodology_hash(params: dict[str, Any]) -> str:
    blob = METHOD + "\n" + json.dumps(params, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def serialize_version(v: SeasonalityModelVersion, *, full: bool = False) -> dict[str, Any]:
    out = {
        "id": str(v.id),
        "version": v.version,
        "name": v.name,
        "status": v.status,
        "frozen_at": v.frozen_at.isoformat() if v.frozen_at else None,
        "methodology_hash": v.methodology_hash[:12],
        "params": v.params,
        "verdict": v.verdict,
        "notes": v.notes,
    }
    if full:
        out["report_snapshot"] = v.report_snapshot
        out["backtest_snapshot"] = v.backtest_snapshot
    return out


def freeze(
    db: Session,
    settings: Settings,
    *,
    version: str,
    name: str,
    notes: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    version = version.strip()
    if not version:
        raise ValidationError("version is required, e.g. 'v1.0'")
    if db.execute(
        select(SeasonalityModelVersion).where(SeasonalityModelVersion.version == version)
    ).scalar_one_or_none():
        raise ValidationError(f"version {version!r} already exists")

    report = load_report()
    if not report:
        raise ValidationError(
            "no seasonality report to freeze — build it first (POST /seasonality/refresh)"
        )
    merged = {**_DEFAULT_PARAMS, **(params or {})}
    row = SeasonalityModelVersion(
        version=version,
        name=name.strip() or f"Seasonality {version}",
        status="frozen",
        frozen_at=datetime.now(UTC),
        methodology_hash=_methodology_hash(merged),
        params=merged,
        report_snapshot={k: report[k] for k in report if k not in ("backtests",)},
        backtest_snapshot=report.get("backtests", {}),
        verdict=report.get("verdict"),
        notes=notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("seasonality_model_frozen", version=version, verdict=row.verdict)
    return serialize_version(row, full=True)


def list_versions(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(SeasonalityModelVersion).order_by(SeasonalityModelVersion.frozen_at.desc())
    ).scalars().all()
    return [serialize_version(v) for v in rows]


def get_version(db: Session, version_id: str) -> SeasonalityModelVersion:
    try:
        vid = uuid.UUID(str(version_id))
    except ValueError as exc:
        raise NotFoundError("model version not found") from exc
    v = db.get(SeasonalityModelVersion, vid)
    if v is None:
        raise NotFoundError("model version not found")
    return v


def retire_version(db: Session, version_id: str) -> dict[str, Any]:
    v = get_version(db, version_id)
    v.status = "retired"
    db.commit()
    return serialize_version(v)


def _serialize_signal(s: SeasonalitySignal) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "signal_ref": s.signal_ref,
        "model_version_id": str(s.model_version_id),
        "for_month": s.for_month,
        "generated_at": s.generated_at.isoformat() if s.generated_at else None,
        "data_cutoff": s.data_cutoff,
        "rankings": s.rankings,
        "long_candidates": s.long_candidates,
        "short_candidates": s.short_candidates,
        "market_regime": s.market_regime,
        "status": s.status,
        "review": s.review,
        "reviewed_at": s.reviewed_at.isoformat() if s.reviewed_at else None,
    }


def generate_signal(
    db: Session,
    settings: Settings,
    *,
    version_id: str,
    for_month: str | None = None,
) -> dict[str, Any]:
    """Write one immutable signal snapshot for ``for_month`` (default: the
    upcoming month) from the frozen version's methodology, using data only
    through the last completed month."""
    v = get_version(db, version_id)
    if v.status != "frozen":
        raise ValidationError("only a frozen version can generate signals")

    now = datetime.now(UTC)
    if for_month:
        y, m = (int(x) for x in for_month.split("-"))
    else:
        y, m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    fm = f"{y:04d}-{m:02d}"
    ref = f"SEASONAL-{fm}-{v.version}"

    existing = db.execute(
        select(SeasonalitySignal).where(SeasonalitySignal.signal_ref == ref)
    ).scalar_one_or_none()
    if existing:
        return _serialize_signal(existing)

    # regenerate the report point-in-time (data only through the last
    # completed month). analyze() already excludes partial / future months.
    report = analyze(db, settings, bootstrap=False)
    block = report["months"].get(str(m), {})
    cutoff = report["history_span"]["latest"]

    row = SeasonalitySignal(
        model_version_id=v.id,
        signal_ref=ref,
        for_month=fm,
        generated_at=now,
        data_cutoff=cutoff or now.date().isoformat(),
        rankings=block.get("ranking", []),
        long_candidates=block.get("long_candidates", []),
        short_candidates=block.get("short_candidates", []),
        market_regime=report.get("regime_sample", {}),
        status="generated",
        frozen=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("seasonality_signal_generated", ref=ref, longs=len(row.long_candidates))
    return _serialize_signal(row)


def list_signals(db: Session, *, version_id: str | None = None) -> list[dict[str, Any]]:
    stmt = select(SeasonalitySignal).order_by(SeasonalitySignal.for_month.desc())
    if version_id:
        stmt = stmt.where(SeasonalitySignal.model_version_id == uuid.UUID(str(version_id)))
    return [_serialize_signal(s) for s in db.execute(stmt).scalars().all()]


def review_signal(db: Session, settings: Settings, *, signal_id: str) -> dict[str, Any]:
    """Once ``for_month`` is complete, score the snapshot: predicted vs
    actual sector order (rank IC) and the realised long/short spread. The
    signal itself is never modified — only the ``review`` block is filled."""
    try:
        sid = uuid.UUID(str(signal_id))
    except ValueError as exc:
        raise NotFoundError("signal not found") from exc
    s = db.get(SeasonalitySignal, sid)
    if s is None:
        raise NotFoundError("signal not found")

    y, m = (int(x) for x in s.for_month.split("-"))
    now = datetime.now(UTC)
    if (y, m) >= (now.year, now.month):
        raise ValidationError(f"{s.for_month} is not complete yet — nothing to review")

    from app.seasonality.data import load_history
    from app.seasonality.returns import build_panel

    bars_by, audits = load_history(db, settings)
    usable = [x for x, a in audits.items()
              if a.status != "FAIL" and x not in ("NIFTY 50", "INDIA VIX") and x in bars_by]
    panel = build_panel(bars_by, sectors=usable)
    actual = {sec: panel["returns"][sec][(y, m)]
              for sec in usable if (y, m) in panel["returns"].get(sec, {})}
    if len(actual) < 4:
        raise ValidationError("not enough realised returns for that month yet")

    pred_rank = {r["sector"]: r["rank"] for r in s.rankings if r["sector"] in actual}
    common = list(pred_rank)
    ic = _spearman([float(pred_rank[c]) for c in common], [-actual[c] for c in common])

    longs = [r["sector"] for r in s.long_candidates if r["sector"] in actual]
    shorts = [r["sector"] for r in s.short_candidates if r["sector"] in actual]
    long_ret = sum(actual[x] for x in longs) / len(longs) if longs else None
    short_ret = sum(actual[x] for x in shorts) / len(shorts) if shorts else None
    spread = (long_ret - short_ret) if (long_ret is not None and short_ret is not None) else None

    actual_order = sorted(actual, key=lambda x: actual[x], reverse=True)
    review = {
        "reviewed_for": s.for_month,
        "rank_ic": round(ic, 4) if ic is not None else None,
        "predicted_best": s.rankings[0]["sector"] if s.rankings else None,
        "actual_best": actual_order[0],
        "predicted_worst": s.rankings[-1]["sector"] if s.rankings else None,
        "actual_worst": actual_order[-1],
        "long_return_pct": round(long_ret, 2) if long_ret is not None else None,
        "short_return_pct": round(short_ret, 2) if short_ret is not None else None,
        "long_short_spread_pct": round(spread, 2) if spread is not None else None,
        "per_sector": {sec: round(actual[sec], 2) for sec in actual_order},
    }
    s.review = review
    s.status = "reviewed"
    s.reviewed_at = now
    db.commit()
    return _serialize_signal(s)


def health(db: Session, *, version_id: str) -> dict[str, Any]:
    """Model-health rollup for a version: mean rank IC and long/short
    spread across its reviewed signals vs the frozen backtest expectation."""
    v = get_version(db, version_id)
    signals = db.execute(
        select(SeasonalitySignal).where(
            SeasonalitySignal.model_version_id == v.id,
            SeasonalitySignal.status == "reviewed",
        )
    ).scalars().all()
    ics = [s.review["rank_ic"] for s in signals if s.review and s.review.get("rank_ic") is not None]
    spreads = [s.review["long_short_spread_pct"] for s in signals
               if s.review and s.review.get("long_short_spread_pct") is not None]

    bt = (v.backtest_snapshot.get("strategies", {})
          .get(v.params.get("backtest_strategy", "E_long_top3_short_bottom3"), {}))
    exp_ic = (bt.get("rank_ic") or {}).get("mean")
    exp_spread = (bt.get("spread") or {}).get("mean_pct")

    live_ic = sum(ics) / len(ics) if ics else None
    live_spread = sum(spreads) / len(spreads) if spreads else None

    status = "insufficient data"
    if len(ics) >= 3 and exp_ic is not None and live_ic is not None:
        if live_ic >= exp_ic * 0.7 and (live_spread or 0) >= 0:
            status = "healthy"
        elif live_ic >= 0:
            status = "degraded"
        elif live_ic >= exp_ic - 0.1:
            status = "warning"
        else:
            status = "disabled"

    return {
        "version": v.version,
        "reviewed_signals": len(signals),
        "live_rank_ic": round(live_ic, 4) if live_ic is not None else None,
        "expected_rank_ic": exp_ic,
        "live_long_short_spread_pct": round(live_spread, 3) if live_spread is not None else None,
        "expected_long_short_spread_pct": exp_spread,
        "status": status,
    }
