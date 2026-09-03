"""Phase 16 — adaptive-options paper trading.

A run ticks the *same* decision engine live: analyse → (if flat) select /
size / risk-check / open a paper position → (if open) mark, run the leg
manager, adjust or close. Every decision is persisted so the Decision Log
is a full replayable history. No capital moves; fills are simulated through
the shared options cost model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adaptive_options import leg_manager, risk_engine, sizing, strategy_selector
from app.adaptive_options.backtest import _basket_cost, _short_strikes
from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.service import _analyse
from app.adaptive_options.strategy_library import build_position, get_template
from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.adaptive_options import (
    AdaptiveDecision,
    AdaptivePaperPosition,
    AdaptivePaperRun,
)

_SUPPORTED = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")
_LOT = {"NIFTY": 75, "BANKNIFTY": 35, "FINNIFTY": 65, "MIDCPNIFTY": 140}


def _leg_ns(d: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        strike=float(d["strike"]), right=d["right"], side=d["side"],
        lots=int(d["lots"]), entry_price=float(d["entry_price"]),
        signed=1 if d["side"] == "BUY" else -1,
    )


def _mark(leg_dicts: list[dict[str, Any]], snap, lot_size: int) -> float:
    pnl = 0.0
    for d in leg_dicts:
        lg = _leg_ns(d)
        row = min(snap.rows, key=lambda r: abs(r.strike - lg.strike))
        cur = (row.call_ltp if lg.right == "CE" else row.put_ltp) or 0.0
        if cur <= 0:
            cur = max(0.0, (snap.spot - lg.strike) if lg.right == "CE" else (lg.strike - snap.spot))
        pnl += lg.signed * lg.lots * lot_size * (cur - lg.entry_price)
    return pnl


# --------------------------------------------------------------------------
# lifecycle
# --------------------------------------------------------------------------

def start_run(
    db: Session, *, underlying: str = "NIFTY", preset: str = "balanced",
    overrides: dict[str, Any] | None = None, capital: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    u = underlying.strip().upper()
    if u not in _SUPPORTED:
        raise ValidationError(f"Adaptive Options supports {', '.join(_SUPPORTED)}.")
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset)
    if capital:
        cfg.account_capital = float(capital)
    run = AdaptivePaperRun(
        underlying=u, status="ACTIVE", preset=preset, config=cfg.to_dict(),
        capital=cfg.account_capital, realized_pnl=0.0, note=note,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return _run_dict(db, run)


def list_runs(db: Session) -> dict[str, Any]:
    runs = db.execute(select(AdaptivePaperRun).order_by(AdaptivePaperRun.created_at.desc())).scalars().all()
    return {"runs": [_run_summary(db, r) for r in runs]}


def get_run(db: Session, run_id: str) -> dict[str, Any]:
    return _run_dict(db, _get(db, run_id))


def stop_run(db: Session, run_id: str) -> dict[str, Any]:
    run = _get(db, run_id)
    run.status = "STOPPED"
    run.stopped_at = datetime.now(UTC)
    db.commit()
    return _run_dict(db, run)


def run_decisions(db: Session, run_id: str, *, limit: int = 200) -> dict[str, Any]:
    _get(db, run_id)
    rows = db.execute(
        select(AdaptiveDecision).where(AdaptiveDecision.run_id == run_id)
        .order_by(AdaptiveDecision.ts.desc()).limit(limit)
    ).scalars().all()
    return {"run_id": run_id, "decisions": [_dec_dict(x) for x in rows]}


# --------------------------------------------------------------------------
# the tick
# --------------------------------------------------------------------------

def tick_run(db: Session, settings: Settings, run_id: str) -> dict[str, Any]:
    run = _get(db, run_id)
    if run.status != "ACTIVE":
        return {"run_id": run_id, "skipped": f"run is {run.status}"}
    cfg = AdaptiveConfig.from_dict(dict(run.config or {}), preset=None)
    b = _analyse(db, settings, underlying=run.underlying, expiry=None, cfg=cfg, record=True)
    if isinstance(b, dict):
        run.last_tick_at = datetime.now(UTC)
        db.commit()
        return {"run_id": run_id, "available": False, "reason": b.get("reason")}

    lot_size = _LOT.get(run.underlying, 50)
    open_row = db.execute(
        select(AdaptivePaperPosition).where(
            AdaptivePaperPosition.run_id == run_id, AdaptivePaperPosition.status == "OPEN")
    ).scalar_one_or_none()

    events: list[str] = []

    if open_row is not None:
        pnl = _mark(open_row.legs, b.snap, lot_size)
        open_row.last_pnl = pnl
        open_row.mae = min(float(open_row.mae), pnl)
        open_row.mfe = max(float(open_row.mfe), pnl)
        op = leg_manager.OpenPosition(
            slug=open_row.slug, direction=open_row.direction, lots=open_row.lots,
            lot_size=lot_size, entry_spot=float(open_row.entry_spot or b.snap.spot),
            entry_net_premium=float(open_row.entry_net_premium or 0.0),
            short_call=_f(_short_of(open_row.legs, "CE", "SELL")),
            short_put=_f(_short_of(open_row.legs, "PE", "SELL")),
            long_call=_f(_short_of(open_row.legs, "CE", "BUY")),
            long_put=_f(_short_of(open_row.legs, "PE", "BUY")),
            entry_regime=open_row.entry_regime or "", entry_pcr_state=b.pcr.state,
            target_pnl=float(open_row.target_pnl or 0.0), stop_pnl=float(open_row.stop_pnl or 0.0))
        act = leg_manager.evaluate(
            op, cfg, snap=b.snap, regime=b.regime, pcr=b.pcr, intel=b.intel, vol=b.volatility,
            current_pnl=pnl, dte=b.dte)
        _log(db, run_id, "manage", b, act.action, open_row.slug, act.reason, pnl)
        exit_now = act.action in ("FULL_EXIT", "PARTIAL_EXIT", "REDUCE_QTY") or b.dte <= 1
        if not exit_now and act.action != "HOLD":
            open_row.adjustments = int(open_row.adjustments) + 1
        if exit_now:
            leg_ns = [_leg_ns(d) for d in open_row.legs]
            exit_costs = _basket_cost(_cm(), leg_ns, lot_size, opening=False)
            net = pnl - float(open_row.entry_costs or 0.0) - exit_costs
            open_row.status = "CLOSED"
            open_row.closed_at = datetime.now(UTC)
            open_row.exit_reason = act.reason if b.dte > 1 else "near expiry"
            open_row.gross_pnl = pnl
            open_row.costs = float(open_row.entry_costs or 0.0) + exit_costs
            open_row.net_pnl = net
            run.realized_pnl = float(run.realized_pnl) + net
            events.append(f"closed {open_row.slug} for ₹{net:,.0f} ({open_row.exit_reason})")
            open_row = None

    if open_row is None:
        sel = strategy_selector.rank(
            cfg, snap=b.snap, regime=b.regime, pcr=b.pcr, positioning=b.positioning,
            vol=b.volatility, expected_move=b.expected_move, confidence=b.confidence,
            intel=b.intel, data_ok=b.dq.ok, far_expiry_ok=b.far_expiry_ok)
        _log(db, run_id, "select", b, sel.action,
             sel.top.slug if sel.top else None,
             sel.no_trade_reason or (sel.top.reasons[0] if sel.top else "no fit"), None)
        if sel.action == "ENTER" and sel.top is not None:
            tmpl = get_template(sel.top.slug)
            levels = sel.top.strikes["levels"]
            pos1 = build_position(tmpl, levels, b.snap, lots=1, lot_size=lot_size,
                                  fallback_iv=b.volatility.atm_iv or 0.13)
            sz = sizing.size(pos1, cfg, dte=b.dte)
            state = risk_engine.PortfolioState(capital=float(run.capital), spot=b.snap.spot)
            rk = risk_engine.check_entry(sz, pos1, cfg, state, data_ok=b.dq.ok, dte=b.dte)
            lots = int(sz.lots * rk.scale) if rk.ok else 0
            if lots > 0:
                posN = build_position(tmpl, levels, b.snap, lots=lots, lot_size=lot_size,
                                      fallback_iv=b.volatility.atm_iv or 0.13)
                entry_costs = _basket_cost(_cm(), posN.legs, lot_size, opening=True)
                _sc, _sp, _lc, _lp = _short_strikes(posN.legs)
                row = AdaptivePaperPosition(
                    run_id=run.id, slug=tmpl.slug, direction=tmpl.direction, status="OPEN",
                    expiry=date.fromisoformat(b.snap.expiry[:10]),
                    opened_at=datetime.now(UTC), lots=lots, lot_size=lot_size,
                    legs=[lg.as_dict() for lg in posN.legs],
                    entry_spot=b.snap.spot, entry_net_premium=posN.net_premium,
                    entry_costs=entry_costs, margin=posN.margin_estimate,
                    target_pnl=abs(posN.max_profit) * 0.5,
                    stop_pnl=-(abs(posN.max_loss) if not posN.undefined_risk
                               else abs(posN.net_premium) * 2.0),
                    entry_regime=b.regime.label, entry_iv=b.volatility.atm_iv,
                    entry_confidence=b.confidence.score, adjustments=0, mae=0.0, mfe=0.0)
                db.add(row)
                events.append(f"opened {tmpl.slug} x{lots}")
            else:
                events.append(f"select→ENTER {sel.top.slug} but risk/size gave 0 lots "
                              f"({rk.blocked_reason or 'scaled to zero'})")

    run.last_tick_at = datetime.now(UTC)
    db.commit()
    return {"run_id": run_id, "available": True, "underlying": run.underlying,
            "regime": b.regime.label, "confidence": round(b.confidence.score, 1),
            "events": events, "realized_pnl": round(float(run.realized_pnl), 2)}


def tick_all(db: Session, settings: Settings) -> dict[str, Any]:
    runs = db.execute(
        select(AdaptivePaperRun.id).where(AdaptivePaperRun.status == "ACTIVE")
    ).scalars().all()
    out = []
    for rid in runs:
        try:
            out.append(tick_run(db, settings, str(rid)))
        except Exception as exc:  # noqa: BLE001 - one bad run must not stop the rest
            db.rollback()
            out.append({"run_id": str(rid), "error": str(exc)})
    return {"ticked": len(out), "results": out}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _get(db: Session, run_id: str) -> AdaptivePaperRun:
    run = db.get(AdaptivePaperRun, run_id)
    if run is None:
        raise NotFoundError(f"Adaptive paper run {run_id} not found")
    return run


def _cm():
    from app.backtesting.costs import CostConfig, CostModel
    return CostModel(CostConfig())


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _short_of(legs: list[dict[str, Any]], right: str, side: str) -> float | None:
    return next((float(d["strike"]) for d in legs if d["right"] == right and d["side"] == side), None)


def _log(db: Session, run_id: str, phase: str, b: Any, action: str,
         slug: str | None, reason: str | None, pnl: float | None) -> None:
    db.add(AdaptiveDecision(
        run_id=run_id, ts=datetime.now(UTC), phase=phase, regime=b.regime.label,
        direction=b.regime.direction, confidence=round(b.confidence.score, 2),
        action=action, slug=slug, reason=(reason or "")[:500], position_pnl=pnl))


def _dec_dict(x: AdaptiveDecision) -> dict[str, Any]:
    return {
        "ts": x.ts.isoformat(), "phase": x.phase, "regime": x.regime,
        "direction": x.direction,
        "confidence": float(x.confidence) if x.confidence is not None else None,
        "action": x.action, "strategy": x.slug, "reason": x.reason,
        "position_pnl": float(x.position_pnl) if x.position_pnl is not None else None,
    }


def _pos_dict(p: AdaptivePaperPosition) -> dict[str, Any]:
    def _n(v: Any) -> float | None:
        return None if v is None else float(v)
    return {
        "id": str(p.id), "slug": p.slug, "direction": p.direction, "status": p.status,
        "expiry": p.expiry.isoformat() if p.expiry else None,
        "opened_at": p.opened_at.isoformat(),
        "closed_at": p.closed_at.isoformat() if p.closed_at else None,
        "lots": p.lots, "lot_size": p.lot_size, "legs": p.legs,
        "entry_spot": _n(p.entry_spot), "entry_net_premium": _n(p.entry_net_premium),
        "entry_costs": _n(p.entry_costs), "margin": _n(p.margin),
        "target_pnl": _n(p.target_pnl), "stop_pnl": _n(p.stop_pnl),
        "entry_regime": p.entry_regime, "entry_iv": _n(p.entry_iv),
        "entry_confidence": _n(p.entry_confidence),
        "adjustments": p.adjustments, "mae": _n(p.mae), "mfe": _n(p.mfe),
        "last_pnl": _n(p.last_pnl), "exit_reason": p.exit_reason,
        "gross_pnl": _n(p.gross_pnl), "costs": _n(p.costs), "net_pnl": _n(p.net_pnl),
    }


def _run_summary(db: Session, r: AdaptivePaperRun) -> dict[str, Any]:
    n_open = db.execute(
        select(AdaptivePaperPosition).where(
            AdaptivePaperPosition.run_id == r.id, AdaptivePaperPosition.status == "OPEN")
    ).scalars().all()
    n_closed = db.execute(
        select(AdaptivePaperPosition).where(
            AdaptivePaperPosition.run_id == r.id, AdaptivePaperPosition.status == "CLOSED")
    ).scalars().all()
    return {
        "id": str(r.id), "underlying": r.underlying, "status": r.status, "preset": r.preset,
        "capital": float(r.capital), "realized_pnl": float(r.realized_pnl),
        "open_positions": len(n_open), "closed_positions": len(n_closed),
        "last_tick_at": r.last_tick_at.isoformat() if r.last_tick_at else None,
        "created_at": r.created_at.isoformat(),
    }


def _run_dict(db: Session, r: AdaptivePaperRun) -> dict[str, Any]:
    positions = db.execute(
        select(AdaptivePaperPosition).where(AdaptivePaperPosition.run_id == r.id)
        .order_by(AdaptivePaperPosition.opened_at.desc())
    ).scalars().all()
    recent = db.execute(
        select(AdaptiveDecision).where(AdaptiveDecision.run_id == r.id)
        .order_by(AdaptiveDecision.ts.desc()).limit(40)
    ).scalars().all()
    return {
        **_run_summary(db, r),
        "config": r.config,
        "positions": [_pos_dict(p) for p in positions],
        "recent_decisions": [_dec_dict(x) for x in recent],
    }
