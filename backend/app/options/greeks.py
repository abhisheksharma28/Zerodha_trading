"""Black-Scholes option pricing, greeks and implied volatility.

European options, continuous dividend yield, no early exercise — the
standard model for NSE index options analytics. This is the single source
of truth for the Adaptive Options engine. (Two older, simpler BS copies
live in ``market_data_service`` and ``strategies/options/market_data`` and
are intentionally left untouched so existing pages keep their exact
numbers; new code should import from here.)

Conventions:
  * ``vol`` is a fraction (0.14 = 14% annualised), NOT a percentage.
  * ``theta`` is per calendar day.
  * ``vega`` is per 1 percentage-point change in vol (i.e. per 0.01).
  * ``rho``  is per 1 percentage-point change in the rate.
  * ``delta`` for a put is negative.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

_SQRT_2PI = math.sqrt(2.0 * math.pi)
DEFAULT_RATE = 0.065


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / _SQRT_2PI


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float   # per calendar day
    vega: float    # per +0.01 vol
    rho: float     # per +0.01 rate

    def as_dict(self) -> dict[str, float]:
        return {
            "price": round(self.price, 4),
            "delta": round(self.delta, 5),
            "gamma": round(self.gamma, 7),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "rho": round(self.rho, 4),
        }


def _d1_d2(spot: float, strike: float, t: float, vol: float, r: float, q: float) -> tuple[float, float]:
    sig = max(vol, 1e-9)
    srt = sig * math.sqrt(t)
    d1 = (math.log(spot / strike) + (r - q + 0.5 * sig * sig) * t) / srt
    return d1, d1 - srt


def black_scholes(
    spot: float, strike: float, t_years: float, vol: float, *,
    is_call: bool, r: float = DEFAULT_RATE, q: float = 0.0,
) -> Greeks:
    """Price + full greeks. Degenerate inputs return intrinsic value with
    zeroed second-order greeks rather than raising."""
    if t_years <= 0 or spot <= 0 or strike <= 0 or vol <= 0:
        intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
        itm = (spot > strike) if is_call else (spot < strike)
        delta = (1.0 if is_call else -1.0) if itm else 0.0
        return Greeks(intrinsic, delta, 0.0, 0.0, 0.0, 0.0)

    d1, d2 = _d1_d2(spot, strike, t_years, vol, r, q)
    disc_r = math.exp(-r * t_years)
    disc_q = math.exp(-q * t_years)
    sqrt_t = math.sqrt(t_years)
    pdf = norm_pdf(d1)

    if is_call:
        nd1, nd2 = norm_cdf(d1), norm_cdf(d2)
        price = spot * disc_q * nd1 - strike * disc_r * nd2
        delta = disc_q * nd1
        theta_yr = (
            -spot * disc_q * pdf * vol / (2.0 * sqrt_t)
            - r * strike * disc_r * nd2
            + q * spot * disc_q * nd1
        )
        rho = strike * t_years * disc_r * nd2 / 100.0
    else:
        nnd1, nnd2 = norm_cdf(-d1), norm_cdf(-d2)
        price = strike * disc_r * nnd2 - spot * disc_q * nnd1
        delta = -disc_q * nnd1
        theta_yr = (
            -spot * disc_q * pdf * vol / (2.0 * sqrt_t)
            + r * strike * disc_r * nnd2
            - q * spot * disc_q * nnd1
        )
        rho = -strike * t_years * disc_r * nnd2 / 100.0

    gamma = disc_q * pdf / (spot * vol * sqrt_t)
    vega = spot * disc_q * pdf * sqrt_t / 100.0
    theta = theta_yr / 365.0
    return Greeks(price, delta, gamma, theta, vega, rho)


def bs_price(spot: float, strike: float, t_years: float, vol: float, *,
             is_call: bool, r: float = DEFAULT_RATE, q: float = 0.0) -> float:
    return black_scholes(spot, strike, t_years, vol, is_call=is_call, r=r, q=q).price


def implied_vol(
    price: float, spot: float, strike: float, t_years: float, *,
    is_call: bool, r: float = DEFAULT_RATE, q: float = 0.0,
    lo: float = 1e-4, hi: float = 5.0, tol: float = 1e-5, iters: int = 128,
) -> float | None:
    """Bisection IV solve. Returns a fraction, or ``None`` if the price is
    below intrinsic or outside the [lo, hi] vol bracket."""
    if price <= 0 or t_years <= 0 or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(0.0, (spot - strike) if is_call else (strike - spot))
    if price < intrinsic - 1e-6:
        return None

    f_lo = bs_price(spot, strike, t_years, lo, is_call=is_call, r=r, q=q) - price
    f_hi = bs_price(spot, strike, t_years, hi, is_call=is_call, r=r, q=q) - price
    if f_lo * f_hi > 0:
        return None
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        f_mid = bs_price(spot, strike, t_years, mid, is_call=is_call, r=r, q=q) - price
        if abs(f_mid) < tol:
            return mid
        if f_lo * f_mid < 0.0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)
