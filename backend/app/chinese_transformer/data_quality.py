"""Data Quality Engine — nothing reaches a feature until it passes here.

Every issue gets a severity. Bad data is never silently filled: an
``ERROR`` or ``CRITICAL`` finding excludes that symbol from model inference
until it is resolved. ``WARNING``/``INFO`` are surfaced but do not block.

The checks operate on a list of OHLCV bars (anything with ``.timestamp``,
``.open``, ``.high``, ``.low``, ``.close``, ``.volume``) for one symbol,
already restricted to the decision window by the caller.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_RANK = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2, Severity.CRITICAL: 3}
_BLOCKING = {Severity.ERROR, Severity.CRITICAL}


@dataclass
class DataQualityIssue:
    symbol: str
    code: str
    severity: Severity
    detail: str
    date_from: str | None = None
    date_to: str | None = None
    missing_pct: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "code": self.code,
            "severity": self.severity.value,
            "detail": self.detail,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "missing_pct": None if self.missing_pct is None else round(self.missing_pct, 2),
            "recommended_action": (
                "Exclude from inference until resolved"
                if self.severity in _BLOCKING
                else "Monitor"
            ),
        }


@dataclass
class DataQualityConfig:
    extreme_return_pct: float = 40.0        # 1-day move beyond this -> ERROR (unadjusted split?)
    warn_return_pct: float = 20.0
    stale_run: int = 5                       # >= N identical consecutive closes -> stale
    max_gap_days: int = 6                    # calendar-day gap between bars (holidays ~ 4-5)
    min_bars: int = 60
    max_missing_pct: float = 5.0
    zero_volume_frac: float = 0.20           # >20% zero-volume bars -> ERROR


@dataclass
class SymbolReport:
    symbol: str
    bars: int
    issues: list[DataQualityIssue] = field(default_factory=list)

    @property
    def worst(self) -> Severity | None:
        return max((i.severity for i in self.issues), key=lambda s: _RANK[s], default=None)

    @property
    def tradeable(self) -> bool:
        return not any(i.severity in _BLOCKING for i in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bars": self.bars,
            "worst_severity": self.worst.value if self.worst else None,
            "tradeable": self.tradeable,
            "issues": [i.as_dict() for i in self.issues],
        }


def _ts_to_date(ts: Any) -> date | None:
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date()
    except ValueError:
        return None


class DataQualityEngine:
    def __init__(self, config: DataQualityConfig | None = None) -> None:
        self.config = config or DataQualityConfig()

    def check_symbol(
        self, symbol: str, bars: list[Any], *, expected_bars: int | None = None
    ) -> SymbolReport:
        cfg = self.config
        rep = SymbolReport(symbol=symbol, bars=len(bars))
        if not bars:
            rep.issues.append(DataQualityIssue(symbol, "no_data", Severity.CRITICAL,
                                               "no bars in window"))
            return rep

        dates = [_ts_to_date(getattr(b, "timestamp", None)) for b in bars]
        d_from = next((d for d in dates if d), None)
        d_to = next((d for d in reversed(dates) if d), None)
        span = (d_from.isoformat() if d_from else None, d_to.isoformat() if d_to else None)

        if len(bars) < cfg.min_bars:
            rep.issues.append(DataQualityIssue(symbol, "insufficient_history", Severity.ERROR,
                                               f"{len(bars)} bars < required {cfg.min_bars}",
                                               *span))
        if expected_bars and expected_bars > 0:
            missing_pct = 100.0 * (1.0 - len(bars) / expected_bars)
            if missing_pct > cfg.max_missing_pct:
                sev = Severity.ERROR if missing_pct > 3 * cfg.max_missing_pct else Severity.WARNING
                rep.issues.append(DataQualityIssue(symbol, "missing_candles", sev,
                                                   f"missing {missing_pct:.1f}% vs expected "
                                                   f"{expected_bars}", *span, missing_pct))

        # duplicate timestamps
        dup = [d.isoformat() for d, c in Counter(d for d in dates if d).items() if c > 1]
        if dup:
            rep.issues.append(DataQualityIssue(symbol, "duplicate_candles", Severity.ERROR,
                                               f"{len(dup)} duplicate timestamp(s): {dup[:3]}",
                                               *span))

        prev_d: date | None = None
        prev_close: float | None = None
        stale = 0
        zero_vol = 0
        bad_ohlc = 0
        extreme: list[str] = []
        big_gap: list[str] = []
        for b, d in zip(bars, dates, strict=False):
            o, h, low, c = (float(getattr(b, k, 0.0) or 0.0) for k in ("open", "high", "low", "close"))
            v = float(getattr(b, "volume", 0.0) or 0.0)
            if min(o, h, low, c) <= 0 or not all(map(math.isfinite, (o, h, low, c))) or h < max(o, c) - 1e-9 or low > min(o, c) + 1e-9 or h < low:
                bad_ohlc += 1
            if v <= 0:
                zero_vol += 1
            if prev_close and prev_close > 0 and c > 0:
                r = (c / prev_close - 1.0) * 100.0
                if abs(r) >= cfg.extreme_return_pct and d:
                    extreme.append(f"{d.isoformat()} {r:+.1f}%")
                if abs(c - prev_close) < 1e-9:
                    stale += 1
                    if stale >= cfg.stale_run and d:
                        rep.issues.append(DataQualityIssue(
                            symbol, "stale_price", Severity.WARNING,
                            f"{stale} identical consecutive closes ending {d.isoformat()}"))
                        stale = 0
                else:
                    stale = 0
            if prev_d and d and (d - prev_d).days > cfg.max_gap_days:
                big_gap.append(f"{prev_d.isoformat()}->{d.isoformat()}")
            prev_d, prev_close = d or prev_d, c or prev_close

        if bad_ohlc:
            rep.issues.append(DataQualityIssue(symbol, "invalid_ohlc", Severity.CRITICAL,
                                               f"{bad_ohlc} bar(s) with non-positive or "
                                               "inconsistent OHLC", *span))
        if zero_vol / len(bars) > cfg.zero_volume_frac:
            rep.issues.append(DataQualityIssue(symbol, "abnormal_volume", Severity.ERROR,
                                               f"{zero_vol}/{len(bars)} zero-volume bars", *span))
        if extreme:
            rep.issues.append(DataQualityIssue(
                symbol, "extreme_return", Severity.ERROR,
                f"{len(extreme)} move(s) >= {cfg.extreme_return_pct}% "
                f"(possible unadjusted corp action): {extreme[:3]}", *span))
        if big_gap:
            rep.issues.append(DataQualityIssue(symbol, "timestamp_gap", Severity.WARNING,
                                               f"{len(big_gap)} gap(s) > {cfg.max_gap_days}d: "
                                               f"{big_gap[:3]}", *span))
        return rep

    def report(
        self, bars_by_symbol: dict[str, list[Any]], *, expected_bars: int | None = None
    ) -> DataQualityReport:
        rows = [
            self.check_symbol(sym, bars, expected_bars=expected_bars)
            for sym, bars in sorted(bars_by_symbol.items())
        ]
        return DataQualityReport(rows)


@dataclass
class DataQualityReport:
    symbols: list[SymbolReport]

    def tradeable_symbols(self) -> list[str]:
        return [r.symbol for r in self.symbols if r.tradeable]

    def excluded(self) -> dict[str, str]:
        return {
            r.symbol: "; ".join(i.code for i in r.issues if i.severity in _BLOCKING)
            for r in self.symbols
            if not r.tradeable
        }

    def as_dict(self) -> dict[str, Any]:
        counts = Counter(
            i.severity.value for r in self.symbols for i in r.issues
        )
        return {
            "symbol_count": len(self.symbols),
            "tradeable_count": len(self.tradeable_symbols()),
            "excluded": self.excluded(),
            "issue_counts": dict(counts),
            "symbols": [r.as_dict() for r in self.symbols],
        }
