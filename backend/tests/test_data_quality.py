"""Session-aware data-quality validation for NSE intraday candles.

The regression that matters: an overnight / weekend / holiday boundary must
NEVER be reported as a missing candle.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from app.backtesting.data_quality import validate_candles
from app.strategies.base import Bar

IST = "+05:30"


def _bar(sym: str, dt: datetime, px: float = 100.0) -> Bar:
    return Bar(
        timestamp=dt.strftime("%Y-%m-%dT%H:%M:00") + IST,
        open=px, high=px + 0.5, low=px - 0.5, close=px, volume=1000, instrument=sym,
    )


def _session(sym: str, day: date, *, slots: int = 75, drop: set[str] | None = None,
             stop_after: str | None = None) -> list[Bar]:
    """One NSE 5-minute session: 09:15 .. 15:25 (75 bars)."""
    drop = drop or set()
    out: list[Bar] = []
    start = datetime(day.year, day.month, day.day, 9, 15)
    for i in range(slots):
        t = start + timedelta(minutes=5 * i)
        hhmm = t.strftime("%H:%M")
        if hhmm in drop:
            continue
        if stop_after and hhmm > stop_after:
            break
        out.append(_bar(sym, t))
    return out


def _weekdays(n: int, start=date(2025, 1, 6)) -> list[date]:  # 2025-01-06 is a Monday
    out, k = [], 0
    while len(out) < n:
        d = start + timedelta(days=k)
        if d.weekday() < 5:
            out.append(d)
        k += 1
    return out


def test_overnight_and_weekend_boundaries_are_not_missing_candles():
    days = _weekdays(5)  # Mon-Fri
    bars = [b for d in days for b in _session("INFY", d)]
    dq = validate_candles({"INFY": bars}, timeframe="5m")

    s = dq["per_symbol"][0]
    assert dq["ok"] is True
    assert s["session_aware"] is True
    assert s["trading_days"] == 5
    assert s["complete_days"] == 5
    assert s["incomplete_days"] == 0
    assert s["missing_candles"] == 0
    assert s["gap_count"] == 0
    assert s["opening_range_missing_days"] == []
    # crucially: no warning about missing candles / large gaps
    assert not any("missing" in w.lower() or "gap" in w.lower() for w in dq["warnings"])


def test_genuine_intraday_hole_is_reported_precisely():
    days = _weekdays(3)
    bars: list[Bar] = []
    for i, d in enumerate(days):
        drop = {"10:35", "10:40", "10:45"} if i == 1 else set()
        bars += _session("INFY", d, drop=drop)
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    s = dq["per_symbol"][0]

    assert dq["ok"] is True  # a warning, never a hard block
    assert s["missing_candles"] == 3
    assert s["incomplete_days"] == 1
    assert s["gaps"] == [
        {"date": days[1].isoformat(), "missing": ["10:35", "10:40", "10:45"], "minutes": 15}
    ]
    sess = next(x for x in s["incomplete_sessions"] if x["date"] == days[1].isoformat())
    assert sess["missing_count"] == 3 and sess["opening_range_ok"] is True


def test_missing_opening_range_candle_flagged():
    days = _weekdays(2)
    bars = _session("INFY", days[0]) + _session("INFY", days[1], drop={"09:15"})
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    s = dq["per_symbol"][0]
    assert s["opening_range_missing_days"] == [days[1].isoformat()]
    assert any("OPENING_RANGE_DATA_MISSING" in w for w in dq["warnings"])
    assert dq["ok"] is True


def test_short_session_not_counted_as_missing():
    days = _weekdays(2)
    bars = _session("INFY", days[0]) + _session("INFY", days[1], stop_after="13:00")
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    s = dq["per_symbol"][0]
    assert s["short_sessions"] == [days[1].isoformat()]
    assert s["missing_candles"] == 0
    assert s["gap_count"] == 0


def test_holiday_weekday_with_no_candles_is_not_a_missing_day():
    # skip Wednesday entirely (a "holiday")
    mon, tue, _wed, thu = _weekdays(4)
    bars = [b for d in (mon, tue, thu) for b in _session("INFY", d)]
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    s = dq["per_symbol"][0]
    assert s["trading_days"] == 3
    assert s["complete_days"] == 3 and s["missing_candles"] == 0


def test_duplicate_and_malformed_are_hard_errors():
    d = _weekdays(1)[0]
    bars = _session("INFY", d)
    bars.append(bars[10])  # duplicate timestamp
    bad = _bar("INFY", datetime(d.year, d.month, d.day, 11, 0))
    bad.high, bad.low = 90.0, 110.0  # high < low
    bars.append(bad)
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    assert dq["ok"] is False
    assert any("duplicate" in e for e in dq["errors"])
    assert any("malformed" in e for e in dq["errors"])


def test_completeness_summary_fields():
    days = _weekdays(4)
    bars: list[Bar] = []
    for i, d in enumerate(days):
        bars += _session("INFY", d, drop={"12:00"} if i == 2 else set())
    dq = validate_candles({"INFY": bars}, timeframe="5m")
    s = dq["per_symbol"][0]
    assert s["expected_candles_per_day"] == 75
    assert s["max_candles_in_day"] == 75
    assert s["min_candles_in_day"] == 74
    assert s["first_candle"].startswith(days[0].isoformat())
    assert s["last_candle"].startswith(days[-1].isoformat())
    assert s["worst_completeness_pct"] < 100.0


def test_threshold_failure_days_reported_not_blocked():
    days = _weekdays(2)
    # day 2: drop a scattered ~40% of slots (not a contiguous tail => a real
    # incomplete session, not a short session)
    full = _session("INFY", days[1])
    scattered = [b for i, b in enumerate(full) if i % 5 != 0]  # keep 80%? -> drop 20%
    scattered = [b for i, b in enumerate(scattered) if i % 3 != 0]  # ~ -47% total
    bars = _session("INFY", days[0]) + scattered
    dq = validate_candles({"INFY": bars}, timeframe="5m", min_session_completeness=0.95)
    s = dq["per_symbol"][0]
    assert days[1].isoformat() in s["threshold_failure_days"]
    assert dq["ok"] is True  # threshold failure is a warning, never a block


def test_daily_series_weekend_gaps_are_fine():
    bars = [
        _bar("INFY", datetime(2025, 1, d, 0, 0))
        for d in range(1, 32)
        if date(2025, 1, d).weekday() < 5
    ]
    dq = validate_candles({"INFY": bars}, timeframe="1d")
    assert dq["session_aware"] is False
    assert dq["ok"] is True
    assert not any("gap" in w.lower() or "missing" in w.lower() for w in dq["warnings"])
