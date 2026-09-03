"""Build a normalised ``ChainSnapshot`` from whatever source has the data.

* ``from_live_payload`` — the dict returned by
  ``market_data_service.option_chain`` (live Kite chain). It has per-strike
  CE/PE ``oi / volume / ltp / iv`` but no change-in-OI, so ΔOI is filled by
  diffing against the previous stored snapshot (``prev_rows``).
* ``from_bhavcopy_rows`` — NSE F&O bhavcopy rows (EOD), which *do* carry
  ``chg_in_oi``; used by the backtest loader in a later phase.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.adaptive_options.types import ChainRow, ChainSnapshot


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _iv_fraction(v: Any) -> float | None:
    """The live chain reports IV as a percentage (e.g. 13.42). Bhavcopy has
    no IV. Normalise to a fraction; treat 0 / negative as missing."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return f / 100.0 if f > 3.0 else f     # >3 must be a percent


def from_live_payload(
    payload: dict[str, Any],
    *,
    dte: float,
    prev_rows: dict[float, dict[str, float]] | None = None,
) -> ChainSnapshot:
    if not payload.get("available"):
        raise ValueError(payload.get("reason") or "option chain unavailable")

    prev = prev_rows or {}
    rows: list[ChainRow] = []
    for r in payload.get("rows", []):
        strike = _f(r.get("strike"))
        call = r.get("call") or {}
        put = r.get("put") or {}
        c_oi, p_oi = _f(call.get("oi")), _f(put.get("oi"))
        pr = prev.get(strike, {})
        rows.append(ChainRow(
            strike=strike,
            call_oi=c_oi, put_oi=p_oi,
            call_chg_oi=c_oi - _f(pr.get("call_oi")) if pr else 0.0,
            put_chg_oi=p_oi - _f(pr.get("put_oi")) if pr else 0.0,
            call_volume=_f(call.get("volume")), put_volume=_f(put.get("volume")),
            call_ltp=call.get("ltp"), put_ltp=put.get("ltp"),
            call_iv=_iv_fraction(call.get("iv")), put_iv=_iv_fraction(put.get("iv")),
        ))
    rows.sort(key=lambda x: x.strike)

    as_of_raw = payload.get("as_of")
    try:
        as_of = datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00")) if as_of_raw \
            else datetime.now()
    except ValueError:
        as_of = datetime.now()

    return ChainSnapshot(
        underlying=str(payload.get("underlying") or "").upper(),
        expiry=str(payload.get("expiry") or ""),
        spot=_f(payload.get("spot")),
        as_of=as_of,
        dte=float(dte),
        rows=rows,
    )


def from_bhavcopy_rows(
    underlying: str, expiry: str, spot: float, as_of: datetime, dte: float,
    rows: list[dict[str, Any]],
) -> ChainSnapshot:
    """``rows``: one dict per contract with keys ``strike``, ``option_type``
    ('CE'|'PE'), ``oi``, ``chg_in_oi``, ``volume``, ``close``."""
    by_strike: dict[float, dict[str, Any]] = {}
    for r in rows:
        k = _f(r.get("strike"))
        slot = by_strike.setdefault(k, {})
        side = "call" if str(r.get("option_type")).upper() == "CE" else "put"
        slot[f"{side}_oi"] = _f(r.get("oi"))
        slot[f"{side}_chg_oi"] = _f(r.get("chg_in_oi"))
        slot[f"{side}_volume"] = _f(r.get("volume"))
        slot[f"{side}_ltp"] = r.get("close")
    out = [
        ChainRow(
            strike=k,
            call_oi=v.get("call_oi", 0.0), put_oi=v.get("put_oi", 0.0),
            call_chg_oi=v.get("call_chg_oi", 0.0), put_chg_oi=v.get("put_chg_oi", 0.0),
            call_volume=v.get("call_volume", 0.0), put_volume=v.get("put_volume", 0.0),
            call_ltp=v.get("call_ltp"), put_ltp=v.get("put_ltp"),
            call_iv=None, put_iv=None,
        )
        for k, v in sorted(by_strike.items())
    ]
    return ChainSnapshot(underlying.upper(), expiry, spot, as_of, float(dte), out)
