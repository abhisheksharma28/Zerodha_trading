"""NIFTY Monthly HNI Strategy — 1:3:2 CALL ratio structure.

Structure (all same underlying / expiry / CALL):

    BUY  1 lot  CE at strike A  (~otm_distance OTM from spot)
    SELL 3 lots CE at strike B  (~strike_spacing above A)   <- the short leg
    BUY  2 lots CE at strike C  (~strike_spacing above B)

Entry: Friday, monthly expiry 39-43 DTE, at 15:16 IST. Exit on target
(+target_percent of deployed capital), stop (-stop_loss_percent), the short
strike being crossed while already down more than stop_loss_percent, a max
holding period, or a safety exit before expiry.

This module is pure logic. See app/strategies/options/base.py for the
MarketData interface the execution layers supply.

---------------------------------------------------------------------------
Documented assumptions (spec "IMPORTANT AMBIGUITIES"); all overridable:

1.  "300 points OTM" = spot + otm_distance, then snapped to the nearest
    listed strike (app.options.chain.select_ratio_strikes). The theoretical
    strike, actual strike and difference are recorded on every leg.
2.  Strike rounding: nearest listed strike, ties broken toward the lower
    strike. Requires three strictly-increasing distinct listed strikes or
    the entry is rejected (never a silent arbitrary pick).
3.  Deployed capital = broker basket margin (MarketData.basket_margin). If
    that is unavailable, a documented per-short-lot fallback is used and the
    source is recorded as "fallback".
4.  Credit for the eligibility check uses **executable** prices: sell the
    short leg at its bid, buy the long legs at their ask (the least
    favourable, most conservative net credit). Final P&L uses actual fill
    prices.
5.  "Crosses the selling leg" = spot goes from <= short strike to > short
    strike (strict), AND combined strategy loss > stop_loss_percent. If the
    first monitored tick is already above the short strike, that counts as a
    cross.
6.  Max holding period: max_holding_days calendar days (default 20), plus a
    hard safety exit exit_before_expiry_days before expiry (default 3).
7.  If target and a stop/risk condition are both true on the same tick, the
    risk exit wins (EXPIRY > SHORT_STRIKE > STOP_LOSS > TARGET > TIME).
8.  Partial fills / execution failures are the execution layer's job (see
    the options worker); this module only emits signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, ClassVar

from app.options.chain import CallChain, select_ratio_strikes
from app.options.expiry import calendar_dte, select_monthly_expiry
from app.options.instruments_nfo import lot_size_for
from app.strategies.library.base import ParamSpec
from app.strategies.options.base import (
    BasketSpec,
    EntryDecision,
    ExitDecision,
    LegQuote,
    MarketData,
    OptionLeg,
)

SLUG = "nifty-monthly-hni"
NAME = "NIFTY Monthly HNI Strategy"

# 1:3:2 CALL ratio. strike_offset is relative to spot and is only a default;
# select_ratio_strikes drives the actual A/B/C spacing off otm_distance +
# strike_spacing so the exchange grid is respected.
LEGS: tuple[dict[str, Any], ...] = (
    {"label": "A", "action": "BUY", "option_type": "CE", "lots": 1, "grid_index": 0},
    {"label": "B", "action": "SELL", "option_type": "CE", "lots": 3, "grid_index": 1},
    {"label": "C", "action": "BUY", "option_type": "CE", "lots": 2, "grid_index": 2},
)

PARAMS: dict[str, ParamSpec] = {
    "underlying": ParamSpec("string", "NIFTY", "Underlying index.", group="core"),
    "entry_weekday": ParamSpec("enum", "FRIDAY", "Weekday entries are allowed on.",
                               choices=("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"),
                               group="core"),
    "entry_time_ist": ParamSpec("string", "15:16", "Entry time, IST (HH:MM).", group="core"),
    "min_dte": ParamSpec("integer", 39, "Minimum calendar DTE to the monthly expiry.",
                         min=1, max=120, group="core"),
    "max_dte": ParamSpec("integer", 43, "Maximum calendar DTE to the monthly expiry.",
                         min=1, max=120, group="core"),
    "otm_distance": ParamSpec("number", 300.0, "Points OTM from spot for strike A.",
                              min=0.0, max=5000.0, group="core"),
    "strike_spacing": ParamSpec("number", 300.0, "Points between A→B and B→C.",
                                min=50.0, max=5000.0, group="core"),
    "target_percent": ParamSpec("number", 1.5, "Target as % of deployed capital.",
                                min=0.01, max=100.0, group="risk"),
    "stop_loss_percent": ParamSpec("number", 2.0, "Stop loss as % of deployed capital.",
                                   min=0.01, max=100.0, group="risk"),
    "max_credit_percent": ParamSpec("number", 1.5,
                                    "Maximum acceptable initial net credit, % of deployed capital. "
                                    "Entry is rejected above this.", min=-100.0, max=100.0,
                                    group="risk"),
    "min_credit_percent": ParamSpec("number", -100.0,
                                    "Reject entry if the initial structure is a debit worse than "
                                    "this % (default: no floor, matching the sheet).",
                                    min=-100.0, max=100.0, group="risk"),
    "max_holding_days": ParamSpec("integer", 20, "Calendar-day time exit.", min=1, max=90,
                                  group="risk"),
    "exit_before_expiry_days": ParamSpec("integer", 3,
                                         "Hard safety exit this many calendar days before expiry.",
                                         min=0, max=20, group="risk"),
    "max_leg_spread_pct": ParamSpec("number", 8.0,
                                    "Reject a leg whose bid/ask spread exceeds this % of mid.",
                                    min=0.0, max=100.0, group="filter"),
    "min_leg_bid": ParamSpec("number", 0.05, "Reject a leg with a bid below this (illiquid).",
                             min=0.0, max=1000.0, group="filter"),
    "fallback_margin_per_short_lot": ParamSpec("number", 150000.0,
                                               "Deployed-capital fallback per short (B) lot when "
                                               "broker margin is unavailable.",
                                               min=1000.0, max=10_000_000.0, group="risk"),
    "exchange": ParamSpec("string", "NFO", "Order exchange for the legs.", group="core"),
    "product": ParamSpec("enum", "NRML", "Order product.", choices=("NRML", "MIS"), group="core"),
}

PRESETS: dict[str, dict[str, Any]] = {
    "as_specified": {
        "min_dte": 39, "max_dte": 43, "otm_distance": 300.0, "strike_spacing": 300.0,
        "target_percent": 1.5, "stop_loss_percent": 2.0, "max_credit_percent": 1.5,
        "max_holding_days": 20, "exit_before_expiry_days": 3,
    },
    "conservative": {
        "otm_distance": 400.0, "strike_spacing": 300.0, "target_percent": 1.0,
        "stop_loss_percent": 1.5, "max_credit_percent": 1.5, "max_holding_days": 15,
        "exit_before_expiry_days": 5, "max_leg_spread_pct": 5.0,
    },
    "aggressive": {
        "otm_distance": 250.0, "strike_spacing": 300.0, "target_percent": 2.0,
        "stop_loss_percent": 2.5, "max_credit_percent": 2.0, "max_holding_days": 22,
        "exit_before_expiry_days": 2,
    },
}

METADATA: dict[str, Any] = {
    "slug": SLUG,
    "name": NAME,
    "category": "Options — Ratio Spread",
    "underlying": "NIFTY",
    "structure": "BUY 1 A CE  /  SELL 3 B CE  /  BUY 2 C CE  (same monthly expiry)",
    "time_horizon": "Positional (≈15–20 days)",
    "complexity": "High",
    "supports_backtest": True,
    "supports_paper": True,
    "supports_live": True,
    "warning": (
        "Research template. A 1:3:2 call ratio carries net short gamma/vega around the middle "
        "strike; a fast rally through the short strike produces accelerating losses until the "
        "long C leg catches up. Not guaranteed or risk-free. Requires historical option-chain "
        "data for a faithful backtest."
    ),
}


@dataclass
class HniConfig:
    underlying: str = "NIFTY"
    entry_weekday: str = "FRIDAY"
    entry_time_ist: str = "15:16"
    min_dte: int = 39
    max_dte: int = 43
    otm_distance: float = 300.0
    strike_spacing: float = 300.0
    target_percent: float = 1.5
    stop_loss_percent: float = 2.0
    max_credit_percent: float = 1.5
    min_credit_percent: float = -100.0
    max_holding_days: int = 20
    exit_before_expiry_days: int = 3
    max_leg_spread_pct: float = 8.0
    min_leg_bid: float = 0.05
    fallback_margin_per_short_lot: float = 150000.0
    exchange: str = "NFO"
    product: str = "NRML"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> HniConfig:
        data = data or {}
        resolved: dict[str, Any] = {}
        for name, spec in PARAMS.items():
            resolved[name] = spec.coerce(name, data.get(name))
        unknown = set(data) - set(PARAMS)
        if unknown:
            from app.strategies.library.base import ParamError

            raise ParamError(f"Unknown parameter(s): {sorted(unknown)}")
        return cls(**resolved)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    _WEEKDAYS: ClassVar[dict[str, int]] = {
        "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3, "FRIDAY": 4,
    }

    @property
    def entry_weekday_num(self) -> int:
        return self._WEEKDAYS[self.entry_weekday]

    @property
    def entry_time(self) -> tuple[int, int]:
        hh, mm = self.entry_time_ist.split(":")
        return int(hh), int(mm)


def parameter_schema() -> dict[str, Any]:
    return {name: spec.to_dict() for name, spec in PARAMS.items()}


# --------------------------------------------------------------------------
# ENTRY
# --------------------------------------------------------------------------

def evaluate_entry(cfg: HniConfig, as_of: datetime, md: MarketData) -> EntryDecision:
    """Deterministic. Returns eligible=False with a human reason for every
    non-qualifying case; only builds a basket when every gate passes."""
    d = as_of.date()

    # 1. weekday
    if d.weekday() != cfg.entry_weekday_num:
        return EntryDecision(False, f"Not {cfg.entry_weekday}: {d.strftime('%A')}.", as_of)

    # 2. entry time window (exact minute; the worker only calls this at 15:16)
    want_h, want_m = cfg.entry_time
    if (as_of.hour, as_of.minute) != (want_h, want_m):
        return EntryDecision(
            False,
            f"Outside entry window: {as_of.strftime('%H:%M')} IST, want {cfg.entry_time_ist}.",
            as_of,
        )

    # 3. monthly expiry + DTE
    sel = select_monthly_expiry(cfg.underlying, d, min_dte=cfg.min_dte, max_dte=cfg.max_dte,
                                require_friday=(cfg.entry_weekday == "FRIDAY"))
    if not sel.eligible:
        return EntryDecision(False, f"Not eligible: {sel.reason}", as_of,
                             expiry=sel.expiry, dte=sel.dte)
    expiry = sel.expiry

    # 4. spot
    spot = md.spot(cfg.underlying, as_of)
    if spot is None or spot <= 0:
        return EntryDecision(False, "Not eligible: NIFTY spot unavailable.", as_of, expiry=expiry,
                             dte=sel.dte)

    # 5. strike selection off the real chain
    strikes = md.call_strikes(cfg.underlying, expiry, as_of)
    if len(strikes) < 3:
        return EntryDecision(False, "Not eligible: option chain unavailable / too few strikes.",
                             as_of, spot=spot, expiry=expiry, dte=sel.dte)
    chain = _build_chain(cfg.underlying, expiry, strikes)
    try:
        selections = select_ratio_strikes(chain, spot, otm_distance=cfg.otm_distance,
                                          strike_spacing=cfg.strike_spacing)
    except Exception as exc:  # noqa: BLE001
        return EntryDecision(False, f"Not eligible: strike selection failed — {exc}", as_of,
                             spot=spot, expiry=expiry, dte=sel.dte)
    missing = [s.actual_strike for s in selections if s.actual_strike not in set(strikes)]
    if missing:
        return EntryDecision(False,
                             f"Not eligible: selected strike(s) {missing} not in the data source.",
                             as_of, spot=spot, expiry=expiry, dte=sel.dte)

    # 6. quotes + liquidity per leg
    lot_size = _resolve_lot_size(cfg.underlying, expiry)
    legs: list[OptionLeg] = []
    quotes: dict[str, LegQuote] = {}
    for spec, seln in zip(LEGS, selections, strict=True):
        q = md.option_quote(cfg.underlying, expiry, seln.actual_strike, "CE", as_of)
        if q is None:
            return EntryDecision(False,
                                 f"Not eligible: no quote for leg {spec['label']} "
                                 f"{seln.actual_strike:.0f} CE.",
                                 as_of, spot=spot, expiry=expiry, dte=sel.dte)
        if q.bid < cfg.min_leg_bid:
            return EntryDecision(False,
                                 f"Not eligible: illiquid leg {spec['label']} "
                                 f"({seln.actual_strike:.0f} CE) bid {q.bid:.2f}.",
                                 as_of, spot=spot, expiry=expiry, dte=sel.dte)
        if q.spread_pct > cfg.max_leg_spread_pct:
            return EntryDecision(False,
                                 f"Not eligible: wide spread on leg {spec['label']} "
                                 f"({q.spread_pct:.1f}% > {cfg.max_leg_spread_pct}%).",
                                 as_of, spot=spot, expiry=expiry, dte=sel.dte)
        quotes[spec["label"]] = q
        legs.append(OptionLeg(
            label=spec["label"], action=spec["action"], option_type="CE",
            strike=seln.actual_strike, expiry=expiry, lots=spec["lots"], lot_size=lot_size,
            tradingsymbol=seln.contract.tradingsymbol,
            instrument_token=seln.contract.instrument_token,
            theoretical_strike=seln.theoretical_strike,
            strike_difference=seln.difference,
        ))

    # 7. conservative executable net credit: sell B at bid, buy A/C at ask
    exec_prices = {
        "A": quotes["A"].ask, "B": quotes["B"].bid, "C": quotes["C"].ask,
    }
    net_credit = lot_size * (
        3 * exec_prices["B"] - 1 * exec_prices["A"] - 2 * exec_prices["C"]
    )

    # 8. deployed capital (broker margin, else documented fallback)
    margin = md.basket_margin(legs, as_of)
    if margin and margin > 0:
        deployed_capital, cap_source = float(margin), "broker"
    else:
        short_lots = next(s["lots"] for s in LEGS if s["action"] == "SELL")
        deployed_capital = cfg.fallback_margin_per_short_lot * short_lots
        cap_source = "fallback"

    credit_pct = net_credit / deployed_capital * 100.0 if deployed_capital else 0.0

    # 9. credit gate
    if credit_pct > cfg.max_credit_percent:
        return EntryDecision(
            False,
            f"Not eligible: initial credit = {credit_pct:.2f}%, exceeds {cfg.max_credit_percent}%.",
            as_of, spot=spot, expiry=expiry, dte=sel.dte,
            diagnostics={"net_credit": round(net_credit, 2), "deployed_capital": deployed_capital},
        )
    if credit_pct < cfg.min_credit_percent:
        return EntryDecision(
            False,
            f"Not eligible: initial structure is a debit {credit_pct:.2f}%, "
            f"below floor {cfg.min_credit_percent}%.",
            as_of, spot=spot, expiry=expiry, dte=sel.dte,
        )

    basket = BasketSpec(
        underlying=cfg.underlying, expiry=expiry, spot_at_entry=spot, lot_size=lot_size,
        legs=legs, net_credit=net_credit, credit_pct=credit_pct,
        deployed_capital=deployed_capital, deployed_capital_source=cap_source,
        target_amount=deployed_capital * cfg.target_percent / 100.0,
        stop_loss_amount=deployed_capital * cfg.stop_loss_percent / 100.0,
        short_strike=next(leg.strike for leg in legs if leg.action == "SELL"),
    )
    return EntryDecision(
        True, sel.reason, as_of, spot=spot, expiry=expiry, dte=sel.dte, basket=basket,
        diagnostics={
            "selected_strikes": [s.__dict__ | {"contract": None} for s in selections],
            "exec_prices": exec_prices,
        },
    )


# --------------------------------------------------------------------------
# EXIT
# --------------------------------------------------------------------------

def basket_pnl(basket: BasketSpec, leg_prices: dict[str, float]) -> float:
    """Combined, mark-to-market P&L of the whole basket (INR)."""
    total = 0.0
    for leg in basket.legs:
        cur = leg_prices.get(leg.label)
        if cur is None:
            continue
        total += leg.signed_dir * (cur - leg.entry_price) * leg.quantity
    return total


def evaluate_exit(
    cfg: HniConfig,
    basket: BasketSpec,
    *,
    now: datetime,
    entry_time: datetime,
    spot: float,
    prev_spot: float | None,
    leg_prices: dict[str, float],
) -> ExitDecision:
    """Precedence: EXPIRY > SHORT_STRIKE(+loss) > STOP_LOSS > TARGET > TIME."""
    pnl = basket_pnl(basket, leg_prices)
    dc = basket.deployed_capital or 1.0
    pnl_pct = pnl / dc * 100.0

    dte_left = calendar_dte(basket.expiry, now.date())
    held_days = (now.date() - entry_time.date()).days

    # 4. expiry safety
    if dte_left <= cfg.exit_before_expiry_days:
        return ExitDecision(True, "EXPIRY_EXIT", pnl, pnl_pct,
                            f"{dte_left} calendar days to expiry ≤ {cfg.exit_before_expiry_days}.")

    loss_breached = pnl <= -basket.stop_loss_amount

    # 3. short-strike cross + loss
    crossed = _crossed_above(prev_spot, spot, basket.short_strike)
    if crossed and loss_breached:
        return ExitDecision(True, "SHORT_STRIKE_EXIT", pnl, pnl_pct,
                            f"Spot {spot:.1f} crossed short strike {basket.short_strike:.0f} "
                            f"with loss {pnl_pct:.2f}%.")

    # 2. hard stop
    if loss_breached:
        return ExitDecision(True, "STOP_LOSS", pnl, pnl_pct, f"P&L {pnl_pct:.2f}% ≤ "
                            f"-{cfg.stop_loss_percent}%.")

    # 1. target
    if pnl >= basket.target_amount:
        return ExitDecision(True, "TARGET", pnl, pnl_pct, f"P&L {pnl_pct:.2f}% ≥ "
                            f"+{cfg.target_percent}%.")

    # 5. time exit
    if held_days >= cfg.max_holding_days:
        return ExitDecision(True, "TIME_EXIT", pnl, pnl_pct,
                            f"Held {held_days} days ≥ max {cfg.max_holding_days}.")

    return ExitDecision(False, "", pnl, pnl_pct)


def _crossed_above(prev_spot: float | None, spot: float, strike: float) -> bool:
    if prev_spot is None:
        # First monitored tick: treat "already above" as a cross (spec).
        return spot > strike
    return prev_spot <= strike < spot


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _resolve_lot_size(underlying: str, expiry: date) -> int:
    try:
        return lot_size_for(underlying, expiry)
    except Exception:  # noqa: BLE001 - offline / no dump: fall back to the well-known NIFTY lot
        return 75 if underlying == "NIFTY" else 50


def _build_chain(underlying: str, expiry: date, strikes: list[float]) -> CallChain:
    """Prefer real listed contracts (tradingsymbol + instrument_token) from
    the NFO master, restricted to the strikes the data source actually
    offers; fall back to synthetic rows when the master is unavailable."""
    try:
        real = CallChain.load(underlying, expiry)
        wanted = set(strikes)
        subset = [
            c for k in real.strikes if k in wanted
            for c in (real.contract_at(k),) if c is not None
        ]
        if len(subset) >= 3:
            return CallChain(underlying, expiry, subset)
    except Exception:  # noqa: BLE001
        pass
    return CallChain(underlying, expiry, _synthetic_contracts(underlying, expiry, strikes))


def _synthetic_contracts(underlying: str, expiry: date, strikes: list[float]):
    """Build minimal OptionContract rows from a bare strike list when the
    MarketData source hands us strikes but not full instrument rows (e.g. a
    historical source). The live path passes real rows via CallChain.load."""
    from app.options.instruments_nfo import OptionContract

    lot = _resolve_lot_size(underlying, expiry)
    ymd = expiry.strftime("%y%b").upper()
    return [
        OptionContract(
            instrument_token=f"SYN-{underlying}-{expiry.isoformat()}-{int(k)}CE",
            tradingsymbol=f"{underlying}{ymd}{int(k)}CE",
            name=underlying, expiry=expiry, strike=float(k), option_type="CE",
            lot_size=lot, tick_size=0.05,
        )
        for k in strikes
    ]
