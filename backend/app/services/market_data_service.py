"""Live market overview for the Market Scanner.

Pulls real quotes from the connected Zerodha session and derives the things
a trader wants in one glance: index snapshot, market breadth, top gainers /
losers, most-active by value, sector performance and a change heat-map.

If there is no broker session the endpoint returns ``available: False`` with
a reason — it never fabricates prices or serves a stale/mock fallback.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError
from app.core.logging import get_logger
from app.market_data.nse_universe import BROAD_INDICES, SECTOR_INDICES, UNIVERSES
from app.models.instrument import Instrument
from app.services import broker_service

logger = get_logger(__name__)

_QUOTE_BATCH = 200
_GAP_PCT = 1.0          # |open vs prev close| beyond this = gap up / down
_NEAR_EXTREME_PCT = 0.3  # within this % of the day's high / low


def _pct(ltp: float | None, prev_close: float | None) -> float | None:
    if not ltp or not prev_close:
        return None
    return (ltp - prev_close) / prev_close * 100.0


def _quote_all(client: Any, symbols: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for i in range(0, len(symbols), _QUOTE_BATCH):
        batch = symbols[i : i + _QUOTE_BATCH]
        try:
            out.update(client.get_quote(batch))
        except Exception as exc:  # noqa: BLE001 - one bad batch shouldn't kill the view
            logger.warning("market_quote_batch_failed", size=len(batch), error=str(exc))
    return out


def _known_index_symbols(db: Session) -> set[str]:
    rows = db.execute(
        select(Instrument.tradingsymbol)
        .where(Instrument.exchange == "NSE")
        .where(Instrument.segment.ilike("%INDICES%"))
    ).scalars().all()
    return {r.upper() for r in rows}


def market_overview(db: Session, settings: Settings, *, universe: str = "nifty50") -> dict[str, Any]:
    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        return {"available": False, "reason": str(exc), "universe": universe}

    constituents = UNIVERSES.get(universe) or UNIVERSES["nifty50"]
    name_by_symbol = {sym: name for sym, name, _sector in constituents}

    idx_candidates = [*BROAD_INDICES, *SECTOR_INDICES]
    known_idx = _known_index_symbols(db) if idx_candidates else set()
    idx_wanted = [s for s in idx_candidates if s.upper() in known_idx]

    all_syms = [f"NSE:{s}" for s in idx_wanted] + [f"NSE:{sym}" for sym, _n, _s in constituents]
    quotes = _quote_all(client, all_syms)

    if not quotes:
        return {
            "available": False,
            "reason": "The broker session is connected but returned no quotes. Try again shortly.",
            "universe": universe,
        }

    as_of: str | None = None

    def _row(key: str, sym: str) -> dict[str, Any] | None:
        q = quotes.get(key)
        if not q:
            return None
        nonlocal as_of
        ts = q.get("timestamp") or q.get("last_trade_time")
        if ts and (as_of is None or str(ts) > as_of):
            as_of = str(ts)
        ohlc = q.get("ohlc") or {}
        ltp = q.get("last_price")
        prev = ohlc.get("close")
        return {
            "symbol": sym,
            "ltp": ltp,
            "open": ohlc.get("open"),
            "high": ohlc.get("high"),
            "low": ohlc.get("low"),
            "prev_close": prev,
            "change": (ltp - prev) if (ltp is not None and prev) else None,
            "change_pct": _pct(ltp, prev),
            "volume": q.get("volume"),
        }

    # --- indices --------------------------------------------------------
    indices: list[dict[str, Any]] = []
    for idx_sym in idx_wanted:
        r = _row(f"NSE:{idx_sym}", idx_sym)
        if r is None:
            continue
        r["name"] = idx_sym.title()
        r["group"] = "broad" if idx_sym in BROAD_INDICES else "sector"
        indices.append(r)

    # --- constituents -------------------------------------------------
    stocks: list[dict[str, Any]] = []
    for sym, _name, sector in constituents:
        r = _row(f"NSE:{sym}", sym)
        if r is None or r["change_pct"] is None:
            continue
        r["name"] = name_by_symbol.get(sym, sym)
        r["sector"] = sector
        r["value"] = (r["ltp"] or 0) * (r["volume"] or 0)
        stocks.append(r)

    by_change = sorted(stocks, key=lambda s: s["change_pct"], reverse=True)
    gainers = by_change[:15]
    losers = list(reversed(by_change[-15:]))
    most_active = sorted(stocks, key=lambda s: s["value"], reverse=True)[:15]

    advances = sum(1 for s in stocks if s["change_pct"] > 0)
    declines = sum(1 for s in stocks if s["change_pct"] < 0)
    unchanged = len(stocks) - advances - declines

    # --- sector performance ----------------------------------------
    sec_sum: dict[str, float] = {}
    sec_cnt: dict[str, int] = {}
    sec_adv: dict[str, int] = {}
    sec_dec: dict[str, int] = {}
    for s in stocks:
        name = s["sector"]
        chg = float(s["change_pct"])
        sec_sum[name] = sec_sum.get(name, 0.0) + chg
        sec_cnt[name] = sec_cnt.get(name, 0) + 1
        if chg > 0:
            sec_adv[name] = sec_adv.get(name, 0) + 1
        elif chg < 0:
            sec_dec[name] = sec_dec.get(name, 0) + 1
    sector_rows: list[dict[str, Any]] = [
        {
            "sector": name,
            "count": sec_cnt[name],
            "advances": sec_adv.get(name, 0),
            "declines": sec_dec.get(name, 0),
            "avg_change_pct": round(sec_sum[name] / sec_cnt[name], 2),
        }
        for name in sec_cnt
    ]
    sector_list = sorted(sector_rows, key=lambda d: d["avg_change_pct"], reverse=True)

    # --- intraday signals ----------------------------------------
    def _gap(s: dict[str, Any]) -> float | None:
        return _pct(s["open"], s["prev_close"])

    def _near(s: dict[str, Any], which: str) -> bool:
        ltp, ext = s["ltp"], s.get(which)
        if not ltp or not ext:
            return False
        return abs(ltp - ext) / ext * 100.0 <= _NEAR_EXTREME_PCT

    signals = {
        "gap_up": [s["symbol"] for s in stocks if (_gap(s) or 0) >= _GAP_PCT],
        "gap_down": [s["symbol"] for s in stocks if (_gap(s) or 0) <= -_GAP_PCT],
        "near_day_high": [s["symbol"] for s in stocks if _near(s, "high")],
        "near_day_low": [s["symbol"] for s in stocks if _near(s, "low")],
    }

    trim = ("symbol", "name", "sector", "ltp", "change", "change_pct", "volume", "value")
    return {
        "available": True,
        "as_of": as_of or datetime.now(UTC).isoformat(),
        "universe": universe,
        "constituent_count": len(stocks),
        "indices": indices,
        "breadth": {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "total": len(stocks),
            "ad_ratio": round(advances / declines, 2) if declines else None,
        },
        "gainers": [{k: g[k] for k in trim} for g in gainers],
        "losers": [{k: x[k] for k in trim} for x in losers],
        "most_active": [{k: m[k] for k in trim} for m in most_active],
        "sectors": sector_list,
        "heatmap": [
            {"symbol": s["symbol"], "sector": s["sector"],
             "change_pct": round(s["change_pct"], 2), "value": s["value"]}
            for s in by_change
        ],
        "signals": signals,
    }
