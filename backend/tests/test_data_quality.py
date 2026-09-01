"""Data-quality validation tests (no DB)."""

from app.backtesting.data_quality import validate_candles
from app.strategies.base import Bar


def _bar(ts, o, h, low, c, v=1000, sym="X"):
    return Bar(timestamp=ts, open=o, high=h, low=low, close=c, volume=v, instrument=sym)


def _good_day(i):
    return _bar(f"2026-01-{i + 1:02d}T00:00:00+05:30", 100, 101, 99, 100.5)


def test_clean_data_is_ok():
    report = validate_candles({"X": [_good_day(i) for i in range(40)]})
    assert report["ok"] is True
    assert report["errors"] == []


def test_invalid_ohlc_is_a_hard_error():
    bars = [_good_day(i) for i in range(35)]
    bars.append(_bar("2026-02-05T00:00:00+05:30", 100, 90, 95, 99))  # high < low, high < open
    report = validate_candles({"X": bars})
    assert report["ok"] is False
    assert any("invalid OHLC" in e for e in report["errors"])


def test_duplicate_and_out_of_order_timestamps_are_hard_errors():
    bars = [
        _bar("2026-01-01T00:00:00+05:30", 100, 101, 99, 100),
        _bar("2026-01-01T00:00:00+05:30", 100, 101, 99, 100),   # duplicate
        _bar("2025-12-30T00:00:00+05:30", 100, 101, 99, 100),   # goes backwards
    ]
    report = validate_candles({"X": bars})
    assert report["ok"] is False
    joined = " ".join(report["errors"])
    assert "duplicate" in joined and "out-of-order" in joined


def test_thin_history_and_naive_timestamps_are_warnings_not_errors():
    bars = [_bar(f"2026-01-{i + 1:02d}T00:00:00", 100, 101, 99, 100) for i in range(10)]
    report = validate_candles({"X": bars})
    assert report["ok"] is True
    joined = " ".join(report["warnings"])
    assert "thin history" in joined and "without a timezone" in joined


def test_large_gap_is_flagged_as_a_warning():
    bars = [_bar(f"2026-01-{i + 1:02d}T00:00:00+05:30", 100, 101, 99, 100) for i in range(20)]
    bars.append(_bar("2026-06-01T00:00:00+05:30", 100, 101, 99, 100))  # months later
    report = validate_candles({"X": bars})
    assert report["ok"] is True
    assert any("large gaps" in w for w in report["warnings"])
