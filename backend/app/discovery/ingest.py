"""Persist an ingested multi-asset price dataset into the discovery store.

Provider-agnostic: the caller (a one-off script pulling Twelve Data via
the MCP, or the Kite candle store for Indian ETFs) hands over
``{symbol: [(date, close), ...]}`` and this module upserts the instrument
metadata + bars, assigns a data-quality tier and score, and records an
ingest run for reproducibility.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.discovery import universe as U
from app.models.discovery import (
    DiscoveryBar,
    DiscoveryFxRate,
    DiscoveryIngestRun,
    DiscoveryInstrument,
)

logger = get_logger(__name__)

Series = dict[str, list[tuple[date, float]]]


def _tier(years: float) -> str:
    if years >= 10.0:
        return "A"
    if years >= 7.0:
        return "B"
    if years >= 3.0:
        return "C"
    return "D"


def _quality_score(pts: list[tuple[date, float]], interval: str) -> float:
    """0-100: completeness (few missing periods), sane values, recency."""
    if len(pts) < 6:
        return 0.0
    pts = sorted(pts)
    span_days = (pts[-1][0] - pts[0][0]).days or 1
    step = 30.5 if interval == "1month" else 7.0 if interval == "1week" else 1.4
    expected = span_days / step
    completeness = min(1.0, len(pts) / expected) if expected > 0 else 0.0

    # no non-positive prices, no >60% single-period jumps (split/data glitch)
    bad = 0
    for i in range(1, len(pts)):
        p0, p1 = pts[i - 1][1], pts[i][1]
        if p1 <= 0 or p0 <= 0 or abs(p1 / p0 - 1.0) > 0.60:
            bad += 1
    clean = max(0.0, 1.0 - bad / max(1, len(pts) - 1))

    stale_days = (date.today() - pts[-1][0]).days
    recency = 1.0 if stale_days <= 45 else 0.7 if stale_days <= 120 else 0.4

    return round(100.0 * (0.55 * completeness + 0.30 * clean + 0.15 * recency), 2)


def _upsert_instrument(
    db: Session, u: U.UnivInstrument, interval: str
) -> DiscoveryInstrument:
    inst = db.execute(
        select(DiscoveryInstrument).where(DiscoveryInstrument.symbol == u.symbol)
    ).scalar_one_or_none()
    if inst is None:
        inst = DiscoveryInstrument(symbol=u.symbol)
        db.add(inst)
    inst.name = u.name
    inst.asset_class = u.asset_class
    inst.sub_class = u.sub_class
    inst.region = u.region
    inst.currency = u.currency
    inst.provider = u.provider
    inst.provider_symbol = u.provider_symbol
    inst.expense_ratio = u.expense_ratio
    inst.inception_date = date(u.inception_year, 1, 1) if u.inception_year else None
    inst.bar_interval = interval
    inst.active = True
    db.flush()
    return inst


def _write_bars(db: Session, inst: DiscoveryInstrument, pts: list[tuple[date, float]]) -> int:
    db.execute(delete(DiscoveryBar).where(DiscoveryBar.instrument_id == inst.id))
    rows = [
        {"instrument_id": inst.id, "d": d, "close": float(c)}
        for d, c in sorted(pts)
        if c and c > 0
    ]
    if rows:
        db.bulk_insert_mappings(DiscoveryBar, rows)
    return len(rows)


def _finalise_meta(inst: DiscoveryInstrument, pts: list[tuple[date, float]]) -> None:
    clean = sorted((d, c) for d, c in pts if c and c > 0)
    if not clean:
        inst.n_points = 0
        inst.tier = "D"
        inst.quality_score = 0.0
        return
    inst.data_start = clean[0][0]
    inst.data_end = clean[-1][0]
    inst.n_points = len(clean)
    years = (clean[-1][0] - clean[0][0]).days / 365.25
    inst.tier = _tier(years)
    inst.quality_score = _quality_score(clean, inst.bar_interval)


def _write_fx(db: Session, pair: str, pts: list[tuple[date, float]]) -> int:
    db.execute(delete(DiscoveryFxRate).where(DiscoveryFxRate.pair == pair))
    rows = [
        {"pair": pair, "d": d, "rate": float(r)}
        for d, r in sorted(pts)
        if r and r > 0
    ]
    if rows:
        db.bulk_insert_mappings(DiscoveryFxRate, rows)
    return len(rows)


def ingest_prices(
    db: Session,
    *,
    series: Series,
    fx: Series | None = None,
    source: str = "twelvedata",
    bar_interval: str = "1month",
    note: str | None = None,
) -> dict[str, Any]:
    run = DiscoveryIngestRun(
        started_at=datetime.now(UTC), source=source, bar_interval=bar_interval
    )
    db.add(run)
    db.flush()

    n_inst = 0
    n_bars = 0
    per: list[dict[str, Any]] = []
    for u in U.all_instruments():
        pts = series.get(u.symbol)
        if not pts:
            continue
        inst = _upsert_instrument(db, u, bar_interval)
        wrote = _write_bars(db, inst, pts)
        _finalise_meta(inst, pts)
        n_inst += 1
        n_bars += wrote
        per.append({"symbol": u.symbol, "bars": wrote, "tier": inst.tier,
                    "quality": float(inst.quality_score or 0.0)})

    n_fx = 0
    for pair, pts in (fx or {}).items():
        n_fx += _write_fx(db, pair, pts)

    run.finished_at = datetime.now(UTC)
    run.n_instruments = n_inst
    run.n_bars = n_bars + n_fx
    run.note = note
    db.commit()

    logger.info("discovery_ingest", instruments=n_inst, bars=n_bars, fx_rows=n_fx, source=source)
    return {
        "run_id": str(run.id),
        "instruments": n_inst,
        "bars": n_bars,
        "fx_rows": n_fx,
        "per_instrument": per,
    }


# --- Twelve Data CSV helper + seed-file loader ------------------------

def parse_twelvedata_csv(text: str) -> list[tuple[date, float]]:
    """Twelve Data returns ``datetime;open;high;low;close;volume`` rows,
    newest first. Keep (date, close)."""
    out: list[tuple[date, float]] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line or line.lower().startswith("datetime"):
            continue
        parts = line.split(";")
        if len(parts) < 5:
            continue
        try:
            d = date.fromisoformat(parts[0][:10])
            c = float(parts[4])
        except ValueError:
            continue
        out.append((d, c))
    return out


_SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "discovery_seed"


def load_seed_dir(seed_dir: Path) -> tuple[Series, Series]:
    """Read ``<SYMBOL>.csv`` (raw Twelve Data output) from a directory.
    Files named like an FX pair (``USD-INR.csv``) go into the FX map."""
    series: Series = {}
    fx: Series = {}
    for f in sorted(seed_dir.glob("*.csv")):
        name = f.stem.upper()
        pts = parse_twelvedata_csv(f.read_text())
        if not pts:
            continue
        if "-" in name and len(name) <= 8:  # "USD-INR" -> "USD/INR"
            fx[name.replace("-", "/")] = pts
        else:
            series[name] = pts
    return series, fx


def fetch_via_twelvedata(*, interval: str = "1month", start: str = "2004-01-01") -> tuple[Series, Series]:
    """Pull every universe instrument + FX pair from the Twelve Data REST
    API. Needs TWELVEDATA_API_KEY. One bad symbol is logged and skipped so
    a single delisting doesn't abort the whole run."""
    import httpx

    from app.discovery.providers import twelvedata_series

    series: Series = {}
    fx: Series = {}
    with httpx.Client(timeout=30.0) as client:
        for u in U.all_instruments():
            try:
                series[u.symbol] = twelvedata_series(
                    u.provider_symbol, interval=interval, start=start, client=client
                )
            except Exception as exc:  # noqa: BLE001 - one symbol must not stop the batch
                logger.warning("discovery_fetch_failed", symbol=u.symbol, err=str(exc))
        for pair in U.FX_PAIRS:
            try:
                fx[pair] = twelvedata_series(pair, interval=interval, start=start, client=client)
            except Exception as exc:  # noqa: BLE001
                logger.warning("discovery_fetch_failed", symbol=pair, err=str(exc))
    return series, fx


if __name__ == "__main__":
    import json
    import sys

    from app.db.session import SessionLocal

    _mode = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if _mode == "fetch":
        _series, _fx = fetch_via_twelvedata()
        _note = "twelvedata REST fetch"
    else:
        _series, _fx = load_seed_dir(_SEED_DIR)
        _note = f"seed dir ({_SEED_DIR.name})"

    _db = SessionLocal()
    try:
        result = ingest_prices(
            _db, series=_series, fx=_fx, bar_interval="1month",
            source="twelvedata", note=_note,
        )
    finally:
        _db.close()
    print(json.dumps(result, indent=1))
