"""Live market overview for the Market Scanner.

Pulls real quotes from the connected Zerodha session and derives the things
a trader wants in one glance: index snapshot, market breadth, top gainers /
losers, most-active by value, sector performance and a change heat-map.

If there is no broker session the endpoint returns ``available: False`` with
a reason — it never fabricates prices or serves a stale/mock fallback.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.timeframes import UnknownTimeframeError, kite_interval, resolve
from app.config import Settings
from app.core.exceptions import BrokerNotConnectedError, ValidationError
from app.core.logging import get_logger
from app.market_data.instruments import resolve_instrument_token
from app.market_data.nse_universe import BROAD_INDICES, SECTOR_INDICES, UNIVERSES
from app.models.instrument import Instrument
from app.services import broker_service, instrument_service

logger = get_logger(__name__)

# Sensible lookback per timeframe for a chart (also respects Kite's per-call
# range ceilings for intraday intervals).
_CHART_DEFAULT_DAYS: dict[str, int] = {
    "1m": 5, "3m": 12, "5m": 30, "10m": 45, "15m": 75, "30m": 120, "1h": 200, "1d": 1500,
}
_CHART_MAX_DAYS: dict[str, int] = {
    "1m": 30, "3m": 60, "5m": 90, "10m": 100, "15m": 180, "30m": 365, "1h": 730, "1d": 4000,
}

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


# Tiny hot cache so a 1-2s frontend poll doesn't multiply Kite quote calls
# (the underlying quotes only move once per ~second anyway).
_OVERVIEW_TTL = 1.5
_overview_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def market_overview(db: Session, settings: Settings, *, universe: str = "nifty50") -> dict[str, Any]:
    hit = _overview_cache.get(universe)
    if hit and time.monotonic() - hit[0] < _OVERVIEW_TTL:
        return hit[1]
    out = _market_overview_uncached(db, settings, universe=universe)
    _overview_cache[universe] = (time.monotonic(), out)
    return out


def _market_overview_uncached(
    db: Session, settings: Settings, *, universe: str = "nifty50"
) -> dict[str, Any]:
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


def _epoch(ts: Any) -> int:
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip().replace("Z", "+00:00")
        if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        dt = datetime.fromisoformat(s)
    return int(dt.timestamp())


def _parse_day(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def candles(
    db: Session,
    settings: Settings,
    *,
    symbol: str,
    timeframe: str = "5m",
    days: int | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict[str, Any]:
    """Historical OHLCV for one instrument, shaped for a lightweight-charts
    candlestick + volume series. Real data from the connected Zerodha
    session; ``available: false`` when there is none.

    Pass ``from_date`` / ``to_date`` (ISO) to pin an exact window — e.g. a
    backtest's own date range so the chart lines up with the trades. When
    only ``from_date`` is given the window runs to now; otherwise the
    per-timeframe default lookback ending today is used."""
    try:
        tf = resolve(timeframe)
    except UnknownTimeframeError as exc:
        raise ValidationError(str(exc)) from exc

    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        return {"available": False, "reason": str(exc), "symbol": symbol, "timeframe": tf.token}

    try:
        token, tradingsymbol = resolve_instrument_token(symbol)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError(f"Unknown instrument '{symbol}'.") from exc

    fd, td = _parse_day(from_date), _parse_day(to_date)
    if fd:
        from_dt = fd
        to_dt = td or datetime.now()
        # pad a little so warm-up / edge candles are visible around the window
        from_dt = from_dt - timedelta(days=2)
        to_dt = to_dt + timedelta(days=2)
    else:
        span = days or _CHART_DEFAULT_DAYS.get(tf.token, 60)
        span = min(span, _CHART_MAX_DAYS.get(tf.token, 365))
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=span)
    try:
        rows = client.get_historical_candles(token, kite_interval(tf.token), from_dt, to_dt)
    except Exception as exc:  # noqa: BLE001 - surface Kite's message (e.g. historical add-on)
        return {
            "available": False,
            "reason": f"Historical data unavailable: {exc}",
            "symbol": tradingsymbol,
            "timeframe": tf.token,
        }

    out = [
        {
            "time": _epoch(r[0]),
            "open": r[1],
            "high": r[2],
            "low": r[3],
            "close": r[4],
            "volume": r[5] if len(r) > 5 else 0,
        }
        for r in rows
    ]
    return {
        "available": True,
        "symbol": tradingsymbol,
        "timeframe": tf.token,
        "candles": out,
    }


# --- option chain -----------------------------------------------------

_R = 0.065  # risk-free rate for IV
_INDEX_SPOT = {
    "NIFTY": "NIFTY 50",
    "BANKNIFTY": "NIFTY BANK",
    "FINNIFTY": "NIFTY FIN SERVICE",
    "MIDCPNIFTY": "NIFTY MIDCAP SELECT",
    "NIFTYNXT50": "NIFTY NEXT 50",
}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs(spot: float, strike: float, t: float, vol: float, is_call: bool) -> float:
    if t <= 0 or vol <= 0 or spot <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (_R + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if is_call:
        return spot * _norm_cdf(d1) - strike * math.exp(-_R * t) * _norm_cdf(d2)
    return strike * math.exp(-_R * t) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)


def _implied_vol(price: float, spot: float, strike: float, t: float, is_call: bool) -> float | None:
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    if price <= intrinsic or price <= 0 or t <= 0 or spot <= 0:
        return None
    lo, hi = 0.01, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if _bs(spot, strike, t, mid, is_call) > price:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2 * 100.0, 2)


def option_chain(
    db: Session, settings: Settings, *, underlying: str, expiry: str
) -> dict[str, Any]:
    """Live NSE-style option chain for one underlying + expiry, assembled from
    the instrument master + Zerodha quotes. IV is back-solved from the LTP
    (Kite doesn't publish it)."""
    u = underlying.strip().upper()
    legs = instrument_service.option_strikes(db, u, expiry)
    if not legs:
        return {"available": False, "reason": f"No listed options for {u} @ {expiry}.",
                "underlying": u, "expiry": expiry}

    try:
        client = broker_service.build_authenticated_client(db, settings)
    except BrokerNotConnectedError as exc:
        return {"available": False, "reason": str(exc), "underlying": u, "expiry": expiry}

    spot_sym = f"NSE:{_INDEX_SPOT.get(u, u)}"
    keys = [spot_sym] + [f"NFO:{leg['tradingsymbol']}" for leg in legs]
    quotes = _quote_all(client, keys)

    sq = quotes.get(spot_sym) or {}
    spot = sq.get("last_price")

    try:
        exp_d = datetime.fromisoformat(expiry[:10]).date()
        t_years = max((exp_d - datetime.now().date()).days, 0) / 365.0
    except ValueError:
        t_years = 0.0

    by_strike: dict[float, dict[str, Any]] = {}
    for leg in legs:
        strike = float(leg["strike"] or 0.0)
        q = quotes.get(f"NFO:{leg['tradingsymbol']}") or {}
        ltp = q.get("last_price")
        prev = (q.get("ohlc") or {}).get("close")
        side = "call" if leg["option_type"] == "CE" else "put"
        row = by_strike.setdefault(strike, {"strike": strike, "call": None, "put": None})
        row[side] = {
            "tradingsymbol": leg["tradingsymbol"],
            "instrument_token": leg["instrument_token"],
            "ltp": ltp,
            "change_pct": ((ltp - prev) / prev * 100.0) if (ltp and prev) else None,
            "oi": q.get("oi"),
            "volume": q.get("volume"),
            "iv": _implied_vol(ltp, spot, strike, t_years, side == "call")
            if (ltp and spot) else None,
        }

    rows = [by_strike[k] for k in sorted(by_strike)]
    tot_call_oi = sum((r["call"] or {}).get("oi") or 0 for r in rows)
    tot_put_oi = sum((r["put"] or {}).get("oi") or 0 for r in rows)
    atm = min(rows, key=lambda r: abs(r["strike"] - (spot or 0)))["strike"] if (spot and rows) else None

    # max pain: strike that minimises total writer payout
    max_pain = None
    if rows:
        def _pain(k: float) -> float:
            p = 0.0
            for r in rows:
                c_oi = (r["call"] or {}).get("oi") or 0
                p_oi = (r["put"] or {}).get("oi") or 0
                p += max(0.0, k - r["strike"]) * c_oi + max(0.0, r["strike"] - k) * p_oi
            return p
        max_pain = min((r["strike"] for r in rows), key=_pain)

    return {
        "available": True,
        "underlying": u,
        "expiry": expiry,
        "spot": spot,
        "atm_strike": atm,
        "pcr": round(tot_put_oi / tot_call_oi, 2) if tot_call_oi else None,
        "max_pain": max_pain,
        "total_call_oi": tot_call_oi,
        "total_put_oi": tot_put_oi,
        "rows": rows,
        "as_of": sq.get("timestamp") or datetime.now(UTC).isoformat(),
    }
