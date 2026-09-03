"""Phase 5 (greeks) — per-strike and ATM greeks across the chain.

Uses the shared ``app.options.greeks`` Black-Scholes. Per-strike IV comes
from the chain; where a strike has no IV it falls back to the ATM IV, then
to a supplied realized-vol estimate, so the surface is always complete
enough to aggregate.
"""

from __future__ import annotations

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot, GreeksReport
from app.options.greeks import black_scholes


def _fallback_vol(snap: ChainSnapshot, realized_vol: float | None) -> float:
    ivs = [v for r in snap.rows for v in (r.call_iv, r.put_iv) if v and v > 0]
    if ivs:
        return sorted(ivs)[len(ivs) // 2]
    return realized_vol if (realized_vol and realized_vol > 0) else 0.14


def chain(
    snap: ChainSnapshot, cfg: AdaptiveConfig, *, realized_vol: float | None = None,
) -> GreeksReport:
    spot, t = snap.spot, snap.t_years
    fb = _fallback_vol(snap, realized_vol)
    per: list[dict] = []
    gamma_by_strike: list[tuple[float, float]] = []

    for r in snap.rows:
        c_iv = r.call_iv if (r.call_iv and r.call_iv > 0) else fb
        p_iv = r.put_iv if (r.put_iv and r.put_iv > 0) else fb
        cg = black_scholes(spot, r.strike, t, c_iv, is_call=True)
        pg = black_scholes(spot, r.strike, t, p_iv, is_call=False)
        agg_gamma = cg.gamma * r.call_oi + pg.gamma * r.put_oi
        gamma_by_strike.append((r.strike, agg_gamma))
        per.append({
            "strike": r.strike,
            "call": cg.as_dict(), "put": pg.as_dict(),
            "call_oi": r.call_oi, "put_oi": r.put_oi,
        })

    atm = snap.atm_strike()
    atm_row = next((p for p in per if p["strike"] == atm), None)
    atm_call = atm_row["call"] if atm_row else {}
    atm_put = atm_row["put"] if atm_row else {}

    gamma_zone = None
    if gamma_by_strike:
        gamma_by_strike.sort(key=lambda x: -x[1])
        top = sorted(s for s, _g in gamma_by_strike[:3])
        gamma_zone = (top[0], top[-1])

    notes: list[str] = []
    missing = sum(1 for r in snap.rows if not r.call_iv or not r.put_iv)
    if missing:
        notes.append(f"{missing} strike(s) had no IV — greeks there use the median-IV fallback ({fb:.1%}).")
    if snap.dte < 2:
        notes.append("Near expiry: gamma and theta are changing fast intrabar; treat greeks as a snapshot only.")

    return GreeksReport(atm_call=atm_call, atm_put=atm_put, per_strike=per,
                        gamma_zone=gamma_zone, notes=notes)
