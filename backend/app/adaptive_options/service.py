"""Adaptive Options orchestration.

``_analyse`` runs the full analysis pipeline (Phases 1-7) once and returns
a bundle of typed reports. ``market_intelligence`` renders it as JSON;
``run_decision`` additionally runs strategy selection, sizing and the risk
engine (Phases 9-11). Backtest / paper reuse the same building blocks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.adaptive_options import (
    confidence,
    data_quality,
    expected_move,
    greeks_engine,
    leg_manager,
    pcr_engine,
    positioning,
    regime,
    risk_engine,
    sizing,
    snapshots,
    strategy_selector,
    volatility,
)
from app.adaptive_options import market_intelligence as mi_engine
from app.adaptive_options.chain_view import from_live_payload
from app.adaptive_options.config import PRESETS, AdaptiveConfig
from app.adaptive_options.types import (
    ChainQualityReport,
    ChainSnapshot,
    ConfidenceScore,
    ExpectedMove,
    GreeksReport,
    IntelReport,
    PCRState,
    PositioningReport,
    RegimeState,
    VolReport,
)
from app.backtesting.adhoc import fetch_candles
from app.config import Settings
from app.core.exceptions import ValidationError
from app.services import instrument_service, market_data_service
from app.strategies.indicators import atr, rolling_volatility

_SPOT_SYM = {
    "NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK",
    "FINNIFTY": "NSE:NIFTY FIN SERVICE", "MIDCPNIFTY": "NSE:NIFTY MIDCAP SELECT",
}
_SUPPORTED = tuple(_SPOT_SYM)


@dataclass
class AnalysisBundle:
    cfg: AdaptiveConfig
    snap: ChainSnapshot
    dq: ChainQualityReport
    dq_bar_issues: list
    intel: IntelReport
    pcr: PCRState
    positioning: PositioningReport
    volatility: VolReport
    greeks: GreeksReport
    expected_move: ExpectedMove
    confidence: ConfidenceScore
    regime: RegimeState
    dte: int
    history_len: int
    far_expiry_ok: bool
    recorded: str | None


# --------------------------------------------------------------------------
# metadata endpoints
# --------------------------------------------------------------------------

def config_presets() -> dict[str, Any]:
    return {
        "presets": {name: AdaptiveConfig.from_dict(None, preset=name).to_dict() for name in PRESETS},
        "fields": sorted(AdaptiveConfig.field_names()),
        "note": "Any field can be overridden per run; the resolved config is returned with every result.",
    }


def list_expiries(db: Session, underlying: str) -> dict[str, Any]:
    u = underlying.strip().upper()
    exps = instrument_service.expiries(db, u)
    today = date.today()
    return {
        "underlying": u,
        "expiries": [e for e in exps if date.fromisoformat(e) >= today],
        "supported_underlyings": list(_SUPPORTED),
    }


def strategy_matrix(preset: str = "balanced", overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset)
    return {"decision_matrix": strategy_selector.decision_matrix(cfg), "config_preset": cfg.risk_profile}


def data_sources() -> dict[str, Any]:
    """What historical option-chain data the backtest can actually use."""
    from datetime import date, timedelta

    from app.adaptive_options import bhavcopy, kaggle_ingest, local_history

    # cheap freshness probe for the NSE archive: yesterday's weekday
    probe = date.today() - timedelta(days=1)
    while probe.weekday() >= 5:
        probe -= timedelta(days=1)
    bhav_ok = bhavcopy.download(probe, timeout=8.0) is not None
    k_ok, k_why = kaggle_ingest.kaggle_available()

    return {
        "options": {
            "synthetic": "always available — calibrated vol surface, mechanics only.",
            "bhavcopy": "NSE F&O bhavcopy (free, EOD). UDiFF from ~2024-01, legacy format "
                        "from ~2019. Real per-strike OI / ΔOI / volume / settlement.",
            "auto": "bhavcopy where it downloads, else synthetic per date.",
            "local": "your own CSVs from Kaggle / GitHub / an export (see local_history_dir).",
            "local_bhavcopy": "local → bhavcopy → synthetic, best coverage.",
        },
        "bhavcopy_probe": {"date": probe.isoformat(), "reachable": bhav_ok},
        "local_history": local_history.source_info(),
        "kaggle_cli": {"ready": k_ok, "detail": k_why},
    }


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _pick_expiry(db: Session, underlying: str, expiry: str | None) -> str:
    exps = [e for e in instrument_service.expiries(db, underlying)
            if date.fromisoformat(e) >= date.today()]
    if not exps:
        raise ValidationError(f"No listed option expiries for {underlying}.")
    if expiry:
        if expiry[:10] not in exps:
            raise ValidationError(f"{expiry} is not a listed {underlying} expiry. Choose from {exps[:6]}.")
        return expiry[:10]
    return exps[0]


def _prev_close(daily_bars: list[Any]) -> float | None:
    if len(daily_bars) < 2:
        return float(daily_bars[-1].close) if daily_bars else None
    last = daily_bars[-1]
    is_today = str(getattr(last, "timestamp", ""))[:10] == date.today().isoformat()
    return float(daily_bars[-2].close) if is_today else float(last.close)


def _bars_today(intraday: list[Any]) -> list[Any]:
    if not intraday:
        return []
    d = str(getattr(intraday[-1], "timestamp", ""))[:10]
    return [b for b in intraday if str(getattr(b, "timestamp", ""))[:10] == d]


def _summary(b: AnalysisBundle) -> list[str]:
    reg, pcr_s, vol_s, em, dq = b.regime, b.pcr, b.volatility, b.expected_move, b.dq
    out: list[str] = []
    if not dq.ok:
        out.append("Data quality failed the gate — readings below are for diagnosis only, not a decision.")
    out.append(
        f"Regime: {reg.label.replace('_', ' ').title()} ({reg.direction.lower()}, "
        f"{reg.vol_class.lower()} vol). Confidence {reg.confidence:.0f}/100, "
        f"stability {reg.stability:.0f}, transition risk {reg.transition_risk:.0f}."
    )
    out.append(
        f"Positioning (PCR): weighted {pcr_s.weighted_pcr:.2f} — {pcr_s.state.replace('_', ' ').lower()}"
        + (f", {pcr_s.transition.replace('_', ' ').lower()}"
           + (" (confirmed)" if pcr_s.transition_confirmed else " (unconfirmed)")
           if pcr_s.transition != "STABLE" else ", stable")
        + (f"; {pcr_s.price_divergence.replace('_', ' ').lower()} vs price"
           if pcr_s.price_divergence not in ("NA", "ALIGNED") else "")
        + "."
    )
    iv_txt = f"{vol_s.atm_iv*100:.1f}%" if vol_s.atm_iv else "n/a"
    rank_txt = f", IV rank {vol_s.iv_rank:.0f}" if vol_s.iv_rank is not None else " (rank pending history)"
    out.append(
        f"Volatility: ATM IV {iv_txt}{rank_txt}; {vol_s.iv_class.replace('_', ' ').lower()}. "
        f"Premium selling looks {vol_s.vol_selling_verdict.lower()} (score {vol_s.vol_selling_score:.0f}/100)."
    )
    if em.points:
        out.append(
            f"Expected move to expiry: ±{em.points:.0f} pt ({em.lower:.0f} – {em.upper:.0f})"
            + (f"; today's move is {em.current_vs_expected:.0%} of that."
               if em.current_vs_expected is not None else ".")
        )
    for drv in reg.drivers[:2]:
        out.append(drv)
    return out


def _analyse(
    db: Session, settings: Settings, *, underlying: str, expiry: str | None,
    cfg: AdaptiveConfig, record: bool,
) -> AnalysisBundle | dict[str, Any]:
    u = underlying.strip().upper()
    if u not in _SUPPORTED:
        raise ValidationError(f"Adaptive Options supports {', '.join(_SUPPORTED)} (got {u!r}).")
    exp = _pick_expiry(db, u, expiry)
    dte = max((date.fromisoformat(exp) - date.today()).days, 0)
    spot_sym = _SPOT_SYM[u]
    today = datetime.now()

    try:
        daily_map, _sk = fetch_candles(
            db, settings, symbols=[spot_sym], timeframe="1d",
            start=(today - timedelta(days=420)).date().isoformat(), end=today.date().isoformat())
        intra_map, _sk2 = fetch_candles(
            db, settings, symbols=[spot_sym], timeframe="5m",
            start=(today - timedelta(days=4)).date().isoformat(), end=today.date().isoformat())
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"Underlying history unavailable: {exc}",
                "underlying": u, "expiry": exp}
    daily = next(iter(daily_map.values()), [])
    intraday = next(iter(intra_map.values()), [])
    if len(daily) < 30:
        return {"available": False, "reason": "Not enough underlying daily history to analyse.",
                "underlying": u, "expiry": exp}

    chain_payload = market_data_service.option_chain(db, settings, underlying=u, expiry=exp)
    if not chain_payload.get("available"):
        return {"available": False, "reason": chain_payload.get("reason", "Option chain unavailable."),
                "underlying": u, "expiry": exp}

    snap = from_live_payload(chain_payload, dte=dte, prev_rows=snapshots.prev_oi_rows(db, u, exp))
    hist = snapshots.load_history(db, u, exp)

    dc = [float(x.close) for x in daily]
    dh = [float(x.high) for x in daily]
    dl = [float(x.low) for x in daily]
    rv_bar = rolling_volatility(dc, cfg.rv_lookback_days)
    realized_vol = rv_bar * math.sqrt(252.0) if rv_bar else None
    atr_pts = atr(dh, dl, dc, cfg.atr_period)
    prev_close = _prev_close(daily)
    price_chg_pct = ((snap.spot - prev_close) / prev_close * 100.0) if (prev_close and snap.spot) else None
    tod = _bars_today(intraday)
    day_open = float(tod[0].open) if tod else (float(daily[-1].open) if daily else None)

    far_atm_iv = None
    far_exps = [e for e in instrument_service.expiries(db, u) if e > exp]
    try:
        if far_exps:
            far = market_data_service.option_chain(db, settings, underlying=u, expiry=far_exps[0])
            if far.get("available"):
                far_snap = from_live_payload(far, dte=(date.fromisoformat(far_exps[0]) - date.today()).days)
                fr = next((r for r in far_snap.rows if r.strike == far_snap.atm_strike()), None)
                if fr:
                    ivs = [v for v in (fr.call_iv, fr.put_iv) if v]
                    far_atm_iv = sum(ivs) / len(ivs) if ivs else None
    except Exception:  # noqa: BLE001
        far_atm_iv = None

    dq = data_quality.assess_chain(snap, cfg)
    dq_bar_issues = data_quality.assess_bars(daily)
    intel = mi_engine.analyse(daily, cfg, intraday_bars=intraday)
    pcr_s = pcr_engine.analyse(snap, cfg, history=hist)
    pos_s = positioning.analyse(snap, cfg, price_change_pct=price_chg_pct, history=hist)
    vol_s = volatility.analyse(
        snap, cfg, iv_history=[h["atm_iv"] for h in hist if h.get("atm_iv")],
        realized_vol=realized_vol, adx=intel.adx, trend_strength=intel.trend_strength,
        far_atm_iv=far_atm_iv)
    grk = greeks_engine.chain(snap, cfg, realized_vol=realized_vol)
    em = expected_move.compute(snap, cfg, atm_iv=vol_s.atm_iv, atr_points=atr_pts, day_open=day_open)
    conf = confidence.score(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s, snap=snap)
    reg = regime.classify(cfg, intel=intel, pcr=pcr_s, positioning=pos_s, vol=vol_s,
                          expected_move=em, confidence=conf, data_ok=dq.ok)

    recorded = None
    if record:
        try:
            row = snapshots.record(
                db, snap, oi_pcr=pcr_s.oi_pcr, weighted_pcr=pcr_s.weighted_pcr,
                atm_iv=vol_s.atm_iv, put_support=pos_s.put_support,
                call_resistance=pos_s.call_resistance)
            recorded = row.captured_at.isoformat() if row else "throttled"
        except Exception:  # noqa: BLE001
            db.rollback()
            recorded = "error"

    return AnalysisBundle(
        cfg=cfg, snap=snap, dq=dq, dq_bar_issues=dq_bar_issues, intel=intel, pcr=pcr_s,
        positioning=pos_s, volatility=vol_s, greeks=grk, expected_move=em, confidence=conf,
        regime=reg, dte=dte, history_len=len(hist), far_expiry_ok=bool(far_exps), recorded=recorded,
    )


def _intel_payload(b: AnalysisBundle) -> dict[str, Any]:
    return {
        "available": True,
        "underlying": b.snap.underlying, "expiry": b.snap.expiry, "dte": b.dte,
        "spot": b.snap.spot, "as_of": b.snap.as_of.isoformat(),
        "config": {"preset": b.cfg.risk_profile, **b.cfg.to_dict()},
        "summary": _summary(b),
        "regime": b.regime.as_dict(), "confidence": b.confidence.as_dict(),
        "pcr": b.pcr.as_dict(), "positioning": b.positioning.as_dict(),
        "volatility": b.volatility.as_dict(), "greeks": b.greeks.as_dict(),
        "expected_move": b.expected_move.as_dict(),
        "market_intelligence": b.intel.as_dict(),
        "data_quality": {**b.dq.as_dict(),
                         "underlying_issues": [i.as_dict() for i in b.dq_bar_issues]},
        "chain": b.snap.as_dict(),
        "history_len": b.history_len, "snapshot_recorded": b.recorded,
    }


# --------------------------------------------------------------------------
# public entry points
# --------------------------------------------------------------------------

def market_intelligence(
    db: Session, settings: Settings, *, underlying: str = "NIFTY", expiry: str | None = None,
    preset: str | None = None, overrides: dict[str, Any] | None = None, record: bool = True,
) -> dict[str, Any]:
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset or "balanced")
    b = _analyse(db, settings, underlying=underlying, expiry=expiry, cfg=cfg, record=record)
    if isinstance(b, dict):
        return b
    return _intel_payload(b)


def run_decision(
    db: Session, settings: Settings, *, underlying: str = "NIFTY", expiry: str | None = None,
    preset: str | None = None, overrides: dict[str, Any] | None = None,
    compare_slugs: list[str] | None = None, record: bool = True,
) -> dict[str, Any]:
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset or "balanced")
    b = _analyse(db, settings, underlying=underlying, expiry=expiry, cfg=cfg, record=record)
    if isinstance(b, dict):
        return b

    sel = strategy_selector.rank(
        cfg, snap=b.snap, regime=b.regime, pcr=b.pcr, positioning=b.positioning,
        vol=b.volatility, expected_move=b.expected_move, confidence=b.confidence,
        intel=b.intel, data_ok=b.dq.ok, far_expiry_ok=b.far_expiry_ok,
    )

    entry: dict[str, Any] | None = None
    if sel.action == "ENTER" and sel.top is not None:
        from app.adaptive_options.strategy_library import build_position, get_template
        tmpl = get_template(sel.top.slug)
        plan = sel.top.strikes["levels"]
        pos1 = build_position(tmpl, plan, b.snap, lots=1,
                              lot_size=strategy_selector._lot_size(b.snap),  # noqa: SLF001
                              fallback_iv=b.volatility.atm_iv or 0.13)
        sz = sizing.size(pos1, cfg, dte=b.dte)
        state = risk_engine.PortfolioState(capital=cfg.account_capital, spot=b.snap.spot)
        rk = risk_engine.check_entry(sz, pos1, cfg, state, data_ok=b.dq.ok, dte=b.dte)
        final_lots = max(0, int(sz.lots * rk.scale)) if rk.ok else 0
        entry = {
            "template": tmpl.as_dict(),
            "sized": sz.as_dict(),
            "risk": rk.as_dict(),
            "final_lots": final_lots,
            "actionable": rk.ok and final_lots > 0,
        }
        if not (rk.ok and final_lots > 0):
            sel = strategy_selector.SelectionResult(
                "WAIT", rk.blocked_reason or "Risk engine reduced size to zero.",
                sel.ranked, sel.avoid, sel.top, sel.decision_matrix)

    comparison = None
    if compare_slugs:
        comparison = strategy_selector.compare(
            cfg, compare_slugs, snap=b.snap, regime=b.regime, pcr=b.pcr,
            positioning=b.positioning, vol=b.volatility, expected_move=b.expected_move,
            confidence=b.confidence, intel=b.intel, data_ok=b.dq.ok,
            far_expiry_ok=b.far_expiry_ok,
        )

    payload = _intel_payload(b)
    payload["decision"] = {
        **sel.as_dict(),
        "entry": entry,
        "expiry_guidance": risk_engine.expiry_guidance(b.dte, cfg),
    }
    if comparison is not None:
        payload["decision"]["comparison"] = comparison
    return payload


def backtest(
    db: Session, settings: Settings, *, underlying: str = "NIFTY",
    start: str, end: str, mode: str = "simple", preset: str = "balanced",
    risk_level: str | None = None, capital: float | None = None,
    overrides: dict[str, Any] | None = None, expiry_kind: str = "weekly",
    data_source: str = "synthetic",
) -> dict[str, Any]:
    """Phase 14. ``mode='simple'`` maps a risk level + capital to sensible
    config; ``mode='advanced'`` passes ``overrides`` straight through."""
    from app.adaptive_options.backtest import run_adaptive_backtest

    cfg_over: dict[str, Any] = dict(overrides or {})
    if mode == "simple":
        rl = (risk_level or preset or "balanced").lower()
        preset = {"conservative": "conservative", "moderate": "balanced",
                  "balanced": "balanced", "aggressive": "aggressive"}.get(rl, "balanced")
        if capital:
            cfg_over.setdefault("account_capital", float(capital))
    elif capital:
        cfg_over.setdefault("account_capital", float(capital))

    return run_adaptive_backtest(
        db, settings, underlying=underlying, start=start, end=end,
        config=cfg_over or None, preset=preset,
        expiry_kind=expiry_kind, data_source=data_source,
    )


def validate(
    db: Session, settings: Settings, *, underlying: str = "NIFTY", start: str, end: str,
    preset: str = "balanced", overrides: dict[str, Any] | None = None,
    n_folds: int = 3, mc_sims: int = 400, sensitivity_params: list[str] | None = None,
    data_source: str = "synthetic",
) -> dict[str, Any]:
    from app.adaptive_options.validation import run_validation
    return run_validation(
        db, settings, underlying=underlying, start=start, end=end, preset=preset,
        overrides=overrides, n_folds=n_folds, mc_sims=mc_sims,
        sensitivity_params=sensitivity_params, data_source=data_source,
    )


def evaluate_open_position(
    db: Session, settings: Settings, *, underlying: str, expiry: str, position: dict[str, Any],
    current_pnl: float, preset: str | None = None, overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase 12 — run the leg manager against a live read for an open
    position (dict shape = leg_manager.OpenPosition fields)."""
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset or "balanced")
    b = _analyse(db, settings, underlying=underlying, expiry=expiry, cfg=cfg, record=False)
    if isinstance(b, dict):
        return b
    op = leg_manager.OpenPosition(**position)
    action = leg_manager.evaluate(
        op, cfg, snap=b.snap, regime=b.regime, pcr=b.pcr, intel=b.intel, vol=b.volatility,
        current_pnl=current_pnl, dte=b.dte)
    return {
        "available": True, "underlying": b.snap.underlying, "expiry": b.snap.expiry,
        "spot": b.snap.spot, "dte": b.dte,
        "regime": b.regime.as_dict(), "action": action.as_dict(),
    }
