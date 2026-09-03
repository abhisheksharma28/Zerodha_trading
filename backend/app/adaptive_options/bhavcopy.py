"""Phase 14 — NSE F&O bhavcopy (UDiFF) loader for the adaptive backtest.

The UDiFF "Common Bhavcopy Final" is a free daily EOD file with per-contract
open interest, change in OI, volume and settlement price going back years —
enough for a *daily-decision* adaptive options backtest.

    https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip

NSE archive downloads are frequently rate-limited or blocked for non-browser
clients, so every function here fails soft: on any error it returns
``None`` / an empty result and the backtest falls back to the synthetic
chain (clearly flagged). Downloaded files are cached under ``data/bhavcopy``.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import httpx

_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "bhavcopy"
# UDiFF "Common Bhavcopy Final" — the current format, reliable from ~2024-01.
_URL_UDIFF = ("https://nsearchives.nseindia.com/content/fo/"
              "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip")
# Legacy F&O bhavcopy — the only free option-OI history before 2024-01
# (~2019 onward). Different column names; no underlying price column.
_URL_LEGACY = ("https://nsearchives.nseindia.com/content/historical/DERIVATIVES/"
               "{yyyy}/{mon}/fo{dd}{mon}{yyyy}bhav.csv.zip")
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_INDEX_OPT_TYPES = {"IDO", "OPTIDX"}       # UDiFF FinInstrmTp / legacy INSTRUMENT
_STOCK_OPT_TYPES = {"STO", "OPTSTK"}


def _cache_path(d: date) -> Path:
    return _DIR / f"fo_{d.isoformat()}.csv"


def _fetch_zip_csv(url: str, timeout: float) -> str | None:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": _UA, "Accept": "*/*"}) as c:
            r = c.get(url)
            if r.status_code != 200 or not r.content:
                return None
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                name = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
                if not name:
                    return None
                return z.read(name).decode("utf-8", "replace")
    except (httpx.HTTPError, zipfile.BadZipFile, OSError, ValueError):
        return None


def download(d: date, *, timeout: float = 20.0) -> str | None:
    """CSV text for one trading day, cached. Tries the UDiFF format first,
    then the legacy F&O bhavcopy. ``None`` on any failure (weekend / holiday
    / blocked / not archived)."""
    cp = _cache_path(d)
    if cp.exists():
        return cp.read_text()
    if d.weekday() >= 5:
        return None
    _DIR.mkdir(parents=True, exist_ok=True)

    text = _fetch_zip_csv(_URL_UDIFF.format(ymd=d.strftime("%Y%m%d")), timeout)
    if text is None:
        mon = d.strftime("%b").upper()
        text = _fetch_zip_csv(
            _URL_LEGACY.format(yyyy=d.year, mon=mon, dd=d.strftime("%d")), timeout)
    if text is None:
        return None
    cp.write_text(text)
    return text


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# column aliases: canonical name -> (UDiFF, legacy) header
_COLS = {
    "symbol": ("TckrSymb", "SYMBOL"),
    "instr": ("FinInstrmTp", "INSTRUMENT"),
    "opt_type": ("OptnTp", "OPTION_TYP"),
    "expiry": ("XpryDt", "EXPIRY_DT"),
    "strike": ("StrkPric", "STRIKE_PR"),
    "oi": ("OpnIntrst", "OPEN_INT"),
    "chg_oi": ("ChngInOpnIntrst", "CHG_IN_OI"),
    "volume": ("TtlTradgVol", "CONTRACTS"),
    "close": ("ClsPric", "CLOSE"),
    "settle": ("SttlmPric", "SETTLE_PR"),
    "underlying_px": ("UndrlygPric", "UndrlygPric"),
}


def _pick(r: dict[str, Any], key: str) -> Any:
    a, b = _COLS[key]
    return r.get(a) if r.get(a) not in (None, "") else r.get(b)


def _parse_expiry(v: Any) -> date | None:
    s = str(v or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d%b%Y"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(s[:11], fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _rows(text: str):
    for row in csv.DictReader(io.StringIO(text)):
        yield {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}


def chain_rows(
    text: str, underlying: str, expiry: date, *, index_option: bool = True
) -> list[dict[str, Any]]:
    """Parse rows for one underlying + expiry (either bhavcopy format) into
    the shape ``chain_view.from_bhavcopy_rows`` expects."""
    want_types = _INDEX_OPT_TYPES if index_option else _STOCK_OPT_TYPES
    u = underlying.strip().upper()
    out: list[dict[str, Any]] = []
    for r in _rows(text):
        if str(_pick(r, "symbol")).upper() != u:
            continue
        if str(_pick(r, "instr")) not in want_types:
            continue
        ot = str(_pick(r, "opt_type")).upper()
        if ot not in ("CE", "PE"):
            continue
        if _parse_expiry(_pick(r, "expiry")) != expiry:
            continue
        out.append({
            "strike": _f(_pick(r, "strike")),
            "option_type": ot,
            "oi": _f(_pick(r, "oi")),
            "chg_in_oi": _f(_pick(r, "chg_oi")),
            "volume": _f(_pick(r, "volume")),
            "close": _f(_pick(r, "close") or _pick(r, "settle")),
        })
    return out


def underlying_close(text: str, underlying: str) -> float | None:
    """Underlying price on the option rows if the file carries it (UDiFF
    only). Legacy bhavcopy has no such column — the caller supplies spot."""
    u = underlying.strip().upper()
    for r in _rows(text):
        if str(_pick(r, "symbol")).upper() == u and str(_pick(r, "opt_type")).upper() in ("CE", "PE"):
            p = _f(_pick(r, "underlying_px"))
            if p > 0:
                return p
    return None


def expiries_in(text: str, underlying: str, *, index_option: bool = True) -> list[date]:
    want = _INDEX_OPT_TYPES if index_option else _STOCK_OPT_TYPES
    u = underlying.strip().upper()
    seen: set[date] = set()
    for r in _rows(text):
        if str(_pick(r, "symbol")).upper() == u and str(_pick(r, "instr")) in want \
                and str(_pick(r, "opt_type")).upper() in ("CE", "PE"):
            e = _parse_expiry(_pick(r, "expiry"))
            if e:
                seen.add(e)
    return sorted(seen)
