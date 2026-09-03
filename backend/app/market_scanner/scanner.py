"""Orchestrate one sweep of the universe into persisted LIVE recommendations.

Budget-aware: the core tier gets full daily + 15-minute candle pulls; the
broad tier rides one batched quote sweep and only the few names that light
up the cheap screen get a (daily-only) full evaluation.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_scanner import fundamentals as fund_mod
from app.market_scanner import marketdata as md
from app.market_scanner import options_overlay, signals
from app.market_scanner import structure as st
from app.market_scanner.features import daily_features, intraday_features
from app.market_scanner.signals import SignalConfig, SignalInput
from app.market_scanner.universe import ScanInstrument, Universe
from app.market_scanner.universe import build as build_universe
from app.models.market_scanner import ScannerAlert, ScanRecommendation, ScanRun

logger = get_logger(__name__)
IST = ZoneInfo("Asia/Kolkata")
_SCAN_RUN_LOCK = 776611  # serialize scans (scheduler loop vs a manual POST /scan)


@dataclass
class ScanOutcome:
    run_id: str | None
    data_available: bool
    reason: str | None
    scanned: int
    produced: int
    skipped: dict[str, str]
    notes: list[str] = field(default_factory=list)
    recommendation_ids: list[str] = field(default_factory=list)


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


def _evaluate_instrument(
    client: Any, settings: Settings, si: ScanInstrument, cfg: SignalConfig, *, deep: bool
) -> tuple[signals.Setup | None, str | None]:
    """Returns (setup, skip_reason)."""
    daily = md.fetch_bars(client, si.instrument_token, "day")
    if len(daily) < 40:
        return None, f"only {len(daily)} daily bars"
    d_feat = daily_features(daily)
    d_struct = st.analyse(daily, min_bars=30)

    i_feat = i_struct = None
    if deep:
        intr = md.fetch_bars(client, si.instrument_token, "15minute")
        if len(intr) >= 20:
            i_feat = intraday_features(intr)
            i_struct = st.analyse(intr[-160:], min_bars=20)

    # fundamentals (yfinance) are slow - fetch them only for the handful of
    # names that get persisted, in the caller, not for every scanned symbol
    ltp = d_feat.close
    inp = SignalInput(
        ltp=ltp, asset_class=si.asset_class, has_options=si.has_options,
        daily=d_feat, daily_structure=d_struct,
        intraday=i_feat, intraday_structure=i_struct, fundamentals=None,
        tick_size=0.05,
    )
    return signals.evaluate(inp, cfg), None


def _existing_open(db: Session, symbol: str, day: str) -> set[str]:
    """Directions already issued for this symbol today - LIVE *or* already
    resolved - so a stopped-out name is not re-recommended minutes later."""
    rows = db.execute(
        select(ScanRecommendation.direction).where(
            ScanRecommendation.tradingsymbol == symbol,
            ScanRecommendation.trading_day == day,
        )
    ).scalars().all()
    return set(rows)


_STYLE_LABEL = {
    "EQUITY_DELIVERY": "Delivery", "EQUITY_INTRADAY": "Intraday", "OPTION": "Options",
}


def _protective_hedge(
    db: Session, si: ScanInstrument, setup: signals.Setup,
) -> dict[str, Any] | None:
    """A protective option leg to hold *alongside* a LONG delivery position:
    buy an OTM put near the stop so the combined loss is floored. Premium is
    a Black-Scholes estimate from ATR-implied vol - no extra quote call."""
    if setup.direction != "LONG" or not si.underlying or not setup.atr:
        return None
    from app.options.greeks import bs_price
    from app.services import instrument_service

    exp = options_overlay._nearest_expiry(db, si.underlying)  # noqa: SLF001
    if not exp:
        return None
    expiry, dte = exp
    strikes = [
        s for s in instrument_service.option_strikes(db, si.underlying, expiry)
        if s["option_type"] == "PE" and s.get("strike")
    ]
    if not strikes:
        return None
    target = float(setup.stop_loss)
    row = min(strikes, key=lambda s: abs(s["strike"] - target))
    strike = float(row["strike"])
    spot = float(setup.entry)
    iv = max(0.08, min(1.2, (setup.atr / spot) * math.sqrt(252.0)))
    prem = bs_price(spot, strike, dte / 365.0, iv, is_call=False)
    lot = row.get("lot_size") or 0
    if prem <= 0 or not lot:
        return None
    cost_pct = 100.0 * prem / spot
    return {
        "leg": f"BUY {row['tradingsymbol']}",
        "strike": strike,
        "option_type": "PE",
        "expiry": expiry,
        "dte": dte,
        "lot_size": lot,
        "est_premium": round(prem, 2),
        "est_premium_per_lot": round(prem * lot, 0),
        "cost_pct": round(cost_pct, 2),
        "floor_price": strike,
        "note": (
            f"Optional hedge: buy 1 lot ({lot}) of the {expiry} {strike:.0f} PE "
            f"(~Rs {prem * lot:,.0f}, ~{cost_pct:.1f}% of the position) together with the "
            f"shares to cap the downside near {strike:.0f}. Estimated premium - confirm the "
            f"live quote before placing."
        ),
    }


def _persist(
    db: Session, run: ScanRun, si: ScanInstrument, setup: signals.Setup, *,
    trade_style: str, fv: Any, day: str, overlay: dict[str, Any] | None = None,
    hedge: dict[str, Any] | None = None, pair_id: uuid.UUID | None = None,
) -> ScanRecommendation:
    """One recommendation. For ``trade_style="OPTION"`` the entry/stop/target
    stay on the *underlying* (that is the thesis to manage against) and the
    spread economics live in ``option_overlay``."""
    is_option = trade_style == "OPTION"
    rec = ScanRecommendation(
        scan_run_id=run.id,
        exchange=si.exchange, tradingsymbol=si.tradingsymbol, instrument_token=si.instrument_token,
        segment=si.segment, name=si.name, underlying=si.underlying, asset_class=si.asset_class,
        horizon=setup.horizon, trade_style=trade_style,
        direction=setup.direction, setup_type=setup.setup_type, setup_tags=setup.setup_tags,
        ref_price=setup.entry, entry=setup.entry, entry_type=setup.entry_type,
        stop_loss=setup.stop_loss, target_1=setup.target_1, target_2=setup.target_2,
        rr=setup.rr, atr=setup.atr,
        confidence=setup.confidence, bias_score=setup.bias_score,
        score_detail=setup.score_detail or None,
        pop=(overlay or {}).get("pop") if is_option else None,
        factors=setup.factor_dicts(),
        option_overlay=overlay if is_option else None,
        hedge=hedge if not is_option else None,
        pair_id=pair_id,
        fundamentals=fv.as_dict() if fv and getattr(fv, "available", False) else None,
        status="LIVE", trading_day=day,
        entered_price=setup.entry if setup.entry_type == "MARKET" else None,
    )
    db.add(rec)
    db.flush()
    label = _STYLE_LABEL.get(trade_style, trade_style)
    db.add(ScannerAlert(
        recommendation_id=rec.id, kind="NEW_TRADE",
        title=f"{setup.direction} {si.tradingsymbol} · {label}",
        body=(f"{setup.setup_type}. Entry {setup.entry}, SL {setup.stop_loss}, "
              f"T1 {setup.target_1}, R:R {setup.rr}, confidence {setup.confidence:.0f}."),
        payload={"recommendation_id": str(rec.id), "confidence": setup.confidence,
                 "direction": setup.direction, "horizon": setup.horizon, "trade_style": trade_style},
    ))
    return rec


def run_scan(
    db: Session, settings: Settings, *, trigger: str = "schedule",
    universe: Universe | None = None,
) -> ScanOutcome:
    started = datetime.now(UTC)
    t0 = time.monotonic()

    # serialize: never let a manual scan and the scheduled loop run at once
    got_lock = bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _SCAN_RUN_LOCK}).scalar())
    if not got_lock:
        return ScanOutcome(None, False, "A scan is already in progress.", 0, 0, {}, ["scan already running"])

    try:
        return _run_scan_locked(db, settings, trigger=trigger, universe=universe,
                                started=started, t0=t0)
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _SCAN_RUN_LOCK})
        db.commit()


def _run_scan_locked(
    db: Session, settings: Settings, *, trigger: str, universe: Universe | None,
    started: datetime, t0: float,
) -> ScanOutcome:
    run = ScanRun(started_at=started, trigger=trigger)
    db.add(run)
    db.flush()

    client = md.get_client(db, settings)
    if client is None:
        run.finished_at = datetime.now(UTC)
        run.data_available = False
        run.reason = "No connected Zerodha session — live market data unavailable."
        db.commit()
        return ScanOutcome(str(run.id), False, run.reason, 0, 0, {}, [run.reason])

    uni = universe or build_universe(
        db, core_max=settings.market_scanner_core_max,
        broad_max=settings.market_scanner_broad_max,
    )
    cfg = SignalConfig()
    day = _today_ist()
    skipped: dict[str, str] = {}
    setups: list[tuple[ScanInstrument, signals.Setup]] = []
    scanned = 0

    # --- core tier: deep scan --------------------------------------------
    for si in uni.core:
        scanned += 1
        try:
            setup, reason = _evaluate_instrument(client, settings, si, cfg, deep=True)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not kill the sweep
            skipped[si.ref] = f"{type(exc).__name__}: {exc}"
            continue
        if reason:
            skipped[si.ref] = reason
        elif setup:
            setups.append((si, setup))

    # --- broad tier: liquid cash equities, daily-bar scan for delivery /
    #     swing ideas (no F&O needed). Daily bars cache ~1h so repeat scans
    #     in the session are cheap.
    for si in uni.broad:
        scanned += 1
        try:
            setup, reason = _evaluate_instrument(client, settings, si, cfg, deep=False)
        except Exception as exc:  # noqa: BLE001
            skipped[si.ref] = f"{type(exc).__name__}: {exc}"
            continue
        if reason:
            skipped[si.ref] = reason
        elif setup:
            setups.append((si, setup))

    # --- rank, de-dupe, attach overlay, persist -------------------------
    setups.sort(key=lambda x: (-x[1].confidence, -abs(x[1].bias_score)))
    produced_ids: list[str] = []
    live_now = db.execute(
        select(func.count()).select_from(ScanRecommendation).where(ScanRecommendation.status == "LIVE")
    ).scalar_one()
    for si, setup in setups:
        if live_now + len(produced_ids) >= settings.market_scanner_max_live:
            skipped[si.ref] = "live-recommendation cap reached"
            continue
        if setup.direction in _existing_open(db, si.tradingsymbol, day):
            skipped[si.ref] = "already have an open call this direction today"
            continue
        fv = None
        if si.asset_class == "EQUITY":
            fv = fund_mod.view(settings, si.tradingsymbol, asset_class=si.asset_class)

        # 1. the equity idea (delivery / intraday) - the primary card.
        #    Indices have no cash leg, so skip a bare equity card for them
        #    unless there is no option overlay to carry the view.
        style = signals.trade_style_for(setup.horizon, si.asset_class)
        overlay = None
        if si.has_options and si.underlying and setup.confidence >= settings.market_scanner_overlay_min_confidence:
            try:
                overlay = options_overlay.build(db, settings, options_overlay.OverlayInput(
                    underlying=si.underlying, spot=setup.entry, direction=setup.direction,
                    atr_daily=setup.atr, confidence=setup.confidence,
                ))
            except Exception as exc:  # noqa: BLE001 - overlay is optional
                logger.info("scanner_overlay_error", ref=si.ref, error=str(exc))

        pair_id = uuid.uuid4() if overlay is not None else None

        if si.asset_class != "INDEX" or overlay is None:
            hedge = None
            if style == "EQUITY_DELIVERY" and si.has_options:
                try:
                    hedge = _protective_hedge(db, si, setup)
                except Exception as exc:  # noqa: BLE001 - hedge suggestion is optional
                    logger.info("scanner_hedge_error", ref=si.ref, error=str(exc))
            rec = _persist(db, run, si, setup, trade_style=style, fv=fv, day=day,
                           hedge=hedge, pair_id=pair_id)
            produced_ids.append(str(rec.id))

        # 2. a separate OPTION card when a defined-risk spread expresses the
        #    same view (its own KPIs; entry/stop/target stay on the underlying)
        if overlay is not None and live_now + len(produced_ids) < settings.market_scanner_max_live:
            orec = _persist(db, run, si, setup, trade_style="OPTION", fv=fv, day=day,
                            overlay=overlay, pair_id=pair_id)
            produced_ids.append(str(orec.id))

    run.finished_at = datetime.now(UTC)
    run.data_available = True
    run.universe_size = uni.size
    run.scanned = scanned
    run.produced = len(produced_ids)
    run.elapsed_ms = int((time.monotonic() - t0) * 1000)
    run.skipped = dict(list(skipped.items())[:200])
    run.notes = []
    db.commit()

    logger.info("market_scan_complete", scanned=scanned, produced=len(produced_ids),
                elapsed_ms=run.elapsed_ms)
    return ScanOutcome(
        str(run.id), True, None, scanned, len(produced_ids), skipped, run.notes, produced_ids,
    )
