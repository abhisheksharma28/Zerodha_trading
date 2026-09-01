"""Session-aware data-quality checks for backtest candles.

The old version compared every consecutive pair of timestamps and flagged
any delta far above the median as a "missing candle". For intraday NSE data
that is nonsense: the jump from 15:25 on Friday to 09:15 on Monday is ~1000x
the 5-minute spacing but is a completely normal session boundary.

This version is **session-aware**:

* candles are grouped by trading date;
* for an intraday timeframe each trading day gets an *expected grid* of
  regular-session slots (09:15 → 15:25 for 5-minute bars);
* gaps are only ever looked for *within a single session* — an overnight,
  weekend or holiday boundary is never a gap;
* holidays need no calendar: a day with zero candles simply isn't a trading
  day;
* a session that is only missing a contiguous tail of slots is flagged as a
  probable short/holiday session, not as missing candles.

Nothing here modifies, fabricates or forward-fills data. Malformed rows,
duplicates and out-of-order timestamps are hard errors; incomplete sessions
and thin history are soft warnings that never, on their own, block a run.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.backtesting.timeframes import UnknownTimeframeError, resolve
from app.strategies.base import Bar

IST = timezone(timedelta(hours=5, minutes=30))

# NSE regular equity session.
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
_SESSION_MINUTES = 375

_MIN_REASONABLE_BARS = 30
_MAX_REPORTED_GAPS = 25
_MAX_REPORTED_SESSIONS = 25
# Below this fraction of a session's expected candles, the day is DATA_INCOMPLETE.
DEFAULT_MIN_SESSION_COMPLETENESS = 0.0  # 0 = report only, never block


def _to_dt(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        dt = ts
    else:
        s = str(ts).strip().replace("Z", "+00:00")
        if len(s) >= 5 and s[-5] in "+-" and s[-3] != ":":
            s = s[:-2] + ":" + s[-2:]
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    return dt.astimezone(IST) if dt.tzinfo else dt.replace(tzinfo=IST)


def _expected_slots(minutes: int) -> list[time]:
    """Regular-session bar-start times for an intraday timeframe.
    5-minute → 09:15, 09:20 … 15:25 (75 slots)."""
    n = _SESSION_MINUTES // minutes
    base = datetime(2000, 1, 1, SESSION_OPEN.hour, SESSION_OPEN.minute)
    return [(base + timedelta(minutes=minutes * i)).time() for i in range(n)]


def _malformed(b: Bar) -> bool:
    o, h, low, c = float(b.open), float(b.high), float(b.low), float(b.close)
    if min(o, h, low, c) <= 0:
        return True
    if h < low or h < o - 1e-9 or h < c - 1e-9 or low > o + 1e-9 or low > c + 1e-9:
        return True
    return (b.volume or 0) < 0


def _check_intraday(symbol: str, bars: list[Bar], minutes: int, min_completeness: float) -> dict[str, Any]:
    slots = _expected_slots(minutes)
    expected_set = set(slots)
    n_expected = len(slots)

    by_day: dict[date, list[datetime]] = {}
    malformed = out_of_order = naive = 0
    prev: datetime | None = None
    first_dt: datetime | None = None
    last_dt: datetime | None = None

    for b in bars:
        if _malformed(b):
            malformed += 1
        d = _to_dt(b.timestamp)
        if d is None:
            continue
        if getattr(b.timestamp, "tzinfo", None) is None and not (
            isinstance(b.timestamp, str) and ("+" in b.timestamp or "Z" in b.timestamp)
        ):
            naive += 1
        if prev is not None and d < prev:
            out_of_order += 1
        prev = d
        first_dt = first_dt or d
        last_dt = d
        by_day.setdefault(d.date(), []).append(d)

    trading_days = sorted(by_day)
    complete_days = 0
    incomplete: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    short_sessions: list[str] = []
    or_missing: list[str] = []
    total_missing = 0
    total_dupes = 0
    per_day_counts: list[int] = []

    for day in trading_days:
        times = sorted(dt.time() for dt in by_day[day])
        uniq = sorted(set(times))
        total_dupes += len(times) - len(uniq)

        present = set(uniq) & expected_set
        missing_slots = [s for s in slots if s not in present]
        per_day_counts.append(len(present))

        if SESSION_OPEN not in present:
            or_missing.append(day.isoformat())

        if not missing_slots:
            complete_days += 1
            continue

        # a contiguous tail of missing slots => probable short / holiday
        # session (or the current day's data still filling in). Recorded
        # separately and NOT treated as missing data or as an incomplete day.
        tail = slots[len(slots) - len(missing_slots):]
        if tail == missing_slots and len(missing_slots) < n_expected:
            short_sessions.append(day.isoformat())
            continue

        total_missing += len(missing_slots)
        # collapse consecutive missing slots into gap runs
        run: list[time] = []
        for s in slots:
            if s in present:
                if run:
                    gaps.append({
                        "date": day.isoformat(),
                        "missing": [t.strftime("%H:%M") for t in run],
                        "minutes": len(run) * minutes,
                    })
                run = []
            else:
                run.append(s)
        if run:
            gaps.append({
                "date": day.isoformat(),
                "missing": [t.strftime("%H:%M") for t in run],
                "minutes": len(run) * minutes,
            })

        completeness = len(present) / n_expected
        incomplete.append({
            "date": day.isoformat(),
            "completeness_pct": round(completeness * 100, 1),
            "present": len(present),
            "expected": n_expected,
            "missing_count": len(missing_slots),
            "opening_range_ok": SESSION_OPEN in present,
            "short_session": day.isoformat() in short_sessions,
        })

    worst = min((s["completeness_pct"] for s in incomplete), default=100.0)
    threshold_failures = [
        s["date"] for s in incomplete
        if not s["short_session"] and s["completeness_pct"] / 100.0 < min_completeness
    ]

    return {
        "symbol": symbol,
        "session_aware": True,
        "bars": len(bars),
        "trading_days": len(trading_days),
        "complete_days": complete_days,
        "incomplete_days": len(incomplete),
        "short_session_days": len(short_sessions),
        "missing_candles": total_missing,
        "duplicate_candles": total_dupes,
        "out_of_order": out_of_order,
        "malformed_rows": malformed,
        "naive_timestamps": naive,
        "short_sessions": short_sessions,
        "opening_range_missing_days": or_missing,
        "first_candle": first_dt.isoformat() if first_dt else None,
        "last_candle": last_dt.isoformat() if last_dt else None,
        "expected_candles_per_day": n_expected,
        "min_candles_in_day": min(per_day_counts, default=0),
        "max_candles_in_day": max(per_day_counts, default=0),
        "avg_candles_per_complete_day": (
            round(sum(per_day_counts) / len(per_day_counts), 1) if per_day_counts else 0.0
        ),
        "worst_completeness_pct": worst,
        "threshold_failure_days": threshold_failures,
        "gaps": gaps[:_MAX_REPORTED_GAPS],
        "gap_count": len(gaps),
        "incomplete_sessions": incomplete[:_MAX_REPORTED_SESSIONS],
        "insufficient_history": len(bars) < _MIN_REASONABLE_BARS,
    }


def _check_daily(symbol: str, bars: list[Bar]) -> dict[str, Any]:
    """EOD series: weekends/holidays are expected, so only genuinely large
    multi-week gaps are worth mentioning."""
    malformed = out_of_order = naive = dupes = 0
    seen: set[str] = set()
    dts: list[datetime] = []
    prev: datetime | None = None
    for b in bars:
        if _malformed(b):
            malformed += 1
        k = str(b.timestamp)
        if k in seen:
            dupes += 1
        seen.add(k)
        d = _to_dt(b.timestamp)
        if d is None:
            continue
        if getattr(b.timestamp, "tzinfo", None) is None and not (
            isinstance(b.timestamp, str) and ("+" in b.timestamp or "Z" in b.timestamp)
        ):
            naive += 1
        if prev is not None and d < prev:
            out_of_order += 1
        prev = d
        dts.append(d)

    big_gaps = 0
    for i in range(1, len(dts)):
        if (dts[i] - dts[i - 1]).days > 10:
            big_gaps += 1

    return {
        "symbol": symbol,
        "session_aware": False,
        "bars": len(bars),
        "trading_days": len(dts),
        "duplicate_candles": dupes,
        "out_of_order": out_of_order,
        "malformed_rows": malformed,
        "naive_timestamps": naive,
        "multi_week_gaps": big_gaps,
        "first_candle": dts[0].isoformat() if dts else None,
        "last_candle": dts[-1].isoformat() if dts else None,
        "insufficient_history": len(bars) < _MIN_REASONABLE_BARS,
    }


def validate_candles(
    candles_by_instrument: dict[str, list[Bar]],
    *,
    timeframe: str = "1d",
    min_session_completeness: float = DEFAULT_MIN_SESSION_COMPLETENESS,
) -> dict[str, Any]:
    """Session-aware for intraday timeframes; loose for daily. Returns
    ``ok`` (hard errors only), ``errors``, ``warnings`` and a rich
    ``per_symbol`` breakdown. ``ok`` is *not* affected by incomplete
    sessions — the strategy, not the validator, decides whether missing
    data matters for a given day."""
    try:
        tf = resolve(timeframe)
        intraday = tf.intraday
        minutes = tf.minutes
    except UnknownTimeframeError:
        intraday, minutes = False, 1440

    per_symbol: list[dict[str, Any]] = []
    for sym, bars in candles_by_instrument.items():
        if not bars:
            per_symbol.append({"symbol": sym, "bars": 0, "session_aware": intraday})
        elif intraday:
            per_symbol.append(_check_intraday(sym, bars, minutes, min_session_completeness))
        else:
            per_symbol.append(_check_daily(sym, bars))

    errors: list[str] = []
    warnings: list[str] = []
    for s in per_symbol:
        sym = s["symbol"]
        if s.get("bars", 0) == 0:
            errors.append(f"{sym}: no candles")
            continue
        if s.get("malformed_rows"):
            errors.append(f"{sym}: {s['malformed_rows']} malformed OHLCV rows")
        if s.get("duplicate_candles"):
            errors.append(f"{sym}: {s['duplicate_candles']} duplicate timestamps")
        if s.get("out_of_order"):
            errors.append(f"{sym}: {s['out_of_order']} out-of-order timestamps")
        if s.get("insufficient_history"):
            warnings.append(f"{sym}: only {s['bars']} bars — thin history for most strategies")
        if s.get("naive_timestamps"):
            warnings.append(f"{sym}: {s['naive_timestamps']} timestamps without a timezone")
        if s.get("incomplete_days"):
            warnings.append(
                f"{sym}: {s['incomplete_days']}/{s['trading_days']} trading days are "
                f"DATA_INCOMPLETE ({s['missing_candles']} intraday candles missing within "
                f"sessions; worst day {s['worst_completeness_pct']}% complete). "
                "Overnight / weekend / holiday boundaries are not counted."
            )
        if s.get("short_sessions"):
            warnings.append(
                f"{sym}: {len(s['short_sessions'])} probable short/holiday sessions "
                "(missing only a contiguous tail of candles) — not treated as missing data."
            )
        if s.get("opening_range_missing_days"):
            n = len(s["opening_range_missing_days"])
            warnings.append(
                f"{sym}: OPENING_RANGE_DATA_MISSING on {n} day(s) "
                f"({', '.join(s['opening_range_missing_days'][:5])}"
                f"{'…' if n > 5 else ''}) — an ORB strategy must skip those days."
            )
        if s.get("threshold_failure_days"):
            warnings.append(
                f"{sym}: {len(s['threshold_failure_days'])} day(s) below the "
                f"{min_session_completeness:.0%} session-completeness threshold."
            )
        if s.get("multi_week_gaps"):
            warnings.append(
                f"{sym}: {s['multi_week_gaps']} gaps longer than 10 calendar days in the "
                "daily series — check for a listing gap or corporate action."
            )

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "session_aware": intraday,
        "timeframe": timeframe,
        "min_session_completeness": min_session_completeness,
        "per_symbol": per_symbol,
    }
