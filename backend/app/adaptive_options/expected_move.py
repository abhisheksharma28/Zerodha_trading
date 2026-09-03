"""Phase 6 — Expected Move, three ways.

  straddle : ~0.85 x ATM straddle price   (market's own implied 1-sd move)
  iv       : spot x ATM_IV x sqrt(DTE/365)
  atr      : daily ATR (points) x sqrt(DTE)   (realized-movement anchor)

Headline = median of whatever methods have inputs. The band is
+/- headline x ``expected_move_band_sd``.
"""

from __future__ import annotations

import math

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, ExpectedMove


def compute(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *,
    atm_iv: float | None = None,
    atr_points: float | None = None,
    day_open: float | None = None,
) -> ExpectedMove:
    spot = snap.spot
    dte = max(snap.dte, 0.0)
    methods: dict[str, float | None] = {"straddle": None, "iv": None, "atr": None}
    notes: list[str] = []

    atm = snap.atm_strike()
    atm_row = next((r for r in snap.rows if r.strike == atm), None)
    if atm_row and atm_row.call_ltp and atm_row.put_ltp:
        methods["straddle"] = 0.85 * (float(atm_row.call_ltp) + float(atm_row.put_ltp))

    if atm_iv and atm_iv > 0 and spot > 0 and dte > 0:
        methods["iv"] = spot * atm_iv * math.sqrt(dte / 365.0)

    if atr_points and atr_points > 0 and dte > 0:
        methods["atr"] = atr_points * math.sqrt(dte)

    vals = [v for v in methods.values() if v is not None and v > 0]
    if not vals:
        notes.append("No expected-move inputs (need ATM straddle prices, ATM IV, or an ATR).")
        return ExpectedMove(None, None, None, None, methods, None, None, notes)

    vals.sort()
    headline = vals[len(vals) // 2] if len(vals) % 2 else 0.5 * (vals[len(vals) // 2 - 1] + vals[len(vals) // 2])
    band = headline * cfg.expected_move_band_sd
    upper = spot + band
    lower = spot - band
    pct = band / spot * 100.0 if spot else None

    cur_pts = cur_ratio = None
    if day_open and day_open > 0:
        cur_pts = spot - day_open
        cur_ratio = abs(cur_pts) / headline if headline else None
        if cur_ratio and cur_ratio > 1.0:
            notes.append(f"Today's move ({abs(cur_pts):.0f} pt) has already exceeded the "
                         f"expected move ({headline:.0f} pt) — expansion regime.")

    return ExpectedMove(
        points=round(headline, 1),
        upper=round(upper, 1), lower=round(lower, 1),
        pct=round(pct, 3) if pct is not None else None,
        by_method={k: (round(v, 1) if v is not None else None) for k, v in methods.items()},
        current_move_points=round(cur_pts, 1) if cur_pts is not None else None,
        current_vs_expected=round(cur_ratio, 2) if cur_ratio is not None else None,
        notes=notes,
    )
