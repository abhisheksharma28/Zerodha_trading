"""Phase 4 — Options Positioning.

OI walls, writing strength, price+OI build-up classification, auto
put-support / call-resistance, OI concentration and OI-wall migration.
Max pain is computed but treated as informational only.
"""

from __future__ import annotations

import math
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, OICluster, PositioningReport


def _writing_strength(net_chg: float, total_oi: float) -> float:
    if total_oi <= 0:
        return 50.0
    return round(50.0 + 50.0 * math.tanh(net_chg / (0.15 * total_oi)), 1)


def _walls(rows, side: str, spot: float, min_mult: float = 1.6, top: int = 4) -> list[OICluster]:
    ois = [(r.strike, getattr(r, f"{side}_oi")) for r in rows if getattr(r, f"{side}_oi") > 0]
    if not ois:
        return []
    mean = sum(o for _s, o in ois) / len(ois)
    kind = "CALL_WALL" if side == "call" else "PUT_WALL"
    big = [OICluster(s, o, kind) for s, o in ois if o >= mean * min_mult]
    big.sort(key=lambda c: -c.oi)
    return big[:top]


def analyse(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *,
    price_change_pct: float | None = None,
    history: list[dict[str, Any]] | None = None,
) -> PositioningReport:
    history = history or []
    rows = snap.rows
    tot_call_oi = sum(r.call_oi for r in rows)
    tot_put_oi = sum(r.put_oi for r in rows)
    net_call_chg = sum(r.call_chg_oi for r in rows)
    net_put_chg = sum(r.put_chg_oi for r in rows)
    have_chg = any(r.call_chg_oi or r.put_chg_oi for r in rows)

    call_ws = _writing_strength(net_call_chg, tot_call_oi) if have_chg else 50.0
    put_ws = _writing_strength(net_put_chg, tot_put_oi) if have_chg else 50.0
    call_unwind = have_chg and net_call_chg < -0.03 * max(tot_call_oi, 1)
    put_unwind = have_chg and net_put_chg < -0.03 * max(tot_put_oi, 1)

    # price + OI build-up (aggregate)
    total_chg = net_call_chg + net_put_chg
    state = "MIXED"
    if price_change_pct is not None and have_chg and abs(total_chg) > 0.01 * (tot_call_oi + tot_put_oi):
        up = price_change_pct > 0.05
        dn = price_change_pct < -0.05
        oi_up = total_chg > 0
        if up and oi_up:
            state = "LONG_BUILDUP"
        elif dn and oi_up:
            state = "SHORT_BUILDUP"
        elif up and not oi_up:
            state = "SHORT_COVERING"
        elif dn and not oi_up:
            state = "LONG_UNWINDING"

    call_walls = _walls(rows, "call", snap.spot)
    put_walls = _walls(rows, "put", snap.spot)
    all_walls = sorted(call_walls + put_walls, key=lambda c: -c.oi)[:6]

    below = [w for w in put_walls if w.strike <= snap.spot + snap.strike_step()]
    above = [w for w in call_walls if w.strike >= snap.spot - snap.strike_step()]
    put_support = max(below, key=lambda w: w.oi).strike if below else (
        min((r.strike for r in rows if r.strike <= snap.spot), default=None))
    call_resistance = max(above, key=lambda w: w.oi).strike if above else (
        max((r.strike for r in rows if r.strike >= snap.spot), default=None))

    strikes_oi = sorted(
        ((r.call_oi + r.put_oi) for r in rows), reverse=True)
    total_oi = sum(strikes_oi) or 1.0
    concentration = sum(strikes_oi[:3]) / total_oi

    # migration: has the support/resistance band shifted vs recent history?
    migration = "NA"
    prev_sup = [float(h["put_support"]) for h in history if h.get("put_support")]
    prev_res = [float(h["call_resistance"]) for h in history if h.get("call_resistance")]
    if len(prev_sup) >= 3 and put_support:
        base = sum(prev_sup[-3:]) / 3.0
        migration = "UP" if put_support > base + snap.strike_step() * 0.5 else \
                    "DOWN" if put_support < base - snap.strike_step() * 0.5 else "STABLE"
    elif len(prev_res) >= 3 and call_resistance:
        base = sum(prev_res[-3:]) / 3.0
        migration = "UP" if call_resistance > base + snap.strike_step() * 0.5 else \
                    "DOWN" if call_resistance < base - snap.strike_step() * 0.5 else "STABLE"

    # max pain (informational)
    max_pain = None
    if rows:
        def _pain(k: float) -> float:
            return sum(max(0.0, k - r.strike) * r.call_oi + max(0.0, r.strike - k) * r.put_oi
                       for r in rows)
        max_pain = min((r.strike for r in rows), key=_pain)

    notes: list[str] = []
    if not have_chg:
        notes.append("No change-in-OI yet (first snapshot) — writing strength shown as neutral 50.")
    if concentration > 0.55:
        notes.append(f"OI is concentrated ({concentration*100:.0f}% in the top 3 strikes) — expect pinning toward those levels.")

    return PositioningReport(
        total_call_oi=tot_call_oi, total_put_oi=tot_put_oi,
        call_writing_strength=call_ws, put_writing_strength=put_ws,
        call_unwinding=call_unwind, put_unwinding=put_unwind,
        price_oi_state=state,
        put_support=put_support, call_resistance=call_resistance,
        oi_walls=all_walls, oi_concentration=concentration,
        oi_migration=migration, max_pain=max_pain, notes=notes,
    )
