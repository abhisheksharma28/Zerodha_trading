"""Phase 8 — Strategy library + multi-leg payoff engine.

Each template is a small declarative spec (which legs, at which named strike
levels) plus fit hints. A generic payoff engine turns a built position into
max profit / max loss / breakevens / probability-of-profit / net credit /
margin estimate / aggregate greeks — used identically by the selector, the
backtest and paper trading.

Strike *levels* are produced by the strike selector (Phase 10):
    atm, call_1 (short call), call_2 (call wing), put_1 (short put),
    put_2 (put wing), call_0 / put_0 (near-money body legs for ratios).

Naked (undefined-risk) templates are excluded unless
``AdaptiveConfig.allow_naked`` AND ``naked_risk_acknowledged`` are both set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.types import ChainSnapshot
from app.options.greeks import black_scholes

CATEGORIES = ("BULLISH", "BEARISH", "NEUTRAL", "VOL_EXPANSION", "VOL_CONTRACTION")


@dataclass(frozen=True)
class LegSpec:
    level: str          # atm | call_0 | call_1 | call_2 | put_0 | put_1 | put_2
    right: str          # CE | PE
    side: str           # BUY | SELL
    ratio: int = 1      # lot multiplier


@dataclass(frozen=True)
class StrategyTemplate:
    slug: str
    name: str
    category: str
    direction: str            # BULLISH | BEARISH | NEUTRAL
    defined_risk: bool
    naked: bool
    legs: tuple[LegSpec, ...]
    min_dte: int = 2
    max_dte: int = 60
    requires_far_expiry: bool = False
    fit_regimes: tuple[str, ...] = ()
    fit_pcr: tuple[str, ...] = ()
    fit_iv: tuple[str, ...] = ()
    thesis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "name": self.name, "category": self.category,
            "direction": self.direction, "defined_risk": self.defined_risk,
            "naked": self.naked, "n_legs": len(self.legs),
            "legs": [f"{lg.side} {lg.ratio}x {lg.right} @{lg.level}" for lg in self.legs],
            "min_dte": self.min_dte, "max_dte": self.max_dte,
            "requires_far_expiry": self.requires_far_expiry,
            "fit_regimes": list(self.fit_regimes), "fit_pcr": list(self.fit_pcr),
            "fit_iv": list(self.fit_iv), "thesis": self.thesis,
        }


@dataclass
class BuiltLeg:
    strike: float
    right: str
    side: str
    lots: int
    entry_price: float          # per-unit premium (mid)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def signed(self) -> int:
        return 1 if self.side == "BUY" else -1

    def as_dict(self) -> dict[str, Any]:
        return {
            "strike": self.strike, "right": self.right, "side": self.side, "lots": self.lots,
            "entry_price": round(self.entry_price, 2),
            "delta": round(self.delta, 4), "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 2), "vega": round(self.vega, 2),
        }


@dataclass
class BuiltPosition:
    slug: str
    legs: list[BuiltLeg]
    lot_size: int
    net_premium: float           # +credit / -debit, per lot-set (INR)
    max_profit: float
    max_loss: float              # positive number; inf-capped marker if undefined
    undefined_risk: bool
    breakevens: list[float]
    pop: float                   # 0-1
    margin_estimate: float
    greeks: dict[str, float]     # position-level
    notes: list[str] = field(default_factory=list)

    @property
    def risk_reward(self) -> float | None:
        if self.undefined_risk or self.max_loss <= 0:
            return None
        return self.max_profit / self.max_loss

    def as_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "legs": [lg.as_dict() for lg in self.legs],
            "lot_size": self.lot_size,
            "net_premium": round(self.net_premium, 2),
            "max_profit": round(self.max_profit, 2),
            "max_loss": None if self.undefined_risk else round(self.max_loss, 2),
            "undefined_risk": self.undefined_risk,
            "breakevens": [round(b, 1) for b in self.breakevens],
            "pop": round(self.pop, 3),
            "risk_reward": None if self.risk_reward is None else round(self.risk_reward, 2),
            "margin_estimate": round(self.margin_estimate, 0),
            "greeks": {k: round(v, 4) for k, v in self.greeks.items()},
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# the templates
# --------------------------------------------------------------------------

def _L(level: str, right: str, side: str, ratio: int = 1) -> LegSpec:
    return LegSpec(level, right, side, ratio)


TEMPLATES: tuple[StrategyTemplate, ...] = (
    StrategyTemplate(
        "long-call", "Long Call", "BULLISH", "BULLISH", True, False,
        (_L("atm", "CE", "BUY"),), 3, 45,
        fit_regimes=("STRONG_BULLISH_TREND", "BULLISH_TREND", "BREAKOUT"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Directional up; defined risk = premium paid; needs a real move to beat theta."),
    StrategyTemplate(
        "long-put", "Long Put", "BEARISH", "BEARISH", True, False,
        (_L("atm", "PE", "BUY"),), 3, 45,
        fit_regimes=("STRONG_BEARISH_TREND", "BEARISH_TREND", "BREAKDOWN"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Directional down; defined risk = premium paid."),
    StrategyTemplate(
        "bull-call-spread", "Bull Call Spread", "BULLISH", "BULLISH", True, False,
        (_L("atm", "CE", "BUY"), _L("call_1", "CE", "SELL")), 3, 45,
        fit_regimes=("BULLISH_TREND", "WEAK_BULLISH", "STRONG_BULLISH_TREND"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Debit spread; caps cost and reward; good when IV is not rich."),
    StrategyTemplate(
        "bear-put-spread", "Bear Put Spread", "BEARISH", "BEARISH", True, False,
        (_L("atm", "PE", "BUY"), _L("put_1", "PE", "SELL")), 3, 45,
        fit_regimes=("BEARISH_TREND", "WEAK_BEARISH", "STRONG_BEARISH_TREND"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Debit spread to the downside; capped."),
    StrategyTemplate(
        "bull-put-spread", "Bull Put Spread", "BULLISH", "BULLISH", True, False,
        (_L("put_1", "PE", "SELL"), _L("put_2", "PE", "BUY")), 3, 45,
        fit_regimes=("BULLISH_TREND", "WEAK_BULLISH", "STRONG_BULLISH_TREND", "RANGE_BOUND"),
        fit_pcr=("BULLISH", "STRONG_BULLISH", "NEUTRAL"),
        fit_iv=("NORMAL_IV", "HIGH_IV"),
        thesis="Credit spread below support; wins on time + a stable-to-up market."),
    StrategyTemplate(
        "bear-call-spread", "Bear Call Spread", "BEARISH", "BEARISH", True, False,
        (_L("call_1", "CE", "SELL"), _L("call_2", "CE", "BUY")), 3, 45,
        fit_regimes=("BEARISH_TREND", "WEAK_BEARISH", "STRONG_BEARISH_TREND", "RANGE_BOUND"),
        fit_pcr=("BEARISH", "STRONG_BEARISH", "NEUTRAL"),
        fit_iv=("NORMAL_IV", "HIGH_IV"),
        thesis="Credit spread above resistance; wins on time + a stable-to-down market."),
    StrategyTemplate(
        "iron-condor", "Iron Condor", "NEUTRAL", "NEUTRAL", True, False,
        (_L("put_1", "PE", "SELL"), _L("put_2", "PE", "BUY"),
         _L("call_1", "CE", "SELL"), _L("call_2", "CE", "BUY")), 4, 45,
        fit_regimes=("RANGE_BOUND", "NEUTRAL", "LOW_VOLATILITY"),
        fit_pcr=("NEUTRAL",), fit_iv=("HIGH_IV", "NORMAL_IV", "EXTREME_IV"),
        thesis="Both-side credit inside the expected move; wins on time + a quiet range."),
    StrategyTemplate(
        "iron-butterfly", "Iron Butterfly", "NEUTRAL", "NEUTRAL", True, False,
        (_L("atm", "PE", "SELL"), _L("put_1", "PE", "BUY"),
         _L("atm", "CE", "SELL"), _L("call_1", "CE", "BUY")), 4, 45,
        fit_regimes=("RANGE_BOUND", "LOW_VOLATILITY"),
        fit_pcr=("NEUTRAL",), fit_iv=("HIGH_IV", "EXTREME_IV"),
        thesis="Max credit at ATM; needs a tight pin; strong pinning / very high IV."),
    StrategyTemplate(
        "hedged-short-strangle", "Defined-Risk Short Strangle", "NEUTRAL", "NEUTRAL", True, False,
        (_L("put_1", "PE", "SELL"), _L("put_2", "PE", "BUY"),
         _L("call_1", "CE", "SELL"), _L("call_2", "CE", "BUY")), 4, 45,
        fit_regimes=("RANGE_BOUND", "NEUTRAL"),
        fit_iv=("HIGH_IV", "NORMAL_IV"),
        thesis="Wide iron condor — short strikes further out, wings far; higher POP, smaller credit."),
    StrategyTemplate(
        "long-straddle", "Long Straddle", "VOL_EXPANSION", "NEUTRAL", True, False,
        (_L("atm", "CE", "BUY"), _L("atm", "PE", "BUY")), 2, 30,
        fit_regimes=("LOW_VOLATILITY", "EVENT_RISK", "REVERSAL"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Buys a big move either way; loses to theta and IV crush if the market sits still."),
    StrategyTemplate(
        "long-strangle", "Long Strangle", "VOL_EXPANSION", "NEUTRAL", True, False,
        (_L("call_1", "CE", "BUY"), _L("put_1", "PE", "BUY")), 2, 30,
        fit_regimes=("LOW_VOLATILITY", "EVENT_RISK"),
        fit_iv=("LOW_IV",),
        thesis="Cheaper than a straddle; needs a larger move to pay."),
    StrategyTemplate(
        "call-ratio-spread", "Call Ratio Spread", "NEUTRAL", "BEARISH", True, False,
        (_L("call_0", "CE", "BUY"), _L("call_1", "CE", "SELL", 2)), 3, 45,
        fit_regimes=("WEAK_BEARISH", "RANGE_BOUND", "NEUTRAL"),
        fit_iv=("HIGH_IV", "NORMAL_IV"),
        thesis="Buy 1 near-money call, sell 2 further out; credit + upside cushion, risk if it rips."),
    StrategyTemplate(
        "put-ratio-backspread", "Put Ratio Backspread", "BEARISH", "BEARISH", True, False,
        (_L("put_0", "PE", "SELL"), _L("put_1", "PE", "BUY", 2)), 5, 45,
        fit_regimes=("WEAK_BEARISH", "BEARISH_TREND", "BREAKDOWN"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Sell 1 near put, buy 2 lower; small credit, big payoff on a hard drop."),
    StrategyTemplate(
        "calendar-call", "Call Calendar Spread", "NEUTRAL", "NEUTRAL", True, False,
        (_L("atm", "CE", "SELL"), _L("atm", "CE", "BUY")), 5, 45, requires_far_expiry=True,
        fit_regimes=("RANGE_BOUND", "LOW_VOLATILITY"),
        fit_iv=("LOW_IV", "NORMAL_IV"),
        thesis="Sell near, buy far at the same strike; profits from near-expiry theta + IV term."),
    StrategyTemplate(
        "short-strangle", "Short Strangle", "VOL_CONTRACTION", "NEUTRAL", False, True,
        (_L("put_1", "PE", "SELL"), _L("call_1", "CE", "SELL")), 3, 45,
        fit_regimes=("RANGE_BOUND", "NEUTRAL"),
        fit_iv=("HIGH_IV", "EXTREME_IV"),
        thesis="Naked both sides — undefined risk. Requires explicit acknowledgement."),
    StrategyTemplate(
        "short-straddle", "Short Straddle", "VOL_CONTRACTION", "NEUTRAL", False, True,
        (_L("atm", "PE", "SELL"), _L("atm", "CE", "SELL")), 3, 30,
        fit_regimes=("RANGE_BOUND", "LOW_VOLATILITY"),
        fit_iv=("EXTREME_IV",),
        thesis="Naked ATM both sides — maximum theta, maximum risk. Requires acknowledgement."),
)

_BY_SLUG = {t.slug: t for t in TEMPLATES}


def get_template(slug: str) -> StrategyTemplate:
    try:
        return _BY_SLUG[slug]
    except KeyError:
        raise KeyError(f"Unknown strategy template '{slug}'") from None


def available_templates(cfg: AdaptiveConfig, *, far_expiry_ok: bool = False) -> list[StrategyTemplate]:
    out = []
    for t in TEMPLATES:
        if t.naked and not (cfg.allow_naked and cfg.naked_risk_acknowledged):
            continue
        if t.requires_far_expiry and not far_expiry_ok:
            continue
        out.append(t)
    return out


# --------------------------------------------------------------------------
# build + payoff
# --------------------------------------------------------------------------

def _leg_quote(snap: ChainSnapshot, strike: float, right: str) -> tuple[float, float | None]:
    """(mid_price, iv) for the nearest listed strike to ``strike``."""
    row = min(snap.rows, key=lambda r: abs(r.strike - strike))
    ltp = row.call_ltp if right == "CE" else row.put_ltp
    iv = row.call_iv if right == "CE" else row.put_iv
    return (float(ltp) if ltp else 0.0, iv)


def build_position(
    template: StrategyTemplate,
    levels: dict[str, float],
    snap: ChainSnapshot,
    *,
    lots: int = 1,
    lot_size: int = 50,
    fallback_iv: float = 0.13,
) -> BuiltPosition:
    spot, t = snap.spot, snap.t_years
    legs: list[BuiltLeg] = []
    notes: list[str] = []
    for spec in template.legs:
        if spec.level not in levels:
            raise ValueError(f"{template.slug}: strike level '{spec.level}' not provided")
        k = min(snap.rows, key=lambda r: abs(r.strike - levels[spec.level])).strike
        mid, iv = _leg_quote(snap, k, spec.right)
        v = iv if (iv and iv > 0) else fallback_iv
        g = black_scholes(spot, k, t, v, is_call=(spec.right == "CE"))
        if mid <= 0:
            mid = g.price
            notes.append(f"No market price for {spec.right} {k:.0f}; used model price {mid:.2f}.")
        qty_lots = lots * spec.ratio
        legs.append(BuiltLeg(
            strike=k, right=spec.right, side=spec.side, lots=qty_lots, entry_price=mid,
            delta=g.delta * (1 if spec.side == "BUY" else -1) * qty_lots,
            gamma=g.gamma * (1 if spec.side == "BUY" else -1) * qty_lots,
            theta=g.theta * (1 if spec.side == "BUY" else -1) * qty_lots,
            vega=g.vega * (1 if spec.side == "BUY" else -1) * qty_lots,
        ))

    net_premium = -sum(lg.signed * lg.entry_price * lg.lots * lot_size for lg in legs)
    # payoff scan across a wide expiry-price grid
    lo = min(spot * 0.75, min(lg.strike for lg in legs) * 0.9)
    hi = max(spot * 1.25, max(lg.strike for lg in legs) * 1.1)
    grid = [lo + (hi - lo) * i / 400 for i in range(401)]
    pnl = [_payoff_at(legs, s, lot_size) + net_premium for s in grid]
    max_profit = max(pnl)
    max_loss_val = min(pnl)
    # undefined risk if payoff keeps falling at either boundary
    undefined = (pnl[0] < pnl[5] - 1 and pnl[0] <= max_loss_val + 1) or \
                (pnl[-1] < pnl[-6] - 1 and pnl[-1] <= max_loss_val + 1)
    max_loss = abs(min(0.0, max_loss_val))

    breakevens = _breakevens(grid, pnl)
    pop = _pop(snap, breakevens, net_premium > 0)
    greeks = {
        "delta": sum(lg.delta for lg in legs),
        "gamma": sum(lg.gamma for lg in legs),
        "theta": sum(lg.theta * lot_size for lg in legs),
        "vega": sum(lg.vega * lot_size for lg in legs),
    }
    margin = _margin_estimate(template, legs, spot, lot_size, net_premium)

    return BuiltPosition(
        slug=template.slug, legs=legs, lot_size=lot_size,
        net_premium=net_premium, max_profit=max_profit, max_loss=max_loss,
        undefined_risk=undefined or template.naked,
        breakevens=breakevens, pop=pop, margin_estimate=margin, greeks=greeks, notes=notes,
    )


def _payoff_at(legs: list[BuiltLeg], spot_exp: float, lot_size: int) -> float:
    tot = 0.0
    for lg in legs:
        intrinsic = max(0.0, (spot_exp - lg.strike) if lg.right == "CE" else (lg.strike - spot_exp))
        tot += lg.signed * intrinsic * lg.lots * lot_size
    return tot


def _breakevens(grid: list[float], pnl: list[float]) -> list[float]:
    out = []
    for i in range(1, len(pnl)):
        if (pnl[i - 1] <= 0 <= pnl[i]) or (pnl[i - 1] >= 0 >= pnl[i]):
            a, b = pnl[i - 1], pnl[i]
            f = 0.0 if b == a else (0 - a) / (b - a)
            out.append(grid[i - 1] + f * (grid[i] - grid[i - 1]))
    return out


def _pop(snap: ChainSnapshot, breakevens: list[float], is_credit: bool) -> float:
    """Rough probability of profit from a lognormal around spot using the
    ATM IV as sigma. Credit trades profit *between* the breakevens; debit
    trades profit *outside*."""
    from math import erf, log, sqrt
    atm = snap.atm_strike()
    row = next((r for r in snap.rows if r.strike == atm), None)
    iv = None
    if row:
        iv = row.call_iv or row.put_iv
    sig = (iv or 0.13) * sqrt(max(snap.t_years, 1e-6))
    spot = snap.spot
    if not breakevens or sig <= 0 or spot <= 0:
        return 0.5

    def cdf_price(p: float) -> float:
        z = (log(p / spot)) / sig
        return 0.5 * (1 + erf(z / sqrt(2)))

    bes = sorted(breakevens)
    if len(bes) == 1:
        pr = cdf_price(bes[0])
        return (1 - pr) if is_credit else pr    # crude for single-BE directional
    inside = cdf_price(bes[-1]) - cdf_price(bes[0])
    return inside if is_credit else (1 - inside)


def _margin_estimate(template: StrategyTemplate, legs: list[BuiltLeg], spot: float,
                     lot_size: int, net_premium: float) -> float:
    if template.defined_risk and not template.naked:
        # defined-risk margin ~ max loss of the structure
        widths = []
        calls = sorted((lg for lg in legs if lg.right == "CE"), key=lambda x: x.strike)
        puts = sorted((lg for lg in legs if lg.right == "PE"), key=lambda x: x.strike)
        for grp in (calls, puts):
            shorts = [lg for lg in grp if lg.side == "SELL"]
            longs = [lg for lg in grp if lg.side == "BUY"]
            if shorts and longs:
                widths.append(abs(shorts[0].strike - min(longs, key=lambda x: abs(x.strike - shorts[0].strike)).strike))
        w = max(widths) if widths else 0.0
        base_lots = max((lg.lots for lg in legs), default=1)
        return max(0.0, w * lot_size * base_lots - max(0.0, net_premium)) + 500.0
    # naked: SPAN+exposure rough — ~12% of notional per short lot
    short_notional = sum(lg.strike * lg.lots * lot_size for lg in legs if lg.side == "SELL")
    return short_notional * 0.12
