"""Leaderboard orchestration: run canonical backtests, aggregate live paper
performance, rank."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.backtesting.adhoc import run_adhoc
from app.config import Settings
from app.core.logging import get_logger
from app.leaderboard import narrative, store
from app.leaderboard.config import CANONICAL, UNSUITED, canonical_for
from app.models.backtest import Backtest
from app.models.deployment import Deployment
from app.models.enums import DeploymentStatus, TradingMode
from app.models.order import Order, Trade
from app.models.strategy import Strategy, StrategyVersion
from app.schemas.deployment import DeploymentCreate
from app.services import deployment_service
from app.strategies.library import TEMPLATES, get_template
from app.strategies.library.seeding import create_strategy_from_template
from app.tuning.adopted import tuned_overrides

logger = get_logger(__name__)

_METRIC_KEYS = (
    "return_pct", "cagr_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
    "max_drawdown_pct", "win_rate_pct", "profit_factor", "total_trades",
    "avg_trade", "net_pnl", "total_costs", "turnover_ratio",
)


# --------------------------------------------------------------------------
# canonical backtests
# --------------------------------------------------------------------------

def _downsample(curve: list[list[Any]], n: int = 300) -> list[list[Any]]:
    if len(curve) <= n:
        return curve
    step = len(curve) / n
    return [curve[min(len(curve) - 1, int(i * step))] for i in range(n)] + [curve[-1]]


def run_canonical(db: Session, settings: Settings, slug: str) -> dict[str, Any]:
    cfg = canonical_for(slug)
    if cfg is None:
        raise ValueError(f"No canonical config for '{slug}' ({UNSUITED.get(slug, 'unknown')})")

    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=int(cfg.years * 365.25))
    symbols = [f"NSE:{s}" for s in cfg.universe]
    tuned = tuned_overrides(slug)

    report = run_adhoc(
        db, settings, slug=slug, symbols=symbols, timeframe=cfg.timeframe,
        start=from_dt.date().isoformat(), end=to_dt.date().isoformat(),
        preset=cfg.preset, capital=cfg.capital,
        max_gross_exposure=cfg.max_gross_exposure, max_symbols=len(symbols) + 5,
        overrides=tuned or None,
    )
    m = report.metrics
    diag = m.get("diagnostics", {})
    per_symbol = sorted(report.per_symbol, key=lambda s: s.net_pnl, reverse=True)
    payload = {
        "slug": slug,
        "config": cfg.as_dict(),
        "generated_at": report.generated_at,
        "used_symbols": report.used_symbols,
        "skipped": report.skipped,
        "metrics": {k: m.get(k) for k in _METRIC_KEYS},
        "tuned_overrides": tuned or None,
        "ruined": bool(diag.get("ruined")),
        "peak_gross_exposure_pct": diag.get("peak_gross_exposure_pct"),
        "equity_curve": _downsample(report.equity_curve),
        "top_symbols": [s.as_dict() for s in per_symbol[:8]],
        "bottom_symbols": [s.as_dict() for s in per_symbol[-5:]][::-1],
        "caveats": report.caveats,
    }
    payload["summary"] = narrative.summarize(payload)
    store.save(slug, cfg.config_hash, payload)
    return payload


def refresh_all(
    db: Session, settings: Settings, slugs: list[str] | None = None
) -> dict[str, str]:
    targets = slugs or list(CANONICAL)
    out: dict[str, str] = {}
    for slug in targets:
        if slug not in CANONICAL:
            out[slug] = "skipped: not in canonical suite"
            continue
        try:
            payload = run_canonical(db, settings, slug)
            r = payload["metrics"]
            out[slug] = (
                f"ok: return {r.get('return_pct')}%, sharpe {r.get('sharpe_ratio')}, "
                f"{r.get('total_trades')} trades"
                + (" [RUINED]" if payload["ruined"] else "")
            )
        except Exception as exc:  # noqa: BLE001 - one bad strategy must not stop the batch
            logger.warning("leaderboard_refresh_failed", slug=slug, error=str(exc))
            out[slug] = f"error: {exc}"
    return out


# --------------------------------------------------------------------------
# backtest catalog - the pre-computed showcase (read-only; refresh is
# separate). One entry per canonical template, newest cached result.
# --------------------------------------------------------------------------

def catalog(db: Session) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    newest = 0.0
    for slug, cfg in CANONICAL.items():
        blob = store.load(slug, cfg.config_hash) or store.load_any(slug)
        tmpl = get_template(slug)
        row: dict[str, Any] = {
            "slug": slug,
            "name": tmpl.NAME,
            "category": tmpl.CATEGORY,
            "universe": cfg.universe_name,
            "timeframe": cfg.timeframe,
            "years": cfg.years,
            "stale": bool(blob and blob.get("config", {}).get("config_hash") != cfg.config_hash),
        }
        if blob is None:
            row.update(status="not_run", metrics=None, summary=None,
                       equity_curve=[], cached_at=None)
        else:
            row.update(
                status="ruined" if blob.get("ruined") else "ok",
                metrics=blob.get("metrics"),
                summary=blob.get("summary") or narrative.summarize(blob),
                equity_curve=blob.get("equity_curve") or [],
                top_symbols=blob.get("top_symbols") or [],
                cached_at=blob.get("cached_at"),
                used_symbols=len(blob.get("used_symbols") or []),
                skipped=len(blob.get("skipped") or {}),
            )
            newest = max(newest, float(blob.get("cached_at") or 0))
        entries.append(row)

    total_user = db.execute(select(func.count()).select_from(Backtest)).scalar_one()
    ran = sum(1 for e in entries if e["status"] != "not_run")
    entries.sort(key=lambda e: (
        e["status"] == "not_run",
        -((e.get("metrics") or {}).get("sharpe_ratio") or -99),
    ))
    return {
        "meta": {
            "catalog_size": len(entries),
            "catalog_ran": ran,
            "user_backtests": int(total_user),
            "total_backtests": ran + int(total_user),
            "last_refresh": newest or None,
            "universe": next((c.universe_name for c in CANONICAL.values() if c.timeframe == "1d"), None),
        },
        "strategies": entries,
    }


# --------------------------------------------------------------------------
# auto-created paper deployments
# --------------------------------------------------------------------------

def _seeded_strategy(db: Session, slug: str) -> Strategy | None:
    name = get_template(slug).NAME
    return db.execute(select(Strategy).where(Strategy.name == name)).scalar_one_or_none()


def ensure_paper_deployments(db: Session) -> dict[str, str]:
    """One PAPER deployment per canonical template, created + deployed if it
    doesn't already exist. Never LIVE, never real money."""
    out: dict[str, str] = {}
    for slug in CANONICAL:
        template = get_template(slug)
        strat = _seeded_strategy(db, slug)
        if strat is None:
            strat = create_strategy_from_template(
                db, slug, preset="balanced", overrides=tuned_overrides(slug) or None,
            )
            db.flush()
        if strat.current_version_id is None:
            out[slug] = "error: seeded strategy has no version"
            continue

        existing = db.execute(
            select(Deployment)
            .join(StrategyVersion, StrategyVersion.id == Deployment.strategy_version_id)
            .where(StrategyVersion.strategy_id == strat.id)
            .where(Deployment.mode == TradingMode.PAPER)
            .where(Deployment.status != DeploymentStatus.STOPPED)
        ).scalars().first()
        if existing is not None:
            out[slug] = f"exists: {existing.id}"
            continue

        cfg = CANONICAL[slug]
        universe = [f"NSE:{s}" for s in cfg.universe[:25]]  # keep the paper feed sane
        dep = deployment_service.create_deployment(db, DeploymentCreate(
            strategy_version_id=strat.current_version_id,
            name=f"{template.NAME} — leaderboard paper",
            mode=TradingMode.PAPER,
            instrument_universe=universe,
            config={"timeframe": cfg.timeframe, "source": "leaderboard"},
        ))
        db.flush()
        try:
            deployment_service.deploy(db, dep.id)
            out[slug] = f"created + deployed: {dep.id}"
        except Exception as exc:  # noqa: BLE001
            out[slug] = f"created (deploy failed: {exc}): {dep.id}"
    db.commit()
    return out


# --------------------------------------------------------------------------
# live paper performance (reconstructed from fills)
# --------------------------------------------------------------------------

def _fifo_realized(fills: list[tuple[str, str, int, float, datetime]]) -> tuple[float, list[dict]]:
    """fills: (symbol, side BUY/SELL, qty, price, time) in time order.
    Returns (total_realised_pnl, closed_trades)."""
    lots: dict[str, deque[tuple[int, float]]] = defaultdict(deque)  # (signed_qty, price)
    realised = 0.0
    closed: list[dict] = []
    for sym, side, qty, price, ts in fills:
        signed = qty if side == "BUY" else -qty
        book = lots[sym]
        while signed != 0 and book and (book[0][0] > 0) != (signed > 0):
            lot_qty, lot_px = book[0]
            take = min(abs(lot_qty), abs(signed))
            pnl = take * (price - lot_px) * (1 if lot_qty > 0 else -1)
            realised += pnl
            closed.append({"symbol": sym, "qty": take, "pnl": round(pnl, 2),
                           "time": ts.isoformat()})
            lot_qty -= take if lot_qty > 0 else -take
            signed -= -take if signed < 0 else take
            if lot_qty == 0:
                book.popleft()
            else:
                book[0] = (lot_qty, lot_px)
        if signed != 0:
            book.append((signed, price))
    return realised, closed


def live_paper_stats(db: Session, slug: str) -> dict[str, Any] | None:
    strat = _seeded_strategy(db, slug)
    if strat is None:
        return None
    deps = db.execute(
        select(Deployment)
        .join(StrategyVersion, StrategyVersion.id == Deployment.strategy_version_id)
        .where(StrategyVersion.strategy_id == strat.id)
        .where(Deployment.mode == TradingMode.PAPER)
    ).scalars().all()
    if not deps:
        return None
    dep_ids = [d.id for d in deps]
    since = min((d.deployed_at or d.created_at) for d in deps)

    rows = db.execute(
        select(Trade.fill_price, Trade.fill_quantity, Trade.fill_time,
               Order.tradingsymbol, Order.transaction_type)
        .join(Order, Order.id == Trade.order_id)
        .where(Order.deployment_id.in_(dep_ids))
        .order_by(Trade.fill_time.asc())
    ).all()

    base = {
        "available": len(rows) > 0,
        "deployments": len(deps),
        "since": since.isoformat() if since else None,
        "days_live": (datetime.now(UTC) - since).days if since else 0,
        "fills": len(rows),
    }
    if not rows:
        return {**base, "note": "collecting — no fills yet"}

    fills = [
        (r.tradingsymbol, r.transaction_type.value.upper() if hasattr(r.transaction_type, "value")
         else str(r.transaction_type).upper(),
         int(r.fill_quantity), float(r.fill_price), r.fill_time)
        for r in rows
    ]
    realised, closed = _fifo_realized(fills)
    wins = [c for c in closed if c["pnl"] > 0]
    by_day: dict[str, float] = defaultdict(float)
    for c in closed:
        by_day[c["time"][:10]] += c["pnl"]
    daily = list(by_day.values())
    ann_sharpe = 0.0
    if len(daily) > 2:
        mean = sum(daily) / len(daily)
        var = sum((x - mean) ** 2 for x in daily) / len(daily)
        sd = math.sqrt(var)
        if sd > 0:
            ann_sharpe = (mean / sd) * math.sqrt(252)
    return {
        **base,
        "realised_pnl": round(realised, 2),
        "closed_trades": len(closed),
        "win_rate_pct": round(len(wins) / len(closed) * 100.0, 2) if closed else 0.0,
        "avg_trade": round(realised / len(closed), 2) if closed else 0.0,
        "sharpe_daily_ann": round(ann_sharpe, 3),
    }


# --------------------------------------------------------------------------
# ranking
# --------------------------------------------------------------------------

def _zblock(vals: list[float]) -> list[float]:
    if not vals:
        return []
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    sd = math.sqrt(var) or 1.0
    return [(v - mean) / sd for v in vals]


def _tuning_summary(slug: str) -> dict[str, Any] | None:
    from app.tuning.service import tuning_for  # lazy: avoids an import cycle

    t = tuning_for(slug)
    if t is None:
        return None
    return {
        "verdict": t["verdict"],
        "recommended_overrides": t.get("recommended_overrides"),
        "currently_adopted": t.get("currently_adopted"),
        "generated_at": t.get("generated_at"),
        "explanation": t.get("explanation"),
    }


def _param_sim_summary(slug: str) -> dict[str, Any] | None:
    from app.robustness.service import param_sim_for  # lazy: import cycle

    ps = param_sim_for(slug)
    if ps is None:
        return None
    return {
        "pct": ps.get("pct"),
        "n_samples": ps.get("n_samples"),
        "verdict": ps.get("verdict"),
        "ruined_fraction": ps.get("ruined_fraction"),
        "sharpe": ((ps.get("distribution") or {}).get("sharpe_ratio") or {}),
        "return_pct": ((ps.get("distribution") or {}).get("return_pct") or {}),
        "generated_at": ps.get("generated_at"),
    }


def leaderboard(db: Session, settings: Settings) -> dict[str, Any]:
    from app.robustness.service import robustness_for  # lazy: avoids an import cycle

    rows: list[dict[str, Any]] = []
    for template in TEMPLATES:
        slug = template.SLUG
        cfg = canonical_for(slug)
        bt = store.load(slug, cfg.config_hash) if cfg else None
        if bt is None and cfg is not None:
            bt = store.load_any(slug)  # stale hash: still show it, flagged
        rows.append({
            "slug": slug,
            "name": template.NAME,
            "category": template.CATEGORY,
            "composite_score": None,
            "rank": None,
            "canonical": cfg.as_dict() if cfg else None,
            "unsuited_reason": UNSUITED.get(slug),
            "backtest": (
                {
                    "metrics": bt["metrics"], "ruined": bt.get("ruined", False),
                    "generated_at": bt.get("generated_at"),
                    "stale_config": bool(cfg and bt.get("config", {}).get("config_hash")
                                         != cfg.config_hash),
                    "top_symbols": bt.get("top_symbols", []),
                }
                if bt else None
            ),
            "live": live_paper_stats(db, slug),
            "robustness": robustness_for(slug),
            "tuning": _tuning_summary(slug),
            "param_sim": _param_sim_summary(slug),
        })

    scored = [
        r for r in rows
        if r["backtest"] and not r["backtest"]["ruined"]
        and r["backtest"]["metrics"].get("total_trades", 0) > 0
    ]
    if scored:
        sh = _zblock([float(r["backtest"]["metrics"].get("sharpe_ratio") or 0) for r in scored])
        ca = _zblock([float(r["backtest"]["metrics"].get("calmar_ratio") or 0) for r in scored])
        rt = _zblock([float(r["backtest"]["metrics"].get("return_pct") or 0) for r in scored])
        dd = _zblock([float(r["backtest"]["metrics"].get("max_drawdown_pct") or 0) for r in scored])
        raw = [0.5 * sh[i] + 0.25 * ca[i] + 0.15 * rt[i] - 0.10 * dd[i] for i in range(len(scored))]
        lo, hi = min(raw), max(raw)
        span = (hi - lo) or 1.0
        for r, x in zip(scored, raw, strict=True):
            score = round(10.0 + 85.0 * (x - lo) / span, 1)
            rob = r.get("robustness") or {}
            if rob.get("robustness_score") is not None:
                # 35% of the score comes from out-of-sample robustness
                score = round(0.65 * score + 0.35 * float(rob["robustness_score"]), 1)
            live = r.get("live") or {}
            if live.get("available") and live.get("closed_trades", 0) >= 20:
                score = round(0.8 * score + 0.2 * max(0.0, min(100.0, 50 + 15 * live.get(
                    "sharpe_daily_ann", 0.0))), 1)
            r["composite_score"] = score

    def _key(r: dict) -> float:
        s = r.get("composite_score")
        return s if s is not None else -1e9

    rows.sort(key=_key, reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i if r.get("composite_score") is not None else None

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "score_method": (
            "Composite = min-max scaled blend of z-scored backtest metrics "
            "(0.50 Sharpe + 0.25 Calmar + 0.15 return − 0.10 max-drawdown) across "
            "strategies with a completed, non-ruined canonical run — then, where a "
            "robustness suite has run, 35% of the score is replaced by the "
            "out-of-sample robustness_score (Monte Carlo ruin/loss probability, "
            "walk-forward decay, parameter-overfit flag). "
            "strategies with a completed, non-ruined canonical run. Once a strategy's "
            "paper deployment has ≥20 closed trades, 20% of the score shifts to its "
            "live daily Sharpe. Sortable by any column."
        ),
        "rows": rows,
        "any_backtest_cached": any(r["backtest"] for r in rows),
    }
