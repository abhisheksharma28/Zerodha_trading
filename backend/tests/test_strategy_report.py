"""Ad-hoc strategy backtest report: runner + PDF rendering.

The runner is exercised with a monkey-patched broker client and synthetic
candles (no network, no DB), then the PDF renderer is run over the real
result and the output is checked to be a well-formed PDF.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from app.backtesting import adhoc
from app.backtesting.adhoc import AdhocReport, run_adhoc
from app.backtesting.report_pdf import render_pdf
from app.core.exceptions import ValidationError
from app.strategies.base import Bar

IST = "+05:30"


def _bars(sym: str, n: int = 260) -> list[Bar]:
    days, k = [], 0
    while len(days) < n:
        d = date(2024, 1, 1) + timedelta(days=k)
        if d.weekday() < 5:
            days.append(d)
        k += 1
    out = []
    px = 100.0
    for i, d in enumerate(days):
        # gentle trend with a wobble so ATR > 0 and there are breakouts
        px = 100 + i * 0.4 + (5 if (i // 15) % 2 else -3)
        ts = datetime(d.year, d.month, d.day).strftime("%Y-%m-%dT00:00:00") + IST
        out.append(Bar(timestamp=ts, open=px, high=px + 2, low=px - 2, close=px,
                       volume=200_000.0, instrument=sym))
    return out


@pytest.fixture()
def patched(monkeypatch):
    monkeypatch.setattr(adhoc.broker_service, "build_authenticated_client",
                        lambda db, settings: object())
    monkeypatch.setattr(adhoc, "resolve_instrument_token",
                        lambda s: (str(abs(hash(s)) % 10_000_000), s.split(":")[-1]))
    monkeypatch.setattr(adhoc, "get_candles",
                        lambda client, token, ts, interval, frm, to: _bars(ts))
    yield


def test_run_adhoc_happy_path_then_pdf(patched):
    report = run_adhoc(
        None, None, slug="donchian-breakout", symbols=["NSE:RELIANCE", "NSE:INFY"],
        timeframe="1d", preset="balanced", capital=1_000_000.0,
    )
    assert isinstance(report, AdhocReport)
    assert report.used_symbols == ["INFY", "RELIANCE"]
    assert "return_pct" in report.metrics and "sharpe_ratio" in report.metrics
    assert report.equity_curve and report.charts
    assert any("not investment advice" in c for c in report.caveats)

    pdf = render_pdf(report)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 2000  # a few real pages


def test_run_adhoc_rejects_bad_input(patched):
    with pytest.raises(ValidationError):
        run_adhoc(None, None, slug="no-such-strategy", symbols=["NSE:INFY"])
    with pytest.raises(ValidationError):
        run_adhoc(None, None, slug="donchian-breakout", symbols=[])
    with pytest.raises(ValidationError):
        run_adhoc(None, None, slug="donchian-breakout",
                  symbols=[f"S{i}" for i in range(40)])
    with pytest.raises(ValidationError):
        run_adhoc(None, None, slug="donchian-breakout", symbols=["NSE:INFY"], preset="nope")


def test_run_adhoc_rejects_unsupported_timeframe(patched):
    # trend-following declares SUPPORTED_TIMEFRAMES = ("1d",)
    with pytest.raises(ValidationError):
        run_adhoc(None, None, slug="trend-following", symbols=["NSE:INFY"], timeframe="5m")


def test_run_adhoc_reports_skipped_symbols(monkeypatch, patched):
    def _resolve(s):
        if "BADSYM" in s:
            raise ValueError("unknown")
        return (str(abs(hash(s)) % 9_999_999), s.split(":")[-1])

    monkeypatch.setattr(adhoc, "resolve_instrument_token", _resolve)
    report = run_adhoc(None, None, slug="donchian-breakout",
                       symbols=["NSE:INFY", "NSE:BADSYM"], timeframe="1d")
    assert report.used_symbols == ["INFY"]
    assert report.skipped and report.skipped[0]["symbol"] == "NSE:BADSYM"


def test_render_pdf_handles_zero_trade_report():
    empty = AdhocReport(
        slug="x", strategy_name="X", preset="balanced", timeframe="1d",
        start="2024-01-01", end="2024-06-01", capital=1_000_000.0,
        requested_symbols=["INFY"], used_symbols=["INFY"], skipped=[], parameters={},
        metrics={"return_pct": 0.0, "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0,
                 "total_trades": 0, "win_rate_pct": 0.0, "net_pnl": 0.0, "total_costs": 0.0},
        charts={"drawdown_curve": [], "monthly_returns": {}},
        equity_curve=[["2024-01-01T00:00:00+05:30", 1_000_000.0]],
        per_symbol=[], trades=[], data_quality={"ok": True, "warnings": []},
        caveats=["research only, not investment advice"], generated_at="2024-06-01T00:00:00",
    )
    pdf = render_pdf(empty)
    assert pdf[:5] == b"%PDF-"
