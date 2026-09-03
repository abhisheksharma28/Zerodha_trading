"""Bring-your-own historical options data for the adaptive backtest.

Point ``ADAPTIVE_OPTIONS_HISTORY_DIR`` (default ``data/options_history``) at
a folder holding option-chain history you downloaded from Kaggle, a GitHub
dump, or exported yourself. Two layouts are auto-detected:

  1. per-day files      <DIR>/<UNDERLYING>/<YYYY-MM-DD>.csv
  2. one file per name   <DIR>/<UNDERLYING>.csv   (or .parquet) with a date
                         column — indexed by date on first use

Column names are matched loosely against the headers Kaggle NSE-options and
common GitHub dumps use (strike / expiry / type / oi / chg_oi / volume /
ltp|close / iv? / underlying?). Intraday files are collapsed to the last
snapshot of each day (the adaptive engine decides once per day).

``data_source="local"`` in the backtest routes here; missing data for a
date falls through to the synthetic chain, same as bhavcopy.
"""

from __future__ import annotations

import contextlib
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

_DIR = Path(os.getenv("ADAPTIVE_OPTIONS_HISTORY_DIR",
                      str(Path(__file__).resolve().parent.parent.parent / "data" / "options_history")))

_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "trade_date", "timestamp", "datetime", "time", "tradedate", "as_of"),
    "strike": ("strike", "strike_price", "strikeprice", "strike_pr", "strk", "strkpric"),
    "opt_type": ("option_type", "opt_type", "option_typ", "optiontype", "type", "right",
                 "instrument_type", "ce_pe", "cp", "call_put", "optntp"),
    "expiry": ("expiry", "expiry_date", "expirydate", "expiry_dt", "xprydt", "exp"),
    "oi": ("oi", "open_interest", "openinterest", "open_int", "opnintrst"),
    "chg_oi": ("chg_oi", "change_in_oi", "changeinopeninterest", "chg_in_oi", "oi_change",
               "chnginopnintrst", "changeinoi"),
    "volume": ("volume", "vol", "totaltradedvolume", "traded_volume", "contracts", "qty",
               "ttltradgvol"),
    "ltp": ("ltp", "last_price", "lastprice", "close", "close_price", "settle", "settle_pr",
            "price", "clspric", "sttlmpric"),
    "iv": ("iv", "implied_volatility", "impliedvolatility", "iv_close"),
    "underlying": ("underlying", "underlying_value", "underlyingvalue", "spot", "spot_price",
                   "undrlygpric", "underlying_price"),
}


def _norm(s: str) -> str:
    return "".join(ch for ch in s.strip().lower() if ch.isalnum() or ch == "_")


def _colmap(cols: list[str]) -> dict[str, str]:
    norm = {_norm(c): c for c in cols}
    out: dict[str, str] = {}
    for canon, aliases in _ALIASES.items():
        for a in aliases:
            if a in norm:
                out[canon] = norm[a]
                break
    return out


def _to_ce_pe(v: Any) -> str | None:
    s = str(v).strip().upper()
    if s in ("CE", "C", "CALL"):
        return "CE"
    if s in ("PE", "P", "PUT"):
        return "PE"
    return None


def _to_date(v: Any) -> date | None:
    try:
        return pd.to_datetime(v).date()
    except (ValueError, TypeError):
        return None


@lru_cache(maxsize=8)
def _load(underlying: str) -> pd.DataFrame | None:
    u = underlying.strip().upper()
    frames: list[pd.DataFrame] = []

    per_day_dir = _DIR / u
    if per_day_dir.is_dir():
        for f in sorted(per_day_dir.glob("*.csv")):
            try:
                df = pd.read_csv(f)
            except Exception:  # noqa: BLE001
                continue
            df["__date"] = _to_date(f.stem) or pd.NaT
            frames.append(df)

    for ext, reader in ((".csv", pd.read_csv), (".parquet", pd.read_parquet)):
        fp = _DIR / f"{u}{ext}"
        if fp.exists():
            with contextlib.suppress(Exception):
                frames.append(reader(fp))

    if not frames:
        return None
    raw = pd.concat(frames, ignore_index=True)
    cm = _colmap(list(raw.columns))
    if not {"strike", "opt_type", "expiry", "oi"} <= set(cm):
        return None

    out = pd.DataFrame({
        "strike": pd.to_numeric(raw[cm["strike"]], errors="coerce"),
        "opt_type": raw[cm["opt_type"]].map(_to_ce_pe),
        "expiry": raw[cm["expiry"]].map(_to_date),
        "oi": pd.to_numeric(raw[cm["oi"]], errors="coerce").fillna(0.0),
        "chg_oi": pd.to_numeric(raw[cm["chg_oi"]], errors="coerce").fillna(0.0)
        if "chg_oi" in cm else 0.0,
        "volume": pd.to_numeric(raw[cm["volume"]], errors="coerce").fillna(0.0)
        if "volume" in cm else 0.0,
        "ltp": pd.to_numeric(raw[cm["ltp"]], errors="coerce") if "ltp" in cm else pd.NA,
        "iv": pd.to_numeric(raw[cm["iv"]], errors="coerce") if "iv" in cm else pd.NA,
        "underlying": pd.to_numeric(raw[cm["underlying"]], errors="coerce")
        if "underlying" in cm else pd.NA,
    })
    if "date" in cm:
        out["date"] = raw[cm["date"]].map(_to_date)
    elif "__date" in raw.columns:
        out["date"] = raw["__date"].map(_to_date)
    else:
        return None
    out = out.dropna(subset=["strike", "opt_type", "expiry", "date"])
    return out if not out.empty else None


def has_data(underlying: str) -> bool:
    return _load(underlying) is not None


def dates_available(underlying: str) -> list[date]:
    df = _load(underlying)
    return sorted(df["date"].dropna().unique().tolist()) if df is not None else []


def expiries_on(underlying: str, d: date) -> list[date]:
    df = _load(underlying)
    if df is None:
        return []
    sub = df[df["date"] == d]
    return sorted({e for e in sub["expiry"].tolist() if isinstance(e, date)})


def underlying_close_on(underlying: str, d: date) -> float | None:
    df = _load(underlying)
    if df is None:
        return None
    sub = df[df["date"] == d]
    vals = sub["underlying"].dropna()
    return float(vals.iloc[-1]) if len(vals) else None


def chain_rows(underlying: str, d: date, expiry: date) -> list[dict[str, Any]] | None:
    """Rows for one (date, expiry), collapsed to the last snapshot of the
    day. Same shape as ``bhavcopy.chain_rows``. ``None`` if unavailable."""
    df = _load(underlying)
    if df is None:
        return None
    sub = df[(df["date"] == d) & (df["expiry"] == expiry)]
    if sub.empty:
        return None
    # keep the last row per (strike, opt_type) — handles intraday files
    sub = sub.drop_duplicates(subset=["strike", "opt_type"], keep="last")
    rows: list[dict[str, Any]] = []
    for _, r in sub.iterrows():
        rows.append({
            "strike": float(r["strike"]),
            "option_type": str(r["opt_type"]),
            "oi": float(r["oi"] or 0.0),
            "chg_in_oi": float(r["chg_oi"] or 0.0),
            "volume": float(r["volume"] or 0.0),
            "close": float(r["ltp"]) if pd.notna(r["ltp"]) else 0.0,
        })
    return rows or None


def source_info() -> dict[str, Any]:
    out: dict[str, Any] = {"dir": str(_DIR), "exists": _DIR.exists(), "underlyings": {}}
    if _DIR.exists():
        for u in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
            ds = dates_available(u)
            if ds:
                out["underlyings"][u] = {"days": len(ds), "from": ds[0].isoformat(),
                                         "to": ds[-1].isoformat()}
    return out
