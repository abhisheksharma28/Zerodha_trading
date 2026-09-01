"""Synthetic HNI backtest + paper lifecycle / idempotency / recovery."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from app.backtesting.options_runner import run_hni_backtest
from app.models.enums import OptionsStrategyStatus, TradingMode
from app.options.expiry import calendar_dte, monthly_expiries
from app.services import options_strategy_service as svc
from app.strategies.options.hni_monthly import HniConfig
from app.strategies.options.market_data import SyntheticOptionData


def _spot_path(start: date, end: date, base: float = 24_000.0, drift: float = 0.0006) -> dict[date, float]:
    out: dict[date, float] = {}
    d = start
    i = 0
    while d <= end:
        out[d] = base * (1 + drift) ** i + 40 * math.sin(i / 5)
        d += timedelta(days=1)
        i += 1
    return out


def test_synthetic_backtest_runs_and_is_flagged():
    exps = monthly_expiries("NIFTY")
    target = next(e for e in exps if calendar_dte(e, date.today()) >= 44)
    start = target - timedelta(days=60)
    end = target - timedelta(days=1)
    md = SyntheticOptionData(_spot_path(start, end), vol=0.13, margin=None)
    cfg = HniConfig.from_dict({"min_dte": 30, "max_dte": 55, "max_credit_percent": 100.0})
    report = run_hni_backtest(cfg, md, start=start, end=end)

    assert report["synthetic_data"] is True
    assert "SYNTHETIC" in report["data_warning"]
    assert report["entries"] >= 1
    m = report["metrics"]
    for k in ("net_pnl", "total_costs", "hni_entries", "target_hit_pct", "stop_loss_pct",
              "short_strike_exit_pct", "avg_holding_days", "avg_credit_pct",
              "return_on_deployed_capital_pct"):
        assert k in m
    # every trade carries an exit reason from the exit engine
    assert all(t["exit_reason"] in
               ("TARGET", "STOP_LOSS", "SHORT_STRIKE_EXIT", "TIME_EXIT", "EXPIRY_EXIT")
               for t in report["trades"])


def test_backtest_is_deterministic():
    exps = monthly_expiries("NIFTY")
    target = next(e for e in exps if calendar_dte(e, date.today()) >= 44)
    start, end = target - timedelta(days=55), target - timedelta(days=2)
    cfg = HniConfig.from_dict({"min_dte": 30, "max_dte": 55, "max_credit_percent": 100.0})
    sp = _spot_path(start, end)
    a = run_hni_backtest(cfg, SyntheticOptionData(dict(sp), vol=0.13), start=start, end=end)
    b = run_hni_backtest(cfg, SyntheticOptionData(dict(sp), vol=0.13), start=start, end=end)
    assert a["metrics"]["net_pnl"] == b["metrics"]["net_pnl"]
    assert a["trades"] == b["trades"]


# --- paper lifecycle (needs the DB fixture) --------------------------------

def _qualifying_now(cfg_expiry_target=None):
    exps = monthly_expiries("NIFTY")
    target = cfg_expiry_target or next(e for e in exps if calendar_dte(e, date.today()) >= 44)
    d = target - timedelta(days=41)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return datetime(d.year, d.month, d.day, 15, 16), target, calendar_dte(target, d)


def test_paper_enter_monitor_exit_lifecycle(db):
    now, expiry, dte = _qualifying_now()
    inst = svc.create_instance(
        db, mode=TradingMode.PAPER, preset="as_specified",
        overrides={"min_dte": dte - 1, "max_dte": dte + 1, "max_credit_percent": 100.0},
        as_of=now.date(),
    )
    assert inst.status == OptionsStrategyStatus.CREATED
    assert inst.basket_id.startswith("nifty-monthly-hni:paper:")

    # spot path: flat then a rally through the short strike to force an exit
    days = [expiry - timedelta(days=k) for k in range(dte + 2, -1, -1)]
    path = dict.fromkeys(days, 24500.0)
    for d in days[len(days) // 2:]:
        path[d] = 26_500.0  # well above the ~25_100 short strike -> big loss -> SHORT_STRIKE_EXIT
    md = SyntheticOptionData(path, vol=0.13, margin=1_000_000.0)

    entered = svc.enter(db, inst.id, md, as_of=now)
    assert entered.status == OptionsStrategyStatus.ACTIVE
    assert entered.strike_b == entered.strike_a + 300 == entered.strike_c - 300
    assert entered.deployed_capital == 1_000_000.0
    assert entered.deployed_capital_source == "broker"
    assert abs(float(entered.target_amount) - 15_000.0) < 1e-6
    assert abs(float(entered.stop_loss_amount) - 20_000.0) < 1e-6
    assert len(entered.basket["legs"]) == 3

    # monitor forward day by day until it exits
    out = entered
    for k in range(1, dte + 1):
        out = svc.monitor(db, inst.id, md, now=now + timedelta(days=k))
        if out.status != OptionsStrategyStatus.ACTIVE:
            break
    assert out.status in (OptionsStrategyStatus.SHORT_STRIKE_EXIT, OptionsStrategyStatus.STOP_LOSS,
                          OptionsStrategyStatus.EXPIRY_EXIT, OptionsStrategyStatus.TIME_EXIT)
    assert out.net_pnl is not None and out.exit_reason


def test_idempotency_blocks_a_second_non_terminal_instance(db):
    now, expiry, dte = _qualifying_now()
    svc.create_instance(db, mode=TradingMode.PAPER, as_of=now.date())
    try:
        svc.create_instance(db, mode=TradingMode.PAPER, as_of=now.date())
        raise AssertionError("expected a conflict")
    except Exception as exc:  # ConflictError
        assert "already exists" in str(exc)


def test_live_mode_is_refused(db):
    try:
        svc.create_instance(db, mode=TradingMode.LIVE)
        raise AssertionError("expected a validation error")
    except Exception as exc:
        assert "not enabled" in str(exc).lower()


def test_recovery_marks_unmatched_live_instance_failed(db):
    # craft a LIVE instance directly (bypassing create) to exercise recovery
    from app.models.options_strategy import OptionsStrategyInstance

    inst = OptionsStrategyInstance(
        slug="nifty-monthly-hni", mode=TradingMode.LIVE,
        status=OptionsStrategyStatus.ACTIVE, config=HniConfig().to_dict(),
        basket_id="nifty-monthly-hni:live:test", underlying="NIFTY",
        basket={"legs": [{"tradingsymbol": "NIFTYXX25100CE"}]},
    )
    db.add(inst)
    db.commit()

    class _NoPositions:
        def get_positions(self):
            return {"net": []}

    recon = svc.recover_live_instances(db, _NoPositions())
    db.refresh(inst)
    assert recon == []
    assert inst.status == OptionsStrategyStatus.FAILED
    assert "duplicate" in inst.not_eligible_reason.lower()
