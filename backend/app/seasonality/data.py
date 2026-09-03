"""Load the maximum available clean history per sector index, and audit it.

Each sector uses *all* of its own reliable history (no fixed 10-year cap):
IT / REALTY reach ~2000, HEALTHCARE only ~2005. Small-sample sectors are
kept but flagged, never padded, and a sector only contributes to a month's
statistics for the years it actually has data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.core.logging import get_logger
from app.market_data.cache import get_candles
from app.market_data.instruments import resolve_instrument_token
from app.seasonality import INDEX_TIMELINE, MARKET_INDEX, SECTOR_UNIVERSE, VIX_INDEX
from app.services import broker_service

logger = get_logger(__name__)

_HISTORY_START = datetime(1999, 1, 1)
_MIN_YEARS_KEEP = 3.0


@dataclass
class SectorAudit:
    sector: str
    ok: bool
    status: str                       # PASS | WARN | FAIL
    data_start: str | None
    data_end: str | None
    years_available: float
    trading_days: int
    complete_months: int
    duplicate_dates: int
    invalid_prices: int               # <= 0 or NaN
    non_monotonic_dates: int
    max_gap_days: int
    base_year: int | None
    launch_year: int | None
    pre_launch_years: float
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sector": self.sector, "ok": self.ok, "status": self.status,
            "data_start": self.data_start, "data_end": self.data_end,
            "years_available": round(self.years_available, 1),
            "trading_days": self.trading_days, "complete_months": self.complete_months,
            "duplicate_dates": self.duplicate_dates, "invalid_prices": self.invalid_prices,
            "non_monotonic_dates": self.non_monotonic_dates, "max_gap_days": self.max_gap_days,
            "base_year": self.base_year, "launch_year": self.launch_year,
            "pre_launch_years": round(self.pre_launch_years, 1),
            "issues": self.issues,
        }


def _clean_key(ts: Any) -> datetime:
    s = str(ts)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.fromisoformat(s[:19]).replace(tzinfo=None)


def audit_series(sector: str, bars: list[Any]) -> SectorAudit:
    tl = INDEX_TIMELINE.get(sector)
    base_year, launch_year = (tl if tl else (None, None))
    if not bars:
        return SectorAudit(
            sector=sector, ok=False, status="FAIL", data_start=None, data_end=None,
            years_available=0.0, trading_days=0, complete_months=0, duplicate_dates=0,
            invalid_prices=0, non_monotonic_dates=0, max_gap_days=0,
            base_year=base_year, launch_year=launch_year, pre_launch_years=0.0,
            issues=["no history returned by the data provider"],
        )

    dts = [_clean_key(b.timestamp) for b in bars]
    closes = [float(getattr(b, "close", 0.0) or 0.0) for b in bars]

    dupes = len(dts) - len(set(dts))
    invalid = sum(1 for c in closes if not (c > 0))
    non_mono = sum(1 for i in range(1, len(dts)) if dts[i] <= dts[i - 1])
    gaps = [(dts[i] - dts[i - 1]).days for i in range(1, len(dts))]
    max_gap = max(gaps) if gaps else 0

    start, end = dts[0], dts[-1]
    years = (end - start).days / 365.25
    months = {(d.year, d.month) for d in dts}
    # a month is "complete" only if it is not the final (possibly partial) month
    last_ym = (end.year, end.month)
    complete_months = sum(1 for ym in months if ym != last_ym)

    pre_launch = 0.0
    if launch_year and start.year < launch_year:
        pre_launch = (datetime(launch_year, 1, 1) - start).days / 365.25

    issues: list[str] = []
    if dupes:
        issues.append(f"{dupes} duplicate trading dates")
    if invalid:
        issues.append(f"{invalid} bars with a non-positive close")
    if non_mono:
        issues.append(f"{non_mono} out-of-order dates")
    if max_gap > 12:
        issues.append(f"largest gap between bars is {max_gap} days")
    if pre_launch > 0.5:
        issues.append(
            f"~{pre_launch:.0f}y of the series predates the index's {launch_year} launch "
            f"(back-computed by the provider — treat as research history, not live)"
        )
    if years < _MIN_YEARS_KEEP:
        issues.append(f"only {years:.1f}y of history — below the {_MIN_YEARS_KEEP:.0f}y minimum")

    if years < _MIN_YEARS_KEEP or invalid > 5 or non_mono > 2:
        status = "FAIL"
    elif issues:
        status = "WARN"
    else:
        status = "PASS"

    return SectorAudit(
        sector=sector, ok=status != "FAIL", status=status,
        data_start=start.date().isoformat(), data_end=end.date().isoformat(),
        years_available=years, trading_days=len(dts), complete_months=complete_months,
        duplicate_dates=dupes, invalid_prices=invalid, non_monotonic_dates=non_mono,
        max_gap_days=max_gap, base_year=base_year, launch_year=launch_year,
        pre_launch_years=pre_launch, issues=issues,
    )


def load_history(
    db: Session,
    settings: Settings,
    *,
    sectors: list[str] | None = None,
    include_market: bool = True,
    include_vix: bool = True,
    as_of: datetime | None = None,
) -> tuple[dict[str, list[Any]], dict[str, SectorAudit]]:
    """(-> {index name: [Bar] over max available history}, -> {sector: audit}).

    Sectors that FAIL the audit are dropped from the returned bars but kept
    in the audit map so the report can show *why* they were excluded.
    """
    names = list(sectors or SECTOR_UNIVERSE)
    wanted = list(names)
    if include_market and MARKET_INDEX not in wanted:
        wanted.append(MARKET_INDEX)
    if include_vix and VIX_INDEX not in wanted:
        wanted.append(VIX_INDEX)

    end = as_of or datetime.now()
    client = broker_service.build_authenticated_client(db, settings)

    bars_by: dict[str, list[Any]] = {}
    audits: dict[str, SectorAudit] = {}
    for name in wanted:
        try:
            token, tsym = resolve_instrument_token(name)
        except Exception:  # noqa: BLE001
            audits[name] = audit_series(name, [])
            continue
        try:
            bars = get_candles(client, token, tsym, "day", _HISTORY_START, end)
        except Exception as exc:  # noqa: BLE001
            logger.warning("seasonality_history_failed", index=name, err=str(exc))
            bars = []
        a = audit_series(name, bars)
        audits[name] = a
        if bars and (a.status != "FAIL" or name in (MARKET_INDEX, VIX_INDEX)):
            bars_by[name] = bars
    return bars_by, audits
