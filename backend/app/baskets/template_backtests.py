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
CATALOG_STORE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "basket_catalog_backtests.json"
)
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
        "up_capture_pct", "down_capture_pct",
        "rolling_12m_min_pct", "rolling_12m_median_pct", "rolling_12m_max_pct",
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


def _min_funds(db: Any, settings: Any, spec: Any) -> dict[str, Any] | None:
    """Cost to hold one share of every member — shown on the template card so
    a user knows the floor before deploying."""
    from app.baskets.paper import unit_cost_for_spec

    try:
        uc = unit_cost_for_spec(db, settings, spec)
    except Exception as exc:  # noqa: BLE001 - a missing price must not stop the batch
        logger.warning("basket_template_min_funds_failed", err=str(exc))
        return None
    return {
        "unit_cost": uc["unit_cost"],
        "n_members": uc["n_members"],
        "n_priced": uc["n_priced"],
        "est_holdings": uc.get("est_holdings"),
        "as_of": uc["as_of"],
    }


def backfill_min_funds(db: Any, settings: Any) -> dict[str, Any]:
    """Patch ``min_funds`` into the existing store without re-running the
    (expensive) backtests. ``python -m app.baskets.template_backtests min-funds``."""
    if not STORE_PATH.exists():
        raise FileNotFoundError(STORE_PATH)
    data = json.loads(STORE_PATH.read_text())
    tpls = data.get("templates", {})
    by_key = {t["key"]: t for t in _templates()}
    for key, entry in tpls.items():
        t = by_key.get(key)
        if not t:
            continue
        try:
            spec = parse_spec(t["spec"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("basket_template_min_funds_spec_bad", key=key, err=str(exc))
            continue
        entry["min_funds"] = _min_funds(db, settings, spec)
        logger.info(
            "basket_template_min_funds", key=key,
            unit_cost=(entry["min_funds"] or {}).get("unit_cost"),
        )
    STORE_PATH.write_text(json.dumps(data, indent=1))
    return tpls


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
            out[key]["min_funds"] = _min_funds(db, settings, spec)
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


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("templates", {}) if isinstance(data, dict) else {}


def load() -> dict[str, Any]:
    return _load(STORE_PATH)


def load_catalog() -> dict[str, Any]:
    return _load(CATALOG_STORE_PATH)


def run_catalog(db: Any, settings: Any, *, years: float = _DEFAULT_YEARS) -> dict[str, Any]:
    """Backtest the 12 flagship products into ``basket_catalog_backtests.json``.
    ``python -m app.baskets.template_backtests catalog [years]``."""
    from app.baskets.catalog import flagship

    out: dict[str, Any] = {}
    products = flagship()
    for i, p in enumerate(products, 1):
        key = p["key"]
        t0 = time.time()
        try:
            spec = parse_spec(p["spec"])
            res = bt.run_backtest(
                db, settings, spec, years=years, capital=500_000.0,
                benchmark=p.get("benchmark", "NIFTY 50"),
                frequency=p.get("rebalance_frequency", "monthly"),
                drift_band_pct=float(p.get("drift_band_pct", 3.0)),
            )
            out[key] = _summary(key, res.to_dict())
            out[key]["min_funds"] = _min_funds(db, settings, spec)
            m = out[key]["metrics"]
            logger.info(
                "basket_catalog_backtest", key=key, i=i, n=len(products),
                cagr=m.get("cagr_pct"), excess=m.get("excess_return_pct"),
                sharpe=m.get("sharpe_ratio"), secs=round(time.time() - t0, 1),
            )
        except Exception as exc:  # noqa: BLE001 - one bad product must not stop the batch
            out[key] = {"key": key, "error": str(exc),
                        "generated_at": datetime.now(UTC).isoformat()}
            logger.warning("basket_catalog_backtest_failed", key=key, err=str(exc))
    CATALOG_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_STORE_PATH.write_text(json.dumps(
        {"generated_at": datetime.now(UTC).isoformat(), "years": years, "templates": out},
        indent=1,
    ))
    return out


if __name__ == "__main__":
    from app.config import get_settings
    from app.db.session import SessionLocal

    if len(sys.argv) > 1 and sys.argv[1] == "min-funds":
        _db = SessionLocal()
        try:
            backfill_min_funds(_db, get_settings())
        finally:
            _db.close()
        print(f"patched min_funds into {STORE_PATH}")
        raise SystemExit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "catalog":
        yrs2 = float(sys.argv[2]) if len(sys.argv) > 2 else _DEFAULT_YEARS
        _db = SessionLocal()
        try:
            run_catalog(_db, get_settings(), years=yrs2)
        finally:
            _db.close()
        print(f"wrote {CATALOG_STORE_PATH}")
        raise SystemExit(0)

    yrs = float(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_YEARS
    _db = SessionLocal()
    try:
        run_all(_db, get_settings(), years=yrs)
    finally:
        _db.close()
    print(f"wrote {STORE_PATH}")
