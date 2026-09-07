"""Run one screener sweep: build the universe, pull fundamentals +
technicals for each name, score cross-sectionally, replace the ratings
table.

Serialised across workers by a Postgres advisory lock. Safe to call from
the daily scheduler or the manual ``POST /screener/sweep`` endpoint.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.market_data.instruments import resolve_instrument_token
from app.models.instrument import Instrument
from app.models.screener import ScreenerRating, ScreenerRun
from app.providers.fundamentals import get_fundamentals_provider
from app.screener import metrics as M
from app.screener import scoring, universe
from app.services import broker_service

logger = get_logger(__name__)

_LOCK_KEY = 776640
_FUND_WORKERS = 4


def run_sweep(db: Session, settings: Settings, *, trigger: str = "schedule") -> dict[str, Any]:
    if not bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}).scalar()):
        return {"ok": False, "reason": "another screener sweep is already running"}
    run = ScreenerRun(started_at=datetime.now(UTC), trigger=trigger)
    db.add(run)
    db.commit()
    try:
        result = _sweep(db, settings, run)
        run.finished_at = datetime.now(UTC)
        run.universe_size = result["universe_size"]
        run.scored = result["scored"]
        run.buy = result["buy"]
        run.hold = result["hold"]
        run.avoid = result["avoid"]
        db.commit()
        return {"ok": True, **result}
    except Exception as exc:  # noqa: BLE001
        logger.exception("screener_sweep_failed")
        db.rollback()
        fresh = db.get(ScreenerRun, run.id)
        if fresh is not None:
            fresh.finished_at = datetime.now(UTC)
            fresh.error = str(exc)[:2000]
            db.commit()
        return {"ok": False, "reason": str(exc)}
    finally:
        db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY})
        db.commit()


def _sweep(db: Session, settings: Settings, run: ScreenerRun) -> dict[str, Any]:
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        raise RuntimeError(f"screener needs a connected Zerodha session for candles: {exc}") from exc

    provider = get_fundamentals_provider(settings)
    syms = universe.build(db, client, cap=settings.screener_universe_max)
    logger.info("screener_sweep_start", universe=len(syms), provider=provider.name)

    names: dict[str, str | None] = dict(
        db.execute(
            select(Instrument.tradingsymbol, Instrument.name).where(
                Instrument.exchange == "NSE", Instrument.tradingsymbol.in_(syms)
            )
        ).tuples().all()
    )

    # fundamentals in a small thread pool (Yahoo tolerates a little concurrency)
    def _fund(sym: str) -> M.StockMetrics:
        m = M.StockMetrics(symbol=sym, name=names.get(sym))
        try:
            km = provider.get_key_metrics(sym)
            pr = provider.get_company_profile(sym)
            M.from_fundamentals(
                m,
                km.data if getattr(km, "available", False) else None,
                pr.data if getattr(pr, "available", False) else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("screener_fundamentals_failed", symbol=sym, error=str(exc))
            m.missing.append("fundamentals")
        return m

    with ThreadPoolExecutor(max_workers=_FUND_WORKERS) as pool:
        rows = list(pool.map(_fund, syms))

    # technicals: sequential; Kite's historical limiter (3 req/s) self-throttles
    fd, td = M.candle_window()
    for i, m in enumerate(rows):
        try:
            token, _ts = resolve_instrument_token(f"NSE:{m.symbol}")
            candles = client.get_historical_candles(str(token), "day", fd, td)
            M.from_candles(m, candles)
        except Exception as exc:  # noqa: BLE001
            logger.warning("screener_candles_failed", symbol=m.symbol, error=str(exc))
            m.missing.append("candles")
        if (i + 1) % 50 == 0:
            logger.info("screener_sweep_progress", done=i + 1, total=len(rows))

    ratings = scoring.score_universe(
        rows,
        buy_min=settings.screener_buy_min_score,
        avoid_max=settings.screener_avoid_max_score,
        min_completeness=settings.screener_min_completeness,
    )

    as_of = datetime.now(UTC)
    db.execute(delete(ScreenerRating))
    by_sym = {mm.symbol: mm for mm in rows}
    buckets = {"BUY": 0, "HOLD": 0, "AVOID": 0}
    for r in ratings:
        mm = by_sym.get(r.symbol)
        buckets[r.verdict] = buckets.get(r.verdict, 0) + 1
        db.add(ScreenerRating(
            symbol=r.symbol, name=r.name, sector=r.sector,
            verdict=r.verdict, confidence=r.confidence,
            composite=r.composite,
            value_score=r.value_score, quality_score=r.quality_score,
            growth_score=r.growth_score, technical_score=r.technical_score,
            data_completeness=r.completeness,
            ltp=mm.ltp if mm else None,
            pct_from_52w_high=mm.pct_from_52w_high if mm else None,
            pct_from_52w_low=mm.pct_from_52w_low if mm else None,
            metrics=mm.to_dict() if mm else {},
            factors=r.factors,
            notes=r.notes,
            as_of=as_of,
        ))
    db.commit()

    logger.info("screener_sweep_done", scored=len(ratings), **buckets)
    return {
        "universe_size": len(syms),
        "scored": len(ratings),
        "buy": buckets["BUY"],
        "hold": buckets["HOLD"],
        "avoid": buckets["AVOID"],
        "as_of": as_of.isoformat(),
    }
