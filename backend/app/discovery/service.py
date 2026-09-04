"""Read-side helpers for the discovery universe (coverage / tiers / gaps)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.discovery import universe as U
from app.models.discovery import (
    DiscoveryFxRate,
    DiscoveryIngestRun,
    DiscoveryInstrument,
    DiscoverySearchRun,
)


def record_search_run(
    db: Session, *, result: dict[str, Any], method: str, currency: str,
    seed: int, universe_syms: list[str], params: dict[str, Any],
    started_at: datetime, note: str | None = None,
) -> str | None:
    """Persist a search experiment for reproducibility / overfitting audit."""
    if not result.get("available"):
        return None
    surv = result.get("survivors", [])
    run = DiscoverySearchRun(
        started_at=started_at,
        finished_at=datetime.now(UTC),
        method=method,
        currency=currency,
        seed=seed,
        n_tested=int(result.get("tested", 0)),
        n_kept=int(result.get("kept", 0)),
        n_survivors=len(surv),
        universe=list(universe_syms),
        params=params,
        survivors=surv,
        top=result.get("top", []),
        pareto_frontier=result.get("pareto_frontier", []),
        note=note,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return str(run.id)


def recent_search_runs(db: Session, *, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        select(DiscoverySearchRun)
        .order_by(DiscoverySearchRun.started_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "started_at": r.started_at.isoformat(),
            "method": r.method,
            "currency": r.currency,
            "seed": r.seed,
            "n_tested": r.n_tested,
            "n_kept": r.n_kept,
            "n_survivors": r.n_survivors,
            "universe": r.universe,
            "params": r.params,
            "top_alpha": (r.top[0]["alpha_score"] if r.top else None),
            "best_survivor": (r.survivors[0] if r.survivors else None),
        }
        for r in rows
    ]


def get_search_run(db: Session, run_id: str) -> dict[str, Any] | None:
    r = db.get(DiscoverySearchRun, run_id)
    if r is None:
        return None
    return {
        "id": str(r.id),
        "started_at": r.started_at.isoformat(),
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "method": r.method,
        "currency": r.currency,
        "seed": r.seed,
        "n_tested": r.n_tested,
        "n_kept": r.n_kept,
        "n_survivors": r.n_survivors,
        "universe": r.universe,
        "params": r.params,
        "survivors": r.survivors,
        "top": r.top,
        "pareto_frontier": r.pareto_frontier,
        "note": r.note,
    }


def optimize_and_evaluate(
    db: Session, *, symbols: list[str], method: str,
    constraint_mode: str = "balanced", currency: str = "USD", cost_bps: float = 10.0,
) -> dict[str, Any]:
    """Run one optimizer over ``symbols`` and evaluate the resulting
    fixed-weight portfolio (metrics + IS/OOS + regime breakdown)."""
    from app.discovery import normalize, optimizers, portfolio

    syms = [s.strip().upper() for s in symbols if s]
    fr = normalize.returns_frame(db, syms, currency=currency)
    usable = [s for s in syms if s in fr["returns"]]
    if len(usable) < 3:
        return {"available": False,
                "reason": f"need >= 3 instruments with common history, have {len(usable)}"}
    try:
        weights = optimizers.optimize(method, usable, fr["returns"],
                                      constraint_mode=constraint_mode)
    except ValueError as exc:
        return {"available": False, "reason": str(exc)}
    ev = portfolio.evaluate(db, weights, currency=currency, cost_bps=cost_bps)
    return {"method": method, "constraint_mode": constraint_mode,
            "dropped": [s for s in syms if s not in usable], **ev}


def _ingested_symbols(db: Session, *, tiers: tuple[str, ...] = ("A", "B")) -> list[str]:
    """Symbols with ingested bars, best tiers first — the default screening
    universe (Tier A/B: >= 7 years of history)."""
    rows = db.execute(
        select(DiscoveryInstrument.symbol, DiscoveryInstrument.tier)
        .where(DiscoveryInstrument.active.is_(True), DiscoveryInstrument.n_points > 0)
        .order_by(DiscoveryInstrument.symbol)
    ).all()
    return [s for s, t in rows if t in tiers]


def universe_status(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(DiscoveryInstrument).order_by(
            DiscoveryInstrument.asset_class, DiscoveryInstrument.symbol
        )
    ).scalars().all()
    by_sym = {r.symbol: r for r in rows}

    instruments: list[dict[str, Any]] = []
    for u in U.all_instruments():
        r = by_sym.get(u.symbol)
        instruments.append({
            "symbol": u.symbol,
            "name": u.name,
            "asset_class": u.asset_class,
            "sub_class": u.sub_class,
            "region": u.region,
            "currency": u.currency,
            "ingested": r is not None,
            "tier": r.tier if r else None,
            "quality_score": float(r.quality_score) if r and r.quality_score is not None else None,
            "data_start": r.data_start.isoformat() if r and r.data_start else None,
            "data_end": r.data_end.isoformat() if r and r.data_end else None,
            "n_points": r.n_points if r else 0,
            "bar_interval": r.bar_interval if r else None,
        })

    tier_counts: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    for r in rows:
        tier_counts[r.tier or "?"] = tier_counts.get(r.tier or "?", 0) + 1
        class_counts[r.asset_class] = class_counts.get(r.asset_class, 0) + 1

    tier_a_starts = [r.data_start for r in rows if r.tier == "A" and r.data_start]
    common_start = max(tier_a_starts).isoformat() if tier_a_starts else None

    last_run = db.execute(
        select(DiscoveryIngestRun).order_by(DiscoveryIngestRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    fx_pairs = db.execute(
        select(DiscoveryFxRate.pair, func.count(DiscoveryFxRate.id))
        .group_by(DiscoveryFxRate.pair)
    ).all()

    return {
        "n_defined": len(U.all_instruments()),
        "n_ingested": len(rows),
        "by_tier": tier_counts,
        "by_asset_class": class_counts,
        "tier_a_common_start": common_start,
        "fx": dict(fx_pairs),
        "last_ingest": {
            "at": last_run.finished_at.isoformat() if last_run and last_run.finished_at else None,
            "source": last_run.source if last_run else None,
            "bar_interval": last_run.bar_interval if last_run else None,
            "n_instruments": last_run.n_instruments if last_run else 0,
            "n_bars": last_run.n_bars if last_run else 0,
        },
        "instruments": instruments,
    }
