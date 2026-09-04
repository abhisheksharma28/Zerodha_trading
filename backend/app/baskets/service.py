"""Basket CRUD + backtest orchestration (DB-facing)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.baskets import backtest as bt
from app.baskets.spec import FREQUENCIES, SpecError, parse_spec
from app.baskets.templates import categories as _template_categories
from app.baskets.templates import templates as _starter_templates
from app.config import Settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.basket import Basket, BasketRebalanceEvent

logger = get_logger(__name__)


def _summary_of_backtest(bt_dict: dict[str, Any] | None) -> dict[str, Any] | None:
    if not bt_dict:
        return None
    m = bt_dict.get("metrics", {})
    oos = bt_dict.get("oos") or {}
    return {
        "generated_at": bt_dict.get("generated_at"),
        "years": bt_dict.get("years"),
        "cagr_pct": m.get("cagr_pct"),
        "total_return_pct": m.get("total_return_pct"),
        "benchmark_return_pct": m.get("benchmark_return_pct"),
        "excess_return_pct": m.get("excess_return_pct"),
        "sharpe_ratio": m.get("sharpe_ratio"),
        "sortino_ratio": m.get("sortino_ratio"),
        "calmar_ratio": m.get("calmar_ratio"),
        "beta": m.get("beta"),
        "alpha_pct": m.get("alpha_pct"),
        "max_drawdown_pct": m.get("max_drawdown_pct"),
        "annual_turnover_pct": m.get("annual_turnover_pct"),
        "monthly_win_rate_pct": m.get("monthly_win_rate_pct"),
        "oos_return_pct": (oos.get("out_of_sample") or {}).get("return_pct"),
        "oos_sharpe_ratio": (oos.get("out_of_sample") or {}).get("sharpe_ratio"),
    }


def serialize(b: Basket, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(b.id),
        "name": b.name,
        "description": b.description,
        "category": b.category,
        "risk_level": b.risk_level,
        "objective": b.objective,
        "horizon": b.horizon,
        "investment_style": b.investment_style,
        "how_it_works": b.how_it_works or [],
        "internal": bool(b.internal),
        "benchmark": b.benchmark,
        "rebalance_frequency": b.rebalance_frequency,
        "drift_band_pct": float(b.drift_band_pct),
        "capital": float(b.capital),
        "status": b.status,
        "paper_account_id": str(b.paper_account_id) if b.paper_account_id else None,
        "last_rebalanced_at": b.last_rebalanced_at.isoformat() if b.last_rebalanced_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        "sleeves": (b.spec or {}).get("sleeves", []),
        "n_sleeves": len((b.spec or {}).get("sleeves", [])),
        "backtest_summary": _summary_of_backtest(b.last_backtest),
    }
    if full:
        out["spec"] = b.spec
        out["last_backtest"] = b.last_backtest
    return out


def list_baskets(db: Session, *, include_archived: bool = False) -> list[dict[str, Any]]:
    stmt = select(Basket).order_by(Basket.created_at.desc())
    if not include_archived:
        stmt = stmt.where(Basket.status != "archived")
    return [serialize(b) for b in db.execute(stmt).scalars().all()]


def get_basket(db: Session, basket_id: str) -> Basket:
    try:
        bid = uuid.UUID(str(basket_id))
    except ValueError as exc:
        raise NotFoundError("basket not found") from exc
    b = db.get(Basket, bid)
    if b is None:
        raise NotFoundError("basket not found")
    return b


def _validate_common(
    *, frequency: str, drift_band_pct: float, capital: float, benchmark: str
) -> None:
    if frequency not in FREQUENCIES:
        raise ValidationError(f"rebalance_frequency must be one of {FREQUENCIES}")
    if not 0.0 <= drift_band_pct <= 25.0:
        raise ValidationError("drift_band_pct must be in [0, 25]")
    if capital < 10_000:
        raise ValidationError("capital must be at least 10,000")
    if not benchmark.strip():
        raise ValidationError("benchmark is required")


def create_basket(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValidationError("name is required")
    try:
        spec = parse_spec(payload.get("spec"))
    except SpecError as exc:
        raise ValidationError(str(exc)) from exc

    frequency = str(payload.get("rebalance_frequency") or "monthly")
    drift = float(payload.get("drift_band_pct", 3.0))
    capital = float(payload.get("capital", 500_000))
    benchmark = str(payload.get("benchmark") or "NIFTY 50")
    _validate_common(
        frequency=frequency, drift_band_pct=drift, capital=capital, benchmark=benchmark
    )

    def _s(key: str) -> str | None:
        v = payload.get(key)
        return (str(v).strip() or None) if v else None

    risk_level = payload.get("risk_level")
    try:
        risk_level = int(risk_level) if risk_level is not None else None
    except (TypeError, ValueError):
        risk_level = None
    if risk_level is not None and not 1 <= risk_level <= 5:
        risk_level = None
    how = payload.get("how_it_works")
    how = [str(x) for x in how] if isinstance(how, list) else None

    b = Basket(
        name=name,
        description=_s("description"),
        category=_s("category"),
        risk_level=risk_level,
        objective=_s("objective"),
        horizon=_s("horizon"),
        investment_style=_s("investment_style"),
        how_it_works=how,
        internal=bool(payload.get("internal", False)),
        benchmark=benchmark,
        rebalance_frequency=frequency,
        drift_band_pct=drift,
        capital=capital,
        spec=spec.to_dict(),
        status="draft",
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    logger.info("basket_created", basket_id=str(b.id), sleeves=len(spec.sleeves))
    return serialize(b, full=True)


def update_basket(db: Session, basket_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    b = get_basket(db, basket_id)
    if "name" in payload:
        name = str(payload["name"] or "").strip()
        if not name:
            raise ValidationError("name cannot be empty")
        b.name = name
    if "description" in payload:
        desc = payload["description"]
        b.description = str(desc).strip() or None if desc else None
    if "category" in payload:
        cat = payload["category"]
        b.category = str(cat).strip() or None if cat else None
    for f in ("objective", "horizon", "investment_style"):
        if f in payload:
            v = payload[f]
            setattr(b, f, str(v).strip() or None if v else None)
    if "risk_level" in payload:
        rl = payload["risk_level"]
        try:
            rl = int(rl) if rl is not None else None
        except (TypeError, ValueError):
            rl = None
        b.risk_level = rl if (rl is None or 1 <= rl <= 5) else b.risk_level
    if "how_it_works" in payload:
        how = payload["how_it_works"]
        b.how_it_works = [str(x) for x in how] if isinstance(how, list) else None
    if "internal" in payload:
        b.internal = bool(payload["internal"])
    if "benchmark" in payload and payload["benchmark"]:
        b.benchmark = str(payload["benchmark"])
    if "rebalance_frequency" in payload and payload["rebalance_frequency"]:
        b.rebalance_frequency = str(payload["rebalance_frequency"])
    if "drift_band_pct" in payload:
        b.drift_band_pct = float(payload["drift_band_pct"])
    if "capital" in payload:
        b.capital = float(payload["capital"])

    _validate_common(
        frequency=b.rebalance_frequency,
        drift_band_pct=float(b.drift_band_pct),
        capital=float(b.capital),
        benchmark=b.benchmark,
    )

    if "spec" in payload:
        try:
            spec = parse_spec(payload["spec"])
        except SpecError as exc:
            raise ValidationError(str(exc)) from exc
        b.spec = spec.to_dict()
        b.last_backtest = None  # stale once the definition changes

    db.commit()
    db.refresh(b)
    return serialize(b, full=True)


def delete_basket(db: Session, basket_id: str) -> dict[str, Any]:
    b = get_basket(db, basket_id)
    if b.status == "draft":
        db.delete(b)
        db.commit()
        return {"deleted": True, "id": basket_id}
    b.status = "archived"
    db.commit()
    return {"deleted": False, "archived": True, "id": basket_id}


def run_backtest(
    db: Session, settings: Settings, basket_id: str, *, years: float = 5.0
) -> dict[str, Any]:
    b = get_basket(db, basket_id)
    try:
        spec = parse_spec(b.spec)
    except SpecError as exc:
        raise ValidationError(f"stored spec is invalid: {exc}") from exc

    result = bt.run_backtest(
        db, settings, spec,
        years=years,
        capital=float(b.capital),
        benchmark=b.benchmark,
        frequency=b.rebalance_frequency,
        drift_band_pct=float(b.drift_band_pct),
    )
    payload = result.to_dict()
    payload["generated_at"] = datetime.now(UTC).isoformat()

    b.last_backtest = payload
    db.add(
        BasketRebalanceEvent(
            basket_id=b.id,
            as_of=datetime.now(UTC),
            mode="backtest",
            target_weights=(result.rebalances[-1].weights if result.rebalances else {}),
            orders=[],
            applied=False,
            note=f"backtest {result.years}y — CAGR {payload['metrics'].get('cagr_pct')}%",
        )
    )
    db.commit()
    return payload


def screen_universe(
    db: Session, settings: Settings, name: str, *,
    gate_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the eligibility screen against *live* daily candles for every
    member of a named universe: which names are tradeable right now and,
    for the rest, why not. Read-only research / ops view — does not touch
    the scoring path."""
    from datetime import timedelta

    from app.backtesting.adhoc import fetch_candles
    from app.baskets import eligibility as elig
    from app.baskets import universes as U

    try:
        meta = U.describe(name)
    except KeyError as exc:
        raise NotFoundError(str(exc)) from exc

    members = meta["members"]
    end_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=420)
    candles, _skipped = fetch_candles(
        db, settings, symbols=members, timeframe="1d",
        start=start_dt.date().isoformat(), end=end_dt.date().isoformat(),
    )
    bars_by_symbol: dict[str, Any] = {}
    for want in members:
        for got, bars in candles.items():
            if got.upper() == want.upper():
                bars_by_symbol[want] = bars
                break

    gate = elig.DEFAULT_GATE
    if gate_overrides:
        base = gate.to_dict()
        base.update({k: v for k, v in gate_overrides.items() if k in base})
        gate = elig.EligibilityGate(**base)

    eligible, assessed = elig.screen_members(members, bars_by_symbol, end_dt, gate=gate)
    return {
        "universe": {k: v for k, v in meta.items() if k != "members"},
        "as_of": end_dt.date().isoformat(),
        "gate": gate.to_dict(),
        "n_members": len(members),
        "n_eligible": len(eligible),
        "eligible": eligible,
        "ineligible": [a.to_dict() for a in assessed if not a.eligible],
        "assessed": [a.to_dict() for a in assessed],
    }


def universe_catalog() -> dict[str, Any]:
    from app.baskets import universes as U

    return {"universes": U.catalog()}


def _merge_backtests(items: list[dict[str, Any]], stored: dict[str, Any]) -> None:
    for t in items:
        b = stored.get(t["key"])
        if not b:
            continue
        if "error" not in b:
            t["backtest"] = b
        if b.get("min_funds"):
            t["min_funds"] = b["min_funds"]


def starter_templates(*, include_internal: bool = False) -> dict[str, Any]:
    """The 12 flagship products the catalog shows. ``include_internal`` also
    returns the ~14 back-pocket template models under ``internal_models``."""
    from app.baskets import catalog as _catalog
    from app.baskets.template_backtests import load as _load_template_backtests
    from app.baskets.template_backtests import load_catalog as _load_catalog_backtests

    cat_stored = _load_catalog_backtests()
    products = _catalog.flagship()
    _merge_backtests(products, cat_stored)

    out: dict[str, Any] = {
        "categories": _catalog.categories(),
        "journeys": _catalog.journeys(),
        "risk_labels": {str(k): v for k, v in _catalog.risk_labels().items()},
        "templates": products,
        "backtests_generated_at": (
            next(iter(cat_stored.values()), {}).get("generated_at") if cat_stored else None
        ),
    }
    if include_internal:
        internal = _starter_templates()
        _merge_backtests(internal, _load_template_backtests())
        out["internal_models"] = internal
        out["internal_categories"] = _template_categories()
    return out
