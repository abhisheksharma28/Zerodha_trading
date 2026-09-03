"""Phase 15 — Research & Validation for the adaptive backtest.

* Walk-forward: run the same config on successive out-of-sample windows and
  compare each window's Sharpe / return to the full-window reference
  (``sharpe_decay`` = in-sample minus mean OOS).
* Monte Carlo: bootstrap + reshuffle the realised trade P&L (reuses the
  platform's ``app.backtesting.robustness.monte_carlo``).
* Parameter sensitivity: sweep a few key config fields +/-20% and flag a
  lone spike at the base value as likely overfit.

Every underlying backtest carries the same synthetic-data caveat; this
section does not add confidence in a synthetic run, it only checks the
decision process is not fragile.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.adaptive_options.backtest import run_adaptive_backtest
from app.adaptive_options.config import AdaptiveConfig
from app.backtesting.robustness import monte_carlo
from app.config import Settings
from app.core.exceptions import ValidationError

_DEFAULT_SENS = ("no_trade_confidence_min", "suitability_min", "strike_short_delta")


def run_validation(
    db: Session,
    settings: Settings,
    *,
    underlying: str = "NIFTY",
    start: str,
    end: str,
    preset: str = "balanced",
    overrides: dict[str, Any] | None = None,
    n_folds: int = 3,
    mc_sims: int = 400,
    sensitivity_params: list[str] | None = None,
    data_source: str = "synthetic",
) -> dict[str, Any]:
    cfg = AdaptiveConfig.from_dict(overrides, preset=preset)
    d0, d1 = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if (d1 - d0).days < 60:
        raise ValidationError("Validation needs at least ~60 days between start and end.")

    def _bt(s: date, e: date, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return run_adaptive_backtest(
            db, settings, underlying=underlying, start=s.isoformat(), end=e.isoformat(),
            preset=preset, config={**(overrides or {}), **(extra or {})},
            data_source=data_source)

    full = _bt(d0, d1)
    if not full.get("available"):
        return {"available": False, "reason": full.get("reason")}
    is_sharpe = float(full["metrics"].get("sharpe_ratio") or 0.0)
    trade_pnls = [float(t["net_pnl"]) for t in full["trades"]]

    # --- walk-forward OOS windows ---------------------------------
    step = (d1 - d0).days // (n_folds + 1)
    folds: list[dict[str, Any]] = []
    for k in range(n_folds):
        ws = d0 + timedelta(days=step * (k + 1))
        we = d1 if k == n_folds - 1 else d0 + timedelta(days=step * (k + 2))
        r = _bt(ws, we)
        m = r.get("metrics", {}) if r.get("available") else {}
        folds.append({
            "window": [ws.isoformat(), we.isoformat()],
            "sharpe_ratio": m.get("sharpe_ratio"),
            "total_return_pct": m.get("total_return_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "total_trades": m.get("total_trades"),
        })
    oos_sharpes = [f["sharpe_ratio"] for f in folds if isinstance(f["sharpe_ratio"], (int, float))]
    sharpe_decay = round(is_sharpe - (mean(oos_sharpes) if oos_sharpes else 0.0), 3)
    oos_consistency = (
        round(sum(1 for s in oos_sharpes if s > 0) / len(oos_sharpes), 2) if oos_sharpes else None
    )

    # --- Monte Carlo -------------------------------------------
    if len(trade_pnls) >= 5:
        mc = monte_carlo(trade_pnls, initial_capital=float(cfg.account_capital), n_sims=mc_sims)
    else:
        mc = {"available": False, "reason": f"only {len(trade_pnls)} trades — need >= 5 for Monte Carlo."}

    # --- parameter sensitivity -------------------------------
    sens: list[dict[str, Any]] = []
    for p in (sensitivity_params or list(_DEFAULT_SENS)):
        if p not in AdaptiveConfig.field_names():
            sens.append({"param": p, "error": "unknown config field"})
            continue
        base_v = getattr(cfg, p)
        if not isinstance(base_v, (int, float)) or base_v == 0:
            sens.append({"param": p, "error": "non-numeric or zero base value"})
            continue
        pts = []
        for mult in (0.8, 0.9, 1.0, 1.1, 1.2):
            v = type(base_v)(base_v * mult)
            r = _bt(d0, d1, {p: v})
            m = r.get("metrics", {}) if r.get("available") else {}
            pts.append({"value": round(float(v), 4), "mult": mult,
                        "sharpe_ratio": m.get("sharpe_ratio"),
                        "total_return_pct": m.get("total_return_pct"),
                        "total_trades": m.get("total_trades")})
        base_s = pts[2]["sharpe_ratio"] or 0.0
        neigh = [x["sharpe_ratio"] or 0.0 for x in (pts[1], pts[3])]
        spike = base_s > 0.3 and base_s > 2.0 * max(1e-6, mean(neigh))
        sens.append({"param": p, "base_value": round(float(base_v), 4),
                     "points": pts, "overfit_spike": bool(spike),
                     "verdict": "spike — likely overfit" if spike else "plateau — acceptable"})

    overfit = (sharpe_decay > max(0.5, 0.5 * abs(is_sharpe))) or any(s.get("overfit_spike") for s in sens)

    return {
        "available": True,
        "underlying": underlying, "window": [d0.isoformat(), d1.isoformat()],
        "config": {"preset": cfg.risk_profile, **cfg.to_dict()},
        "synthetic_data": full.get("synthetic_data", True),
        "in_sample": {k: full["metrics"].get(k) for k in
                      ("sharpe_ratio", "total_return_pct", "max_drawdown_pct", "total_trades",
                       "profit_factor", "win_rate_pct")},
        "walk_forward": {"folds": folds, "sharpe_decay": sharpe_decay,
                         "oos_positive_fraction": oos_consistency},
        "monte_carlo": mc,
        "sensitivity": sens,
        "overfit_flag": bool(overfit),
        "verdict": ("FRAGILE / likely overfit — do not rely on this config"
                    if overfit else "robust to these perturbations"),
        "warnings": full.get("warnings", []),
    }
