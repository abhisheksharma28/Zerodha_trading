"""Attach a defined-risk vertical spread to a strong directional setup.

Only for F&O underlyings, only when the equity/index signal is strong. Uses
**real** option quotes from the connected Kite session - if they are
unavailable the overlay is simply omitted (never synthesised). ``pop`` is a
lognormal probability the underlying finishes past the spread breakeven,
using the long leg's implied vol.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.options.greeks import DEFAULT_RATE, implied_vol, norm_cdf
from app.services import broker_service, instrument_service

logger = get_logger(__name__)

_MIN_DTE = 2
_MAX_DTE = 45


@dataclass
class OverlayInput:
    underlying: str
    spot: float
    direction: str  # LONG | SHORT
    atr_daily: float | None
    confidence: float


def _nearest_expiry(db: Session, underlying: str) -> tuple[str, int] | None:
    today = date.today()
    for e in instrument_service.expiries(db, underlying):
        try:
            dte = (date.fromisoformat(e) - today).days
        except ValueError:
            continue
        if _MIN_DTE <= dte <= _MAX_DTE:
            return e, dte
    return None


def _expected_move(spot: float, atr_daily: float | None, dte: int) -> float:
    if atr_daily and atr_daily > 0:
        return atr_daily * math.sqrt(max(dte, 1))
    return spot * 0.015 * math.sqrt(max(dte, 1))


def build(db: Session, settings: Settings, inp: OverlayInput) -> dict[str, Any] | None:
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except Exception:  # noqa: BLE001 - no session -> no overlay, quietly
        return None

    exp = _nearest_expiry(db, inp.underlying)
    if not exp:
        return None
    expiry, dte = exp
    strikes = instrument_service.option_strikes(db, inp.underlying, expiry)
    if not strikes:
        return None

    is_call = inp.direction == "LONG"
    opt_type = "CE" if is_call else "PE"
    rows = sorted(
        (s for s in strikes if s["option_type"] == opt_type and s.get("strike")),
        key=lambda s: s["strike"],
    )
    if len(rows) < 4:
        return None

    step = min((rows[i + 1]["strike"] - rows[i]["strike"] for i in range(len(rows) - 1)), default=0)
    if step <= 0:
        return None
    atm = min(rows, key=lambda s: abs(s["strike"] - inp.spot))["strike"]
    em = _expected_move(inp.spot, inp.atr_daily, dte)
    short_strike = (atm + max(em, step) if is_call else atm - max(em, step))
    short_strike = round(short_strike / step) * step

    long_row = next((s for s in rows if s["strike"] == atm), None)
    short_row = next((s for s in rows if s["strike"] == short_strike), None)
    if not long_row or not short_row or long_row["strike"] == short_row["strike"]:
        return None

    refs = [f"NFO:{long_row['tradingsymbol']}", f"NFO:{short_row['tradingsymbol']}"]
    try:
        q = client.get_quote(refs)
    except Exception as exc:  # noqa: BLE001
        logger.info("scanner_overlay_quote_failed", underlying=inp.underlying, error=str(exc))
        return None

    def _ltp(ref: str) -> float | None:
        d = q.get(ref) or q.get(ref.replace("NFO:", ""))
        v = (d or {}).get("last_price")
        return float(v) if v else None

    long_px, short_px = _ltp(refs[0]), _ltp(refs[1])
    if not long_px or not short_px or long_px <= short_px:
        return None

    width = abs(short_row["strike"] - long_row["strike"])
    net_debit = long_px - short_px
    max_profit = width - net_debit
    if max_profit <= 0:
        return None
    breakeven = (long_row["strike"] + net_debit) if is_call else (long_row["strike"] - net_debit)

    t = dte / 365.0
    iv = implied_vol(long_px, inp.spot, long_row["strike"], t, is_call=is_call)
    pop = None
    if iv and iv > 0:
        drift = (DEFAULT_RATE - 0.5 * iv * iv) * t
        z = (math.log(inp.spot / breakeven) + drift) / (iv * math.sqrt(t))
        pop = norm_cdf(z) if is_call else norm_cdf(-z)

    lot = long_row.get("lot_size") or short_row.get("lot_size") or 0
    pulse = chain_pulse(db, settings, inp.underlying, inp.spot, expiry, dte, inp.atr_daily)
    return {
        "structure": "bull_call_spread" if is_call else "bear_put_spread",
        "underlying": inp.underlying,
        "expiry": expiry,
        "dte": dte,
        "lot_size": lot,
        "legs": [
            {"tradingsymbol": long_row["tradingsymbol"], "strike": long_row["strike"],
             "option_type": opt_type, "side": "BUY", "price": round(long_px, 2)},
            {"tradingsymbol": short_row["tradingsymbol"], "strike": short_row["strike"],
             "option_type": opt_type, "side": "SELL", "price": round(short_px, 2)},
        ],
        "net_debit": round(net_debit, 2),
        "max_profit_per_unit": round(max_profit, 2),
        "max_loss_per_unit": round(net_debit, 2),
        "max_profit": round(max_profit * lot, 2) if lot else None,
        "max_loss": round(net_debit * lot, 2) if lot else None,
        "breakeven": round(breakeven, 2),
        "rr": round(max_profit / net_debit, 2) if net_debit > 0 else None,
        "pop": round(pop, 4) if pop is not None else None,
        "iv": round(iv, 4) if iv else None,
        "chain_pulse": pulse,
        "note": "Real Kite option quotes. Defined risk. Not advice.",
    }


def chain_pulse(
    db: Session, settings: Settings, underlying: str, spot: float,
    expiry: str, dte: int, atr_daily: float | None,
) -> dict[str, Any] | None:
    """A quick read of the near-expiry option chain around the money:
    open-interest PCR, a crude max-pain strike, ATM implied vol and the
    1-expiry expected move. One extra quote call; greeks-flavoured context
    for the F&O idea, not a trade trigger."""
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except Exception:  # noqa: BLE001
        return None
    strikes = instrument_service.option_strikes(db, underlying, expiry)
    if not strikes:
        return None
    ce = sorted((s for s in strikes if s["option_type"] == "CE" and s.get("strike")),
                key=lambda s: s["strike"])
    pe = {s["strike"]: s for s in strikes if s["option_type"] == "PE" and s.get("strike")}
    if len(ce) < 5 or not pe:
        return None
    atm = min((s["strike"] for s in ce), key=lambda k: abs(k - spot))
    band = [s for s in ce if abs(s["strike"] - atm) <= 6 * max(
        (ce[i + 1]["strike"] - ce[i]["strike"] for i in range(len(ce) - 1)), default=1)]
    refs: list[str] = []
    for s in band:
        refs.append(f"NFO:{s['tradingsymbol']}")
        if s["strike"] in pe:
            refs.append(f"NFO:{pe[s['strike']]['tradingsymbol']}")
    if not refs:
        return None
    try:
        q = client.get_quote(refs)
    except Exception as exc:  # noqa: BLE001
        logger.info("scanner_chain_pulse_quote_failed", underlying=underlying, error=str(exc))
        return None

    def _row(ref: str) -> dict[str, Any]:
        return q.get(ref) or q.get(ref.replace("NFO:", "")) or {}

    call_oi = put_oi = 0.0
    pain: dict[float, float] = {}
    atm_iv_vals: list[float] = []
    t = max(dte, 1) / 365.0
    for s in band:
        k = s["strike"]
        cr = _row(f"NFO:{s['tradingsymbol']}")
        pr = _row(f"NFO:{pe[k]['tradingsymbol']}") if k in pe else {}
        c_oi = float(cr.get("oi") or 0.0)
        p_oi = float(pr.get("oi") or 0.0)
        call_oi += c_oi
        put_oi += p_oi
        # cash paid out by writers if expiry settled at k
        pain[k] = pain.get(k, 0.0) + sum(
            max(0.0, exp_k - k) * c_oi + max(0.0, k - exp_k) * p_oi
            for exp_k in (kk["strike"] for kk in band)
        )
        if abs(k - atm) < 1e-6:
            for px_row, cp in ((cr, True), (pr, False)):
                px = float(px_row.get("last_price") or 0.0)
                if px > 0:
                    v = implied_vol(px, spot, k, t, is_call=cp)
                    if v and v > 0:
                        atm_iv_vals.append(v)
    if call_oi <= 0 and put_oi <= 0:
        return None
    oi_pcr = round(put_oi / call_oi, 2) if call_oi > 0 else None
    max_pain = min(pain, key=lambda k: pain[k]) if pain else None
    atm_iv = round(sum(atm_iv_vals) / len(atm_iv_vals), 4) if atm_iv_vals else None
    em = _expected_move(spot, atr_daily, dte)

    nudge = 0.0
    read = "balanced positioning"
    if oi_pcr is not None:
        if oi_pcr >= 1.3:
            nudge, read = 0.5, f"OI PCR {oi_pcr} - put writers supporting (contrarian bullish)"
        elif oi_pcr <= 0.7:
            nudge, read = -0.5, f"OI PCR {oi_pcr} - call writers capping upside"
        else:
            read = f"OI PCR {oi_pcr} - neutral"
    return {
        "oi_pcr": oi_pcr,
        "max_pain": max_pain,
        "atm_iv": atm_iv,
        "expected_move": round(em, 2),
        "expected_move_pct": round(100.0 * em / spot, 2) if spot else None,
        "spot_vs_max_pain_pct": round(100.0 * (spot - max_pain) / spot, 2)
        if max_pain and spot else None,
        "nudge": nudge,
        "read": read,
    }
