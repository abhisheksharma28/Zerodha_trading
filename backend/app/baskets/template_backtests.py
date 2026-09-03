"""Pre-computed backtests for the starter basket templates.

Run ``python -m app.baskets.template_backtests`` to (re)build
``data/basket_template_backtests.json``; the API merges the stored summary
into each template so the catalog cards can show real, credible numbers
without every page load kicking off a backtest.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.baskets import backtest as bt
from app.baskets.spec import parse_spec
from app.baskets.templates import templates as _templates
from app.core.logging import get_logger

logger = get_logger(__name__)

STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "basket_template_backtests.json"
_DEFAULT_YEARS = 8.0
_SPARK_POINTS = 60


def _downsample(curve: list[list[Any]], n: int) -> list[float]:
    vals = [float(v) for _d, v in curve]
    if len(vals) <= n:
        return [round(v, 1) for v in vals]
    step = len(vals) / n
    return [round(vals[min(int(i * step), len(vals) - 1)], 1) for i in range(n)]


def _summary(key: str, result_dict: dict[str, Any]) -> dict[str, Any]:
    m = result_dict.get("metrics", {})
    oos = result_dict.get("oos") or {}
    keep = (
        "total_return_pct", "cagr_pct", "benchmark_return_pct", "excess_return_pct",
        "sharpe_ratio", "sortino_ratio", "calmar_ratio", "volatility_pct",
        "max_drawdown_pct", "beta", "alpha_pct", "information_ratio",
        "annual_turnover_pct", "monthly_win_rate_pct", "avg_holding_days",
        "best_year_pct", "worst_year_pct", "n_rebalances",
    )
    return {
        "key": key,
        "generated_at": datetime.now(UTC).isoformat(),
        "start": result_dict.get("start"),
        "end": result_dict.get("end"),
        "years": result_dict.get("years"),
        "benchmark": result_dict.get("benchmark"),
        "metrics": {k: m.get(k) for k in keep},
        "oos": {
            "in_sample": (oos.get("in_sample") or {}),
            "out_of_sample": (oos.get("out_of_sample") or {}),
        },
        "regime_breakdown": result_dict.get("regime_breakdown") or {},
        "spark": _downsample(result_dict.get("equity_curve") or [], _SPARK_POINTS),
    }


def run_all(db: Any, settings: Any, *, years: float = _DEFAULT_YEARS) -> dict[str, Any]:
    out: dict[str, Any] = {}
    tpls = _templates()
    for i, t in enumerate(tpls, 1):
        key = t["key"]
        t0 = time.time()
        try:
            spec = parse_spec(t["spec"])
            res = bt.run_backtest(
                db, settings, spec,
                years=years,
                capital=500_000.0,
                benchmark=t.get("benchmark", "NIFTY 50"),
                frequency=t.get("rebalance_frequency", "monthly"),
                drift_band_pct=float(t.get("drift_band_pct", 3.0)),
            )
            out[key] = _summary(key, res.to_dict())
            m = out[key]["metrics"]
            logger.info(
                "basket_template_backtest", key=key, i=i, n=len(tpls),
                cagr=m.get("cagr_pct"), excess=m.get("excess_return_pct"),
                sharpe=m.get("sharpe_ratio"), secs=round(time.time() - t0, 1),
            )
        except Exception as exc:  # noqa: BLE001 - one bad template must not stop the batch
            out[key] = {"key": key, "error": str(exc),
                        "generated_at": datetime.now(UTC).isoformat()}
            logger.warning("basket_template_backtest_failed", key=key, err=str(exc))
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps({"generated_at": datetime.now(UTC).isoformat(),
                                      "years": years, "templates": out}, indent=1))
    return out


def load() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("templates", {}) if isinstance(data, dict) else {}


if __name__ == "__main__":
    from app.config import get_settings
    from app.db.session import SessionLocal

    yrs = float(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_YEARS
    _db = SessionLocal()
    try:
        run_all(_db, get_settings(), years=yrs)
    finally:
        _db.close()
    print(f"wrote {STORE_PATH}")
