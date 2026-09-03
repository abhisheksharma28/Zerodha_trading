"""Phase 10 — Strike Selection.

Produces the named strike *levels* the strategy templates consume
(atm, call_0/1/2, put_0/1/2) plus a per-level reason, using the method in
``AdaptiveConfig.strike_method``:

  delta               short legs at a target |delta|, wings further out
  expected_move       short legs at spot +/- strike_em_mult * expected move
  oi_wall             short call just inside the biggest call OI wall above
                      spot; short put just inside the biggest put OI wall
  support_resistance  short put near support, short call near resistance
  premium             short legs whose mid is closest to strike_target_premium

Every method snaps to a listed strike and, if ``strike_min_leg_oi`` > 0,
avoids strikes thinner than that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot
from app.options.greeks import black_scholes


@dataclass
class StrikePlan:
    method: str
    levels: dict[str, float]
    reasons: dict[str, str]
    per_leg: dict[str, dict[str, Any]] = field(default_factory=dict)   # level -> {delta, oi, liquidity}
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method, "levels": self.levels, "reasons": self.reasons,
            "per_leg": self.per_leg, "notes": self.notes,
        }


def _delta_of(snap: ChainSnapshot, strike: float, right: str, fallback_iv: float) -> float:
    row = min(snap.rows, key=lambda r: abs(r.strike - strike))
    iv = (row.call_iv if right == "CE" else row.put_iv) or fallback_iv
    g = black_scholes(snap.spot, strike, snap.t_years, max(iv, 1e-4), is_call=(right == "CE"))
    return abs(g.delta)


def _oi_at(snap: ChainSnapshot, strike: float, right: str) -> float:
    row = min(snap.rows, key=lambda r: abs(r.strike - strike))
    return row.call_oi if right == "CE" else row.put_oi


def _liquid_ok(snap: ChainSnapshot, strike: float, right: str, cfg: AdaptiveConfig) -> bool:
    return cfg.strike_min_leg_oi <= 0 or _oi_at(snap, strike, right) >= cfg.strike_min_leg_oi


def _nearest_by_delta(snap: ChainSnapshot, right: str, target: float, side: str,
                      cfg: AdaptiveConfig, fallback_iv: float) -> float:
    """Strike whose |delta| is closest to ``target``; for a short call/put we
    want the OTM one, so restrict to strikes on the OTM side of spot."""
    spot = snap.spot
    cands = [r.strike for r in snap.rows
             if (right == "CE" and r.strike >= spot) or (right == "PE" and r.strike <= spot)]
    cands = [k for k in cands if _liquid_ok(snap, k, right, cfg)] or cands
    if not cands:
        return snap.atm_strike() or spot
    return min(cands, key=lambda k: abs(_delta_of(snap, k, right, fallback_iv) - target))


def _snap_listed(snap: ChainSnapshot, target: float) -> float:
    return min(snap.rows, key=lambda r: abs(r.strike - target)).strike


def select(
    snap: ChainSnapshot,
    cfg: AdaptiveConfig,
    *,
    method: str | None = None,
    expected_move_points: float | None = None,
    support: float | None = None,
    resistance: float | None = None,
    call_wall: float | None = None,
    put_wall: float | None = None,
    fallback_iv: float = 0.13,
) -> StrikePlan:
    m = method or cfg.strike_method
    step = snap.strike_step()
    atm = snap.atm_strike() or snap.spot
    levels: dict[str, float] = {"atm": atm,
                                "call_0": _snap_listed(snap, atm + step),
                                "put_0": _snap_listed(snap, atm - step)}
    reasons: dict[str, str] = {
        "atm": f"ATM = nearest listed strike to spot {snap.spot:.0f}",
        "call_0": "one step above ATM (ratio / body leg)",
        "put_0": "one step below ATM (ratio / body leg)",
    }
    notes: list[str] = []

    # --- short strikes (call_1 / put_1) -----------------------------
    if m == "expected_move" and expected_move_points:
        c1 = _snap_listed(snap, snap.spot + cfg.strike_em_mult * expected_move_points)
        p1 = _snap_listed(snap, snap.spot - cfg.strike_em_mult * expected_move_points)
        reasons["call_1"] = f"spot + {cfg.strike_em_mult:g}x expected move ({expected_move_points:.0f} pt)"
        reasons["put_1"] = f"spot - {cfg.strike_em_mult:g}x expected move ({expected_move_points:.0f} pt)"
    elif m == "oi_wall":
        cw = call_wall or _snap_listed(snap, snap.spot + 3 * step)
        pw = put_wall or _snap_listed(snap, snap.spot - 3 * step)
        c1 = _snap_listed(snap, cw - step)
        p1 = _snap_listed(snap, pw + step)
        reasons["call_1"] = f"one step inside the call OI wall at {cw:.0f}"
        reasons["put_1"] = f"one step inside the put OI wall at {pw:.0f}"
    elif m == "support_resistance" and (support or resistance):
        c1 = _snap_listed(snap, resistance) if resistance else _nearest_by_delta(
            snap, "CE", cfg.strike_short_delta, "SELL", cfg, fallback_iv)
        p1 = _snap_listed(snap, support) if support else _nearest_by_delta(
            snap, "PE", cfg.strike_short_delta, "SELL", cfg, fallback_iv)
        reasons["call_1"] = f"at resistance {c1:.0f}" if resistance else "delta fallback (no resistance)"
        reasons["put_1"] = f"at support {p1:.0f}" if support else "delta fallback (no support)"
    elif m == "premium" and cfg.strike_target_premium > 0:
        c1 = min((r.strike for r in snap.rows if r.strike >= snap.spot and r.call_ltp),
                 key=lambda k: abs((next(r for r in snap.rows if r.strike == k).call_ltp or 0)
                                   - cfg.strike_target_premium), default=atm)
        p1 = min((r.strike for r in snap.rows if r.strike <= snap.spot and r.put_ltp),
                 key=lambda k: abs((next(r for r in snap.rows if r.strike == k).put_ltp or 0)
                                   - cfg.strike_target_premium), default=atm)
        reasons["call_1"] = f"call mid closest to target premium {cfg.strike_target_premium:.0f}"
        reasons["put_1"] = f"put mid closest to target premium {cfg.strike_target_premium:.0f}"
    else:  # delta (and 'probability')
        c1 = _nearest_by_delta(snap, "CE", cfg.strike_short_delta, "SELL", cfg, fallback_iv)
        p1 = _nearest_by_delta(snap, "PE", cfg.strike_short_delta, "SELL", cfg, fallback_iv)
        reasons["call_1"] = f"call |delta| ~ {cfg.strike_short_delta:.2f}"
        reasons["put_1"] = f"put |delta| ~ {cfg.strike_short_delta:.2f}"
        if m not in ("delta", "probability"):
            notes.append(f"strike method '{m}' had no input; fell back to delta.")

    levels["call_1"], levels["put_1"] = c1, p1

    # --- wings (call_2 / put_2) --------------------------------
    if cfg.strike_wing_width_pts > 0:
        levels["call_2"] = _snap_listed(snap, c1 + cfg.strike_wing_width_pts)
        levels["put_2"] = _snap_listed(snap, p1 - cfg.strike_wing_width_pts)
        reasons["call_2"] = f"short call + {cfg.strike_wing_width_pts:.0f} pt"
        reasons["put_2"] = f"short put - {cfg.strike_wing_width_pts:.0f} pt"
    else:
        levels["call_2"] = _nearest_by_delta(snap, "CE", cfg.strike_wing_delta, "BUY", cfg, fallback_iv)
        levels["put_2"] = _nearest_by_delta(snap, "PE", cfg.strike_wing_delta, "BUY", cfg, fallback_iv)
        reasons["call_2"] = f"call wing |delta| ~ {cfg.strike_wing_delta:.2f}"
        reasons["put_2"] = f"put wing |delta| ~ {cfg.strike_wing_delta:.2f}"
    # keep wings strictly outside the shorts
    if levels["call_2"] <= c1:
        levels["call_2"] = _snap_listed(snap, c1 + 2 * step)
    if levels["put_2"] >= p1:
        levels["put_2"] = _snap_listed(snap, p1 - 2 * step)

    per_leg: dict[str, dict[str, Any]] = {}
    for name, k in levels.items():
        right = "PE" if "put" in name else "CE" if "call" in name else "CE"
        per_leg[name] = {
            "strike": k,
            "delta": round(_delta_of(snap, k, right, fallback_iv), 3),
            "call_oi": _oi_at(snap, k, "CE"),
            "put_oi": _oi_at(snap, k, "PE"),
        }

    return StrikePlan(method=m, levels=levels, reasons=reasons, per_leg=per_leg, notes=notes)
