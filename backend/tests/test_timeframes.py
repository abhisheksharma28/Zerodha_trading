"""Canonical timeframe registry + backtest-service timeframe validation."""

from __future__ import annotations

import pytest

from app.backtesting.timeframes import (
    ALL_TIMEFRAMES,
    INTRADAY_TIMEFRAMES,
    UnknownTimeframeError,
    bars_per_year,
    canonical,
    catalog,
    is_intraday,
    kite_interval,
    resolve,
)


@pytest.mark.parametrize(
    "alias,expected",
    [
        ("5m", "5m"), ("5", "5m"), ("5min", "5m"), ("5minute", "5m"), ("5MINUTE", "5m"),
        ("1h", "1h"), ("60m", "1h"), ("60minute", "1h"), ("hour", "1h"),
        ("1d", "1d"), ("day", "1d"), ("DAILY", "1d"), ("eod", "1d"),
        ("1m", "1m"), ("minute", "1m"), ("15minutes", "15m"),
    ],
)
def test_alias_resolution(alias, expected):
    assert canonical(alias) == expected


def test_unknown_timeframe_raises():
    with pytest.raises(UnknownTimeframeError):
        resolve("7m")


def test_kite_interval_mapping():
    assert kite_interval("5m") == "5minute"
    assert kite_interval("1h") == "60minute"
    assert kite_interval("1d") == "day"
    assert kite_interval("day") == "day"


def test_intraday_flag_and_bar_counts():
    assert is_intraday("5m") and not is_intraday("1d")
    # 375-minute session, ~250 days: 5m -> 75 bars/day -> 18,750/yr
    assert bars_per_year("5m") == pytest.approx(18_750)
    assert bars_per_year("1d") == pytest.approx(250)
    # finer bars => more bars per year
    assert bars_per_year("1m") > bars_per_year("5m") > bars_per_year("1h") > bars_per_year("1d")


def test_catalog_shape():
    cat = catalog()
    assert {c["token"] for c in cat} == set(ALL_TIMEFRAMES)
    assert all({"token", "label", "kite_interval", "minutes", "intraday", "bars_per_year"} <= c.keys()
               for c in cat)


def test_intraday_set_excludes_daily():
    assert "1d" not in INTRADAY_TIMEFRAMES
    assert set(INTRADAY_TIMEFRAMES) < set(ALL_TIMEFRAMES)


def test_backtest_service_rejects_unsupported_timeframe_for_template():
    """A daily-only template must refuse an intraday backtest with a clear reason."""
    from app.core.exceptions import ValidationError
    from app.services.backtest_service import _validate_timeframe_supported
    from app.strategies.library import CrossSectionalMomentumStrategy
    from app.strategies.library.seeding import shim_source

    class _V:
        source_code = shim_source(CrossSectionalMomentumStrategy)
        entry_point = "Strategy"

    _validate_timeframe_supported(_V(), "1d")  # ok
    with pytest.raises(ValidationError) as exc:
        _validate_timeframe_supported(_V(), "5m")
    assert "does not support" in str(exc.value) and "1d" in str(exc.value)


def test_backtest_service_allows_intraday_for_intraday_template():
    from app.services.backtest_service import _validate_timeframe_supported
    from app.strategies.library import OpeningRangeBreakoutStrategy
    from app.strategies.library.seeding import shim_source

    class _V:
        source_code = shim_source(OpeningRangeBreakoutStrategy)
        entry_point = "Strategy"

    _validate_timeframe_supported(_V(), "5m")  # no raise


def test_unrestricted_user_strategy_not_blocked():
    """A hand-written BaseStrategy with no SUPPORTED_TIMEFRAMES declaration
    runs on any timeframe."""
    from app.services.backtest_service import _validate_timeframe_supported

    src = (
        "from app.strategies.base import BaseStrategy\n"
        "class Strategy(BaseStrategy):\n"
        "    def on_bar(self, bar):\n        pass\n"
    )

    class _V:
        source_code = src
        entry_point = "Strategy"

    _validate_timeframe_supported(_V(), "3m")  # no raise
