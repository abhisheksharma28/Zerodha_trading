"""OI + Levels + PCR baseline vs enhanced — the research workflow from the
options brief.

Establishes the clean ``oi_levels_pcr`` baseline, then re-enables one signal
family at a time (trend, volatility/IV, volume, price-action, DTE) and the
full engine, backtests each over the same window *and* over a held-out
out-of-sample tail, and reports whether each addition is a genuine,
repeatable improvement over the baseline or should be rejected.

Runs many backtests, so it is slow on real (bhavcopy) data — treat it as a
job, not a snappy request. On ``data_source='synthetic'`` it exercises the
comparison mechanics only and is not evidence of an edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.adaptive_options.backtest import run_adaptive_backtest
from app.adaptive_options.config import ANALYSIS_PROFILES
from app.config import Settings
from app.core.exceptions import ValidationError

_BASELINE = "oi_levels_pcr"

# each add-on = the config deltas that switch one signal family back on,
# layered on top of the baseline profile.
ADD_ONS: dict[str, dict[str, Any]] = {
    "trend": {"w_trend": 0.20, "regime_price_group_weight": 1.0,
              "w_regime_match": 0.25, "w_price_action_confirm": 0.10},
    "volatility_iv": {"w_volatility": 0.12, "w_volatility_match": 0.15},
    "volume": {"w_volume": 0.12},
    "price_action": {"w_price_action": 0.15, "w_price_action_confirm": 0.10},
    "dte_timing": {"w_dte_match": 0.06},
}

_KPI = ("total_return_pct", "win_rate_pct", "expectancy", "profit_factor",
        "max_drawdown_pct", "max_consecutive_losses", "total_trades", "sharpe_ratio")


@dataclass
class VariantRun:
    name: str
    full: dict[str, Any]
    in_sample: dict[str, Any]
    out_of_sample: dict[str, Any]

    def kpis(self, which: str = "full") -> dict[str, Any]:
        m = getattr(self, which).get("metrics", {})
        return {k: m.get(k) for k in _KPI}


@dataclass
class ComparisonReport:
    underlying: str
    window: dict[str, str]
    data_source: str
    synthetic: bool
    baseline: dict[str, Any]
    baseline_otm_claim: dict[str, Any]
    variants: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying, "window": self.window,
            "data_source": self.data_source, "synthetic": self.synthetic,
            "baseline": self.baseline, "baseline_otm_claim": self.baseline_otm_claim,
            "variants": self.variants, "notes": self.notes,
        }


def _split(start: str, end: str, oos_frac: float) -> tuple[str, str]:
    d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    span = (d1 - d0).days
    if span < 60:
        raise ValidationError("Need at least ~2 months between start and end for an IS/OOS split.")
    cut = d1 - timedelta(days=int(span * oos_frac))
    return cut.isoformat(), (cut + timedelta(days=1)).isoformat()


def _run(db, settings, *, underlying, s, e, cfg, preset, data_source, expiry_kind):
    r = run_adaptive_backtest(
        db, settings, underlying=underlying, start=s, end=e,
        config=cfg, preset=preset, data_source=data_source, expiry_kind=expiry_kind)
    return r if r.get("available") else {"available": False, "metrics": {}, "trades": [],
                                         "reason": r.get("reason", "unavailable")}


def _verdict(base: dict[str, Any], var: dict[str, Any], *, min_trades: int) -> tuple[str, list[str]]:
    reasons: list[str] = []
    bt, vt = base["full"].get("metrics", {}), var["full"].get("metrics", {})
    b_oos, v_oos = base["out_of_sample"].get("metrics", {}), var["out_of_sample"].get("metrics", {})
    if (vt.get("total_trades") or 0) < min_trades or (v_oos.get("total_trades") or 0) < min_trades:
        return "inconclusive", [f"< {min_trades} trades in-sample or out-of-sample"]

    def _n(d: dict[str, Any], k: str, dflt: float = 0.0) -> float:
        v = d.get(k)
        return float(v) if v is not None else dflt

    exp_better_full = _n(vt, "expectancy") > _n(bt, "expectancy")
    pf_ok_full = _n(vt, "profit_factor") >= _n(bt, "profit_factor") - 0.05
    dd_not_worse = _n(vt, "max_drawdown_pct") >= _n(bt, "max_drawdown_pct") * 1.20  # dd is negative
    exp_better_oos = _n(v_oos, "expectancy") > _n(b_oos, "expectancy")
    wr_oos_ok = _n(v_oos, "win_rate_pct") >= _n(b_oos, "win_rate_pct") - 3.0

    if not exp_better_full:
        reasons.append("no expectancy gain in-sample")
    if not pf_ok_full:
        reasons.append("profit factor drops")
    if not dd_not_worse:
        reasons.append("materially deeper drawdown")
    if not exp_better_oos:
        reasons.append("gain does not hold out-of-sample")
    if not wr_oos_ok:
        reasons.append("out-of-sample win rate falls")

    adopt = exp_better_full and pf_ok_full and dd_not_worse and exp_better_oos and wr_oos_ok
    return ("adopt" if adopt else "reject"), reasons or ["improves the baseline on every check"]


def run_comparison(
    db: Session,
    settings: Settings,
    *,
    underlying: str = "NIFTY",
    start: str,
    end: str,
    data_source: str = "auto",
    expiry_kind: str = "weekly",
    risk_preset: str = "balanced",
    add_ons: list[str] | None = None,
    oos_frac: float = 0.4,
    min_trades: int = 15,
) -> dict[str, Any]:
    chosen = add_ons or list(ADD_ONS)
    unknown = [a for a in chosen if a not in ADD_ONS]
    if unknown:
        raise ValidationError(f"Unknown add-ons {unknown}; choose from {sorted(ADD_ONS)}.")
    is_end, oos_start = _split(start, end, oos_frac)

    def _variant(name: str, cfg: dict[str, Any] | None, preset: str) -> VariantRun:
        return VariantRun(
            name=name,
            full=_run(db, settings, underlying=underlying, s=start, e=end, cfg=cfg,
                      preset=preset, data_source=data_source, expiry_kind=expiry_kind),
            in_sample=_run(db, settings, underlying=underlying, s=start, e=is_end, cfg=cfg,
                           preset=preset, data_source=data_source, expiry_kind=expiry_kind),
            out_of_sample=_run(db, settings, underlying=underlying, s=oos_start, e=end, cfg=cfg,
                               preset=preset, data_source=data_source, expiry_kind=expiry_kind),
        )

    base_cfg = {**ANALYSIS_PROFILES[_BASELINE], "analysis_profile": _BASELINE}
    baseline = _variant("baseline_oi_levels_pcr", base_cfg, risk_preset)

    rows: list[dict[str, Any]] = []
    for a in chosen:
        v = _variant(f"baseline+{a}", {**base_cfg, **ADD_ONS[a]}, risk_preset)
        verdict, why = _verdict(baseline.__dict__, v.__dict__, min_trades=min_trades)
        rows.append({
            "name": v.name, "add_on": a, "verdict": verdict, "reasons": why,
            "kpis_full": v.kpis("full"), "kpis_oos": v.kpis("out_of_sample"),
            "delta_vs_baseline_full": _delta(baseline.kpis("full"), v.kpis("full")),
        })

    full_engine = _variant("full_engine", None, risk_preset)
    fv, fw = _verdict(baseline.__dict__, full_engine.__dict__, min_trades=min_trades)
    rows.append({
        "name": "full_engine", "add_on": "ALL", "verdict": fv, "reasons": fw,
        "kpis_full": full_engine.kpis("full"), "kpis_oos": full_engine.kpis("out_of_sample"),
        "delta_vs_baseline_full": _delta(baseline.kpis("full"), full_engine.kpis("full")),
    })

    b_full = baseline.full.get("metrics", {})
    wr = b_full.get("win_rate_pct")
    n = b_full.get("total_trades") or 0
    claim = {
        "measured_win_rate_pct": wr,
        "trades": n,
        "supports_80_85_pct_claim": bool(wr is not None and wr >= 78.0 and n >= 30),
        "note": ("Baseline win rate meets the ~80-85% bar on a meaningful sample."
                 if (wr is not None and wr >= 78.0 and n >= 30)
                 else "Not supported: win rate below ~80% and/or fewer than 30 trades in this sample."),
    }

    synthetic = bool(baseline.full.get("synthetic_data") or data_source == "synthetic")
    notes = []
    if synthetic:
        notes.append("SYNTHETIC option chain — mechanics only, not evidence of an edge. "
                     "Re-run with data_source='bhavcopy' for real EOD-OI evidence.")
    if any(not r["kpis_full"].get("total_trades") for r in rows):
        notes.append("Some variants took very few / no trades — widen the window or loosen the floor.")

    return ComparisonReport(
        underlying=underlying.upper(),
        window={"start": start, "end": end, "is_end": is_end, "oos_start": oos_start},
        data_source=data_source, synthetic=synthetic,
        baseline={"kpis_full": baseline.kpis("full"), "kpis_oos": baseline.kpis("out_of_sample"),
                  "attribution": baseline.full.get("attribution", {})},
        baseline_otm_claim=claim,
        variants=rows,
        notes=notes,
    ).as_dict()


def _delta(base: dict[str, Any], var: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in _KPI:
        b, v = base.get(k), var.get(k)
        if isinstance(b, (int, float)) and isinstance(v, (int, float)):
            out[k] = round(v - b, 3)
    return out
