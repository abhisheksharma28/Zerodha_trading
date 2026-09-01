"""Stock Intelligence: a fast 'quick look' for any NSE instrument.

Combines the canonical instrument-master record, a live Zerodha quote
snapshot, and (if a provider is configured) a fundamentals summary. Every
section degrades independently — a missing quote or absent fundamentals
provider never breaks the response.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError, NotFoundError
from app.core.logging import get_logger
from app.providers.fundamentals import get_fundamentals_provider
from app.services import broker_service, instrument_service

logger = get_logger(__name__)


def _quote_snapshot(db: Session, settings: Settings, exchange: str, tradingsymbol: str) -> dict[str, Any]:
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        return {"available": False, "reason": str(exc)}
    key = f"{exchange}:{tradingsymbol}"
    try:
        q = client.get_quote([key]).get(key)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"quote fetch failed: {exc}"}
    if not q:
        return {"available": False, "reason": "instrument returned no quote"}
    ohlc = q.get("ohlc") or {}
    ltp = q.get("last_price")
    prev = ohlc.get("close")
    chg = (ltp - prev) if (ltp is not None and prev) else None
    depth = q.get("depth") or {}
    return {
        "available": True,
        "ltp": ltp,
        "open": ohlc.get("open"),
        "high": ohlc.get("high"),
        "low": ohlc.get("low"),
        "prev_close": prev,
        "change": chg,
        "change_pct": (chg / prev * 100.0) if (chg is not None and prev) else None,
        "volume": q.get("volume"),
        "avg_price": q.get("average_price"),
        "oi": q.get("oi"),
        "buy_quantity": q.get("buy_quantity"),
        "sell_quantity": q.get("sell_quantity"),
        "upper_circuit": (q.get("upper_circuit_limit")),
        "lower_circuit": (q.get("lower_circuit_limit")),
        "last_trade_time": q.get("last_trade_time"),
        "timestamp": q.get("timestamp"),
        "depth": {
            "buy": [
                {"price": b.get("price"), "quantity": b.get("quantity"), "orders": b.get("orders")}
                for b in (depth.get("buy") or [])
            ],
            "sell": [
                {"price": s.get("price"), "quantity": s.get("quantity"), "orders": s.get("orders")}
                for s in (depth.get("sell") or [])
            ],
        },
    }


def _resolve(db: Session, exchange: str, symbol: str):
    ex = exchange.strip().upper()
    sym = symbol.strip().upper()
    inst = instrument_service.get(db, ex, sym)
    if inst is None:
        # fall back to the unauthenticated CSV lookup used elsewhere
        try:
            from app.market_data.instruments import resolve_instrument_token

            token, ts = resolve_instrument_token(f"{ex}:{sym}")
            return ex, ts, {"instrument_token": token, "tradingsymbol": ts, "exchange": ex}
        except Exception as exc:  # noqa: BLE001
            raise NotFoundError(f"{ex}:{sym} is not in the instrument master.") from exc
    return ex, inst.tradingsymbol, {
        "instrument_token": inst.instrument_token,
        "tradingsymbol": inst.tradingsymbol,
        "name": inst.name,
        "exchange": inst.exchange,
        "segment": inst.segment,
        "instrument_type": inst.instrument_type,
        "expiry": inst.expiry.isoformat() if inst.expiry else None,
        "strike": float(inst.strike) if inst.strike is not None else None,
        "lot_size": inst.lot_size,
        "tick_size": float(inst.tick_size) if inst.tick_size is not None else None,
        "underlying": inst.underlying,
    }


def quick_look(db: Session, settings: Settings, exchange: str, symbol: str) -> dict[str, Any]:
    ex, ts, meta = _resolve(db, exchange, symbol)
    provider = get_fundamentals_provider(settings)
    profile = provider.get_company_profile(ts)
    metrics = provider.get_key_metrics(ts)
    return {
        "exchange": ex,
        "symbol": ts,
        "instrument": meta,
        "quote": _quote_snapshot(db, settings, ex, ts),
        "fundamentals_provider": provider.name,
        "profile": profile.to_dict(),
        "key_metrics": metrics.to_dict(),
    }


def fundamentals(db: Session, settings: Settings, exchange: str, symbol: str) -> dict[str, Any]:
    ex, ts, _meta = _resolve(db, exchange, symbol)
    p = get_fundamentals_provider(settings)
    return {
        "exchange": ex,
        "symbol": ts,
        "provider": p.name,
        "profile": p.get_company_profile(ts).to_dict(),
        "key_metrics": p.get_key_metrics(ts).to_dict(),
        "income_statement": p.get_financials(ts).to_dict(),
        "quarterly_results": p.get_quarterly_results(ts).to_dict(),
        "balance_sheet": p.get_balance_sheet(ts).to_dict(),
        "cash_flow": p.get_cash_flow(ts).to_dict(),
        "shareholding": p.get_shareholding(ts).to_dict(),
        "corporate_actions": p.get_corporate_actions(ts).to_dict(),
        "news": p.get_news(ts).to_dict(),
    }
