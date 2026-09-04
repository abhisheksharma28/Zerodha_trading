"""Tactical asset-allocation overlay for the strategic multi-asset baskets.

A strategic basket (Golden Wealth, All Weather) fixes a target weight per
asset sleeve. This module lets the internal engine *tilt within hard
bands* each rebalance — e.g. lean the equity sleeve up to 55% when the
trend is strong, back to 35% when it breaks — without ever leaving the
declared range, and with a per-rebalance step cap so turnover stays low.

Pure functions over close lists. ``tilt(model, sleeves, closes)`` is the
entry point; ``MODELS`` names the folded-in classics (permanent
portfolio, 60/40, risk-parity-lite) plus the default trend tilt.
"""

from __future__ import annotations

from typing import Any

from app.baskets import factors as _f

# a sleeve's allocation band: (strategic, floor, ceiling) in percent
Band = tuple[float, float, float]

# canonical defensive buckets — used to steer tilts in a weak regime and
# by the permanent-portfolio / 60-40 models
_DEFENSIVE_HINTS = ("bond", "gsec", "gold", "silver", "cash", "liquid", "debt")

MODELS: tuple[str, ...] = (
    "strategic",
    "trend_tilt",
    "risk_parity_lite",
    "permanent_portfolio",
    "sixty_forty",
)


def _is_defensive(sleeve_id: str, name: str) -> bool:
    hay = f"{sleeve_id} {name}".lower()
    return any(h in hay for h in _DEFENSIVE_HINTS)


def _clamp_to_bands(weights: dict[str, float], bands: dict[str, Band]) -> dict[str, float]:
    """Clamp each weight into [floor, ceiling] then renormalise to 100,
    re-clamping until stable (a few passes are always enough)."""
    w = dict(weights)
    for _ in range(12):
        w = {k: min(max(v, bands[k][1]), bands[k][2]) for k, v in w.items()}
        tot = sum(w.values())
        if abs(tot - 100.0) < 1e-6:
            break
        # distribute the residual over sleeves that still have room in the
        # needed direction, proportional to that room
        resid = 100.0 - tot
        room = {
            k: (bands[k][2] - w[k]) if resid > 0 else (w[k] - bands[k][1])
            for k in w
        }
        rtot = sum(max(r, 0.0) for r in room.values())
        if rtot < 1e-9:
            break
        for k in w:
            w[k] += resid * (max(room[k], 0.0) / rtot)
    return w


def _limit_step(
    tilted: dict[str, float], bands: dict[str, Band], max_step: float
) -> dict[str, float]:
    """No sleeve moves more than ``max_step`` points from its strategic
    weight in one rebalance."""
    if max_step <= 0:
        return tilted
    capped = {
        k: min(max(v, bands[k][0] - max_step), bands[k][0] + max_step)
        for k, v in tilted.items()
    }
    return _clamp_to_bands(capped, bands)


def _scores(sleeves: dict[str, dict[str, Any]], closes: dict[str, list[float]]) -> dict[str, float]:
    """A 0..1 attractiveness score per sleeve — blended trend + 6m momentum
    of its asset. Missing history -> neutral 0.5."""
    raw: dict[str, float] = {}
    for sid, meta in sleeves.items():
        c = closes.get(meta["asset"]) or []
        tr = _f.trend_composite(c, 200)
        mo = _f.roc(c, 126)
        if tr is None and mo is None:
            raw[sid] = 0.5
            continue
        parts = []
        if tr is not None:
            parts.append(max(min(tr, 1.0), -1.0))
        if mo is not None:
            parts.append(max(min(mo / 30.0, 1.0), -1.0))  # +/-30% 6m -> +/-1
        raw[sid] = (sum(parts) / len(parts) + 1.0) / 2.0
    return raw


def _model_strategic(sleeves: dict[str, dict[str, Any]], bands: dict[str, Band], **_: Any) -> dict[str, float]:
    return {k: bands[k][0] for k in sleeves}


def _model_trend_tilt(
    sleeves: dict[str, dict[str, Any]], bands: dict[str, Band],
    closes: dict[str, list[float]], regime: str | None = None, **_: Any,
) -> dict[str, float]:
    sc = _scores(sleeves, closes)
    mean = sum(sc.values()) / len(sc)
    out: dict[str, float] = {}
    for sid in sleeves:
        span = bands[sid][2] - bands[sid][1]
        # move up to +/-40% of the band width per unit score deviation
        delta = (sc[sid] - mean) * span * 0.8
        if regime == "risk_off" and not _is_defensive(sid, sleeves[sid].get("name", "")):
            delta = min(delta, 0.0)  # in a risk-off tape, never tilt growth UP
        if regime == "risk_off" and _is_defensive(sid, sleeves[sid].get("name", "")):
            delta += span * 0.15
        out[sid] = bands[sid][0] + delta
    return out


def _model_risk_parity_lite(
    sleeves: dict[str, dict[str, Any]], bands: dict[str, Band],
    closes: dict[str, list[float]], **_: Any,
) -> dict[str, float]:
    inv: dict[str, float] = {}
    for sid, meta in sleeves.items():
        vol = _f.total_vol(closes.get(meta["asset"]) or [], 126)
        inv[sid] = 1.0 / vol if vol and vol > 1e-9 else 0.0
    tot = sum(inv.values())
    if tot <= 0:
        return _model_strategic(sleeves, bands)
    return {sid: 100.0 * v / tot for sid, v in inv.items()}


def _model_permanent_portfolio(
    sleeves: dict[str, dict[str, Any]], bands: dict[str, Band], **_: Any,
) -> dict[str, float]:
    n = len(sleeves)
    return dict.fromkeys(sleeves, 100.0 / n)


def _model_sixty_forty(
    sleeves: dict[str, dict[str, Any]], bands: dict[str, Band], **_: Any,
) -> dict[str, float]:
    growth = [s for s in sleeves if not _is_defensive(s, sleeves[s].get("name", ""))]
    defensive = [s for s in sleeves if s not in growth]
    out: dict[str, float] = {}
    if growth:
        for s in growth:
            out[s] = 60.0 / len(growth)
    if defensive:
        for s in defensive:
            out[s] = 40.0 / len(defensive)
    for s in sleeves:
        out.setdefault(s, bands[s][0])
    return out


_DISPATCH = {
    "strategic": _model_strategic,
    "trend_tilt": _model_trend_tilt,
    "risk_parity_lite": _model_risk_parity_lite,
    "permanent_portfolio": _model_permanent_portfolio,
    "sixty_forty": _model_sixty_forty,
}


def tilt(
    model: str,
    sleeves: dict[str, dict[str, Any]],
    closes: dict[str, list[float]],
    *,
    regime: str | None = None,
    max_step_pct: float = 8.0,
) -> tuple[dict[str, float], list[str]]:
    """-> ({sleeve_id: tilted weight_pct summing to 100}, notes).

    ``sleeves`` maps sleeve id -> {"asset": symbol, "band": (strat, lo, hi),
    "name": str}. Unknown model falls back to strategic.
    """
    if not sleeves:
        return {}, []
    bands: dict[str, Band] = {k: tuple(v["band"]) for k, v in sleeves.items()}  # type: ignore[misc]
    fn = _DISPATCH.get(model, _model_strategic)
    proposed = fn(sleeves=sleeves, bands=bands, closes=closes, regime=regime)
    bounded = _limit_step(_clamp_to_bands(proposed, bands), bands, max_step_pct)
    # round lightly and fix any residual on the largest sleeve
    out = {k: round(v, 2) for k, v in bounded.items()}
    drift = round(100.0 - sum(out.values()), 2)
    if abs(drift) >= 0.01:
        big = max(out, key=lambda k: out[k])
        out[big] = round(out[big] + drift, 2)

    notes: list[str] = []
    moved = sorted(
        ((k, out[k] - bands[k][0]) for k in out if abs(out[k] - bands[k][0]) >= 1.0),
        key=lambda kv: abs(kv[1]), reverse=True,
    )
    if moved:
        desc = ", ".join(f"{k} {d:+.0f}pt" for k, d in moved[:4])
        notes.append(f"tactical ({model}): {desc}")
    return out, notes
