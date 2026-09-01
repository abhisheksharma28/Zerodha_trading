"""NIFTY Monthly HNI strategy — expiry, strike selection, credit, exits.

Pure unit tests with a synthetic MarketData (deterministic Black-Scholes
call prices) and a synthetic strike grid. No network, no DB, no broker.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import pytest

from app.options.expiry import calendar_dte, monthly_expiries, select_monthly_expiry
from app.strategies.options.base import LegQuote, OptionLeg
from app.strategies.options.hni_monthly import (
    HniConfig,
    basket_pnl,
    evaluate_entry,
    evaluate_exit,
)

IST = None  # timestamps are naive IST throughout these tests


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_call(spot: float, strike: float, t_years: float, vol: float = 0.14, r: float = 0.065) -> float:
    if t_years <= 0:
        return max(0.0, spot - strike)
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    return spot * _ncdf(d1) - strike * math.exp(-r * t_years) * _ncdf(d2)


class FakeMarketData:
    """Synthetic chain: 50-point grid, BS-priced calls, tight spreads."""

    def __init__(self, spot: float, expiry: date, *, vol: float = 0.14, margin: float | None = 1_000_000.0,
                 spread_frac: float = 0.01, bad_leg: float | None = None, wide_leg: float | None = None):
        self._spot = spot
        self._expiry = expiry
        self._vol = vol
        self._margin = margin
        self._spread_frac = spread_frac
        self._bad_leg = bad_leg
        self._wide_leg = wide_leg

    def spot(self, underlying, as_of):
        return self._spot

    def call_strikes(self, underlying, expiry, as_of):
        lo = int((self._spot - 1500) // 50 * 50)
        return [float(lo + 50 * i) for i in range(80)]

    def option_quote(self, underlying, expiry, strike, option_type, as_of):
        t = max(1e-6, (expiry - as_of.date()).days / 365.0)
        mid = _bs_call(self._spot, strike, t, self._vol)
        if self._bad_leg is not None and abs(strike - self._bad_leg) < 1:
            return LegQuote(bid=0.0, ask=0.10, last=0.05)
        sf = self._spread_frac
        if self._wide_leg is not None and abs(strike - self._wide_leg) < 1:
            sf = 0.30
        half = max(0.05, mid * sf)
        return LegQuote(bid=round(mid - half, 2), ask=round(mid + half, 2), last=round(mid, 2),
                        volume=100000, oi=500000)

    def basket_margin(self, legs, as_of):
        return self._margin


# --------------------------------------------------------------------------
# expiry / DTE
# --------------------------------------------------------------------------

def test_monthly_expiry_is_last_listed_of_month():
    exps = monthly_expiries("NIFTY")
    assert exps == sorted(exps)
    months = [(e.year, e.month) for e in exps]
    assert len(months) == len(set(months)), "one monthly expiry per calendar month"


def test_select_monthly_expiry_dte_window_and_friday():
    exps = monthly_expiries("NIFTY")
    target = next(e for e in exps if calendar_dte(e, date.today()) >= 45)
    # find a Friday 39-43 days before that expiry
    for back in range(38, 46):
        d = target - timedelta(days=back)
        if d.weekday() == 4:
            sel = select_monthly_expiry("NIFTY", d, min_dte=39, max_dte=43)
            if 39 <= sel.dte <= 43:
                assert sel.eligible and sel.expiry == target
                # same date but pretend it's Wednesday -> not eligible
                wed = d - timedelta(days=2)
                assert not select_monthly_expiry("NIFTY", wed, min_dte=39, max_dte=43).eligible
                return
    pytest.skip("no qualifying Friday in the available expiry list")


def test_dte_outside_window_is_reported():
    exps = monthly_expiries("NIFTY")
    e = exps[1]
    d = e - timedelta(days=20)          # 20 DTE, well outside 39-43
    while d.weekday() != 4:
        d -= timedelta(days=1)
    sel = select_monthly_expiry("NIFTY", d, min_dte=39, max_dte=43)
    assert not sel.eligible and "DTE" in sel.reason


# --------------------------------------------------------------------------
# entry: strikes, ratio, credit, deployed capital, gates
# --------------------------------------------------------------------------

def _qualifying_entry(**md_over):
    """Build a datetime + expiry that passes weekday/time/DTE, return
    (cfg, as_of, md)."""
    exps = monthly_expiries("NIFTY")
    target = next(e for e in exps if calendar_dte(e, date.today()) >= 44)
    d = target - timedelta(days=41)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    dte = calendar_dte(target, d)
    cfg = HniConfig.from_dict({"min_dte": dte - 1, "max_dte": dte + 1})
    as_of = datetime(d.year, d.month, d.day, 15, 16)
    md = FakeMarketData(spot=24_500.0, expiry=target, **md_over)
    return cfg, as_of, md, target


def test_entry_builds_1_3_2_call_structure_with_snapped_strikes():
    cfg, as_of, md, expiry = _qualifying_entry()
    dec = evaluate_entry(cfg, as_of, md)
    assert dec.eligible, dec.reason
    b = dec.basket
    assert [leg.label for leg in b.legs] == ["A", "B", "C"]
    assert [leg.action for leg in b.legs] == ["BUY", "SELL", "BUY"]
    assert [leg.lots for leg in b.legs] == [1, 3, 2]
    a, sb, c = (leg.strike for leg in b.legs)
    assert a == 24_800 and sb == 25_100 and c == 25_400          # spot 24500 + 300/300/300
    assert sb - a == 300 and c - sb == 300
    assert b.short_strike == sb
    # quantities use the real/fallback lot size, ratio preserved
    q = [leg.quantity for leg in b.legs]
    assert q[1] == 3 * q[0] and q[2] == 2 * q[0]
    # theoretical vs actual recorded
    assert all(hasattr(leg, "theoretical_strike") for leg in b.legs)


def test_entry_credit_and_deployed_capital_and_targets():
    cfg, as_of, md, expiry = _qualifying_entry(margin=1_000_000.0)
    dec = evaluate_entry(cfg, as_of, md)
    b = dec.basket
    lot = b.lot_size
    qa = md.option_quote("NIFTY", expiry, 24_800, "CE", as_of)
    qb = md.option_quote("NIFTY", expiry, 25_100, "CE", as_of)
    qc = md.option_quote("NIFTY", expiry, 25_400, "CE", as_of)
    expected_credit = lot * (3 * qb.bid - qa.ask - 2 * qc.ask)
    assert abs(b.net_credit - expected_credit) < 1e-6
    assert b.deployed_capital == 1_000_000.0 and b.deployed_capital_source == "broker"
    assert abs(b.credit_pct - expected_credit / 1_000_000.0 * 100) < 1e-9
    assert abs(b.target_amount - 1_000_000.0 * cfg.target_percent / 100) < 1e-6
    assert abs(b.stop_loss_amount - 1_000_000.0 * cfg.stop_loss_percent / 100) < 1e-6


def test_deployed_capital_falls_back_when_no_broker_margin():
    cfg, as_of, md, expiry = _qualifying_entry(margin=None)
    dec = evaluate_entry(cfg, as_of, md)
    assert dec.eligible
    assert dec.basket.deployed_capital_source == "fallback"
    assert dec.basket.deployed_capital == cfg.fallback_margin_per_short_lot * 3


def test_entry_rejected_when_initial_credit_exceeds_max():
    cfg, as_of, md, expiry = _qualifying_entry()
    cfg = HniConfig.from_dict({**cfg.to_dict(), "max_credit_percent": -5.0})  # force a fail
    dec = evaluate_entry(cfg, as_of, md)
    assert not dec.eligible and "credit" in dec.reason.lower()


def test_entry_rejected_on_illiquid_leg():
    cfg, as_of, md, expiry = _qualifying_entry(bad_leg=25_100.0)  # zero-bid short leg
    dec = evaluate_entry(cfg, as_of, md)
    assert not dec.eligible and "illiquid" in dec.reason.lower()


def test_entry_rejected_on_wide_spread():
    cfg, as_of, md, expiry = _qualifying_entry(wide_leg=25_400.0)
    dec = evaluate_entry(cfg, as_of, md)
    assert not dec.eligible and "spread" in dec.reason.lower()


def test_entry_rejected_off_weekday_and_off_time():
    cfg, as_of, md, expiry = _qualifying_entry()
    assert not evaluate_entry(cfg, as_of.replace(hour=14, minute=0), md).eligible
    assert not evaluate_entry(cfg, as_of + timedelta(days=1), md).eligible  # Saturday


def test_entry_is_deterministic():
    cfg, as_of, md, expiry = _qualifying_entry()
    a = evaluate_entry(cfg, as_of, md).basket.to_dict()
    b = evaluate_entry(cfg, as_of, FakeMarketData(24_500.0, expiry)).basket.to_dict()
    assert a == b


# --------------------------------------------------------------------------
# exits
# --------------------------------------------------------------------------

def _basket(dc=1_000_000.0, target_pct=1.5, sl_pct=2.0, entry_prices=(120.0, 60.0, 25.0),
            expiry=None):
    expiry = expiry or (date.today() + timedelta(days=25))
    lot = 75
    legs = []
    for (label, action, lots), ep in zip(
        [("A", "BUY", 1), ("B", "SELL", 3), ("C", "BUY", 2)], entry_prices, strict=True
    ):
        legs.append(OptionLeg(label=label, action=action, option_type="CE",
                              strike={"A": 24_800, "B": 25_100, "C": 25_400}[label],
                              expiry=expiry, lots=lots, lot_size=lot,
                              tradingsymbol=f"X{label}", instrument_token=f"T{label}",
                              entry_price=ep))
    from app.strategies.options.base import BasketSpec

    return BasketSpec(
        underlying="NIFTY", expiry=expiry, spot_at_entry=24_500.0, lot_size=lot, legs=legs,
        net_credit=lot * (3 * entry_prices[1] - entry_prices[0] - 2 * entry_prices[2]),
        credit_pct=0.0, deployed_capital=dc, deployed_capital_source="broker",
        target_amount=dc * target_pct / 100, stop_loss_amount=dc * sl_pct / 100,
        short_strike=25_100,
    )


def _prices_for_pnl(basket, target_pnl):
    """Move only the short leg to hit a given basket P&L (short leg dir = -1),
    keeping A and C at their entry price (0 contribution)."""
    b = basket.legs[1]
    # pnl_B = signed_dir * (cur - entry) * qty  ==>  cur = entry + target / (signed_dir * qty)
    cur_b = b.entry_price + target_pnl / (b.signed_dir * b.quantity)
    return {"A": basket.legs[0].entry_price, "B": cur_b, "C": basket.legs[2].entry_price}


def test_target_exit():
    b = _basket()
    now = datetime.now()
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                        spot=24_600, prev_spot=24_580, leg_prices=_prices_for_pnl(b, b.target_amount + 1))
    assert dec.should_exit and dec.reason == "TARGET"


def test_stop_loss_exit():
    b = _basket()
    now = datetime.now()
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                        spot=24_900, prev_spot=24_850,
                        leg_prices=_prices_for_pnl(b, -b.stop_loss_amount - 1))
    assert dec.should_exit and dec.reason == "STOP_LOSS"


def test_short_strike_cross_requires_loss_breach():
    b = _basket()
    now = datetime.now()
    # crossed the short strike but only a small loss -> no short-strike exit
    small_loss = _prices_for_pnl(b, -b.stop_loss_amount / 2)
    d1 = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                       spot=25_150, prev_spot=25_050, leg_prices=small_loss)
    assert d1.reason != "SHORT_STRIKE_EXIT"
    # crossed AND loss > 2% -> short-strike exit
    big_loss = _prices_for_pnl(b, -b.stop_loss_amount - 100)
    d2 = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                       spot=25_150, prev_spot=25_050, leg_prices=big_loss)
    assert d2.should_exit and d2.reason == "SHORT_STRIKE_EXIT"


def test_short_strike_first_tick_already_above_counts_as_cross():
    b = _basket()
    now = datetime.now()
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                        spot=25_200, prev_spot=None,
                        leg_prices=_prices_for_pnl(b, -b.stop_loss_amount - 50))
    assert dec.should_exit and dec.reason == "SHORT_STRIKE_EXIT"


def test_expiry_safety_exit_takes_precedence():
    exp = date.today() + timedelta(days=2)
    b = _basket(expiry=exp)
    now = datetime.now()
    # even at target P&L, the 2-DTE safety exit wins
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=18),
                        spot=24_600, prev_spot=24_580,
                        leg_prices=_prices_for_pnl(b, b.target_amount + 5))
    assert dec.should_exit and dec.reason == "EXPIRY_EXIT"


def test_time_exit_after_max_holding_days():
    b = _basket()
    now = datetime.now()
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=20),
                        spot=24_600, prev_spot=24_590,
                        leg_prices={"A": b.legs[0].entry_price, "B": b.legs[1].entry_price,
                                    "C": b.legs[2].entry_price})
    assert dec.should_exit and dec.reason == "TIME_EXIT"


def test_stop_beats_target_when_both_conditions_hold():
    # deployed capital tiny so target is trivially hit; also force a big loss
    b = _basket(dc=1000.0)
    now = datetime.now()
    dec = evaluate_exit(HniConfig(), b, now=now, entry_time=now - timedelta(days=5),
                        spot=25_150, prev_spot=25_050,
                        leg_prices=_prices_for_pnl(b, -b.stop_loss_amount - 1))
    assert dec.reason in ("SHORT_STRIKE_EXIT", "STOP_LOSS")  # a risk exit, never TARGET


def test_basket_pnl_combines_all_legs():
    b = _basket(entry_prices=(100.0, 50.0, 20.0))
    flat = {"A": 100.0, "B": 50.0, "C": 20.0}
    assert basket_pnl(b, flat) == 0.0
    # short leg (3 lots) rises 10 -> loss of 10 * 3 * lot
    up = {"A": 100.0, "B": 60.0, "C": 20.0}
    assert basket_pnl(b, up) == -10.0 * 3 * b.lot_size
