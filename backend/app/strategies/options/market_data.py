"""MarketData implementations for the scheduled options strategies.

- KiteMarketData: live/paper. Spot from the NIFTY 50 index quote, strikes +
  quotes from the NFO instrument master + Kite ``get_quote``, basket margin
  from Kite's basket-margin endpoint.
- SyntheticOptionData: a Black-Scholes flat-vol pricer over a synthetic
  strike grid. Clearly labelled SYNTHETIC — for exercising the mechanics
  when real historical option data is unavailable. Never use it to judge
  whether the strategy "works".
- RecordedOptionData: replays a caller-supplied dict of historical option
  prices (the only faithful backtest path; needs an option-chain data
  vendor the platform does not currently integrate).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

from app.options.instruments_nfo import OptionContract, load_option_contracts
from app.strategies.options.base import LegQuote, OptionLeg

_IST_NIFTY_INDEX = "NSE:NIFTY 50"


# --------------------------------------------------------------------------
# live / paper
# --------------------------------------------------------------------------

class KiteMarketData:
    def __init__(self, kite_client: Any) -> None:
        self._kite = kite_client
        self._contracts: dict[str, list[OptionContract]] = {}

    def _all(self, underlying: str) -> list[OptionContract]:
        if underlying not in self._contracts:
            self._contracts[underlying] = load_option_contracts(underlying)
        return self._contracts[underlying]

    def spot(self, underlying: str, as_of: datetime) -> float | None:
        try:
            data = self._kite.get_quote([_IST_NIFTY_INDEX])
            q = data.get(_IST_NIFTY_INDEX) or next(iter(data.values()), None)
            return float(q["last_price"]) if q else None
        except Exception:  # noqa: BLE001
            return None

    def _contract(
        self, underlying: str, expiry: date, strike: float, option_type: str
    ) -> OptionContract | None:
        for c in self._all(underlying):
            if c.expiry == expiry and c.option_type == option_type and abs(c.strike - strike) < 1e-6:
                return c
        return None

    def call_strikes(self, underlying: str, expiry: date, as_of: datetime) -> list[float]:
        return sorted(
            c.strike for c in self._all(underlying)
            if c.expiry == expiry and c.option_type == "CE"
        )

    def option_quote(
        self, underlying: str, expiry: date, strike: float, option_type: str, as_of: datetime
    ) -> LegQuote | None:
        c = self._contract(underlying, expiry, strike, option_type)
        if c is None:
            return None
        key = f"NFO:{c.tradingsymbol}"
        try:
            data = self._kite.get_quote([key])
            q = data.get(key)
            if not q:
                return None
            depth = q.get("depth") or {}
            bid = float((depth.get("buy") or [{}])[0].get("price") or 0.0)
            ask = float((depth.get("sell") or [{}])[0].get("price") or 0.0)
            last = float(q.get("last_price") or 0.0)
            return LegQuote(bid=bid, ask=ask, last=last,
                            volume=float(q.get("volume") or 0.0),
                            oi=float(q.get("oi") or 0.0))
        except Exception:  # noqa: BLE001
            return None

    def basket_margin(self, legs: list[OptionLeg], as_of: datetime) -> float | None:
        """Broker basket margin = deployed capital.

        Kite's ``/margins/basket`` endpoint takes a JSON array body, which the
        current thin KiteClient (form-encoded only) cannot send. Until the
        client gains a JSON POST helper this returns None and the strategy
        uses its documented ``fallback_margin_per_short_lot`` estimate, with
        ``deployed_capital_source == "fallback"`` recorded on the basket.
        """
        return None


# --------------------------------------------------------------------------
# backtest — SYNTHETIC (not a faithful reproduction)
# --------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(spot: float, strike: float, t_years: float, vol: float, r: float = 0.065) -> float:
    if t_years <= 0 or spot <= 0 or strike <= 0:
        return max(0.0, spot - strike)
    sig = max(1e-6, vol)
    d1 = (math.log(spot / strike) + (r + sig * sig / 2) * t_years) / (sig * math.sqrt(t_years))
    d2 = d1 - sig * math.sqrt(t_years)
    return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)


class SyntheticOptionData:
    """SYNTHETIC. Flat-vol Black-Scholes over a fixed strike grid, spot from
    a supplied path. For mechanics testing only."""

    IS_SYNTHETIC = True

    def __init__(
        self,
        spot_path: dict[date, float],
        *,
        strike_step: float = 50.0,
        vol: float = 0.13,
        spread_frac: float = 0.02,
        margin: float | None = None,
    ) -> None:
        self._spot_path = spot_path
        self._strike_step = strike_step
        self._vol = vol
        self._spread_frac = spread_frac
        self._margin = margin

    def spot(self, underlying: str, as_of: datetime) -> float | None:
        return self._spot_path.get(as_of.date())

    def call_strikes(self, underlying: str, expiry: date, as_of: datetime) -> list[float]:
        s = self.spot(underlying, as_of) or 24000.0
        base = round(s / self._strike_step) * self._strike_step
        return [base + self._strike_step * (i - 60) for i in range(120)]

    def option_quote(
        self, underlying: str, expiry: date, strike: float, option_type: str, as_of: datetime
    ) -> LegQuote | None:
        s = self.spot(underlying, as_of)
        if s is None:
            return None
        t = max(1e-6, (expiry - as_of.date()).days / 365.0)
        mid = bs_call(s, strike, t, self._vol)
        half = max(0.05, mid * self._spread_frac)
        return LegQuote(bid=round(max(0.0, mid - half), 2), ask=round(mid + half, 2),
                        last=round(mid, 2), volume=100000, oi=500000)

    def basket_margin(self, legs: list[OptionLeg], as_of: datetime) -> float | None:
        return self._margin


class RecordedOptionData:
    """Replays real historical option prices supplied as
    ``{(iso_date, strike): {"bid":..,"ask":..,"last":..}}`` plus a spot
    path. This is the only faithful backtest source; populate it from an
    options-chain data vendor."""

    IS_SYNTHETIC = False

    def __init__(
        self,
        spot_path: dict[date, float],
        quotes: dict[tuple[str, float], dict[str, float]],
        *,
        margin_path: dict[date, float] | None = None,
    ) -> None:
        self._spot_path = spot_path
        self._quotes = quotes
        self._margin_path = margin_path or {}

    def spot(self, underlying: str, as_of: datetime) -> float | None:
        return self._spot_path.get(as_of.date())

    def call_strikes(self, underlying: str, expiry: date, as_of: datetime) -> list[float]:
        key = as_of.date().isoformat()
        return sorted({k[1] for k in self._quotes if k[0] == key})

    def option_quote(
        self, underlying: str, expiry: date, strike: float, option_type: str, as_of: datetime
    ) -> LegQuote | None:
        row = self._quotes.get((as_of.date().isoformat(), strike))
        if not row:
            return None
        return LegQuote(bid=float(row["bid"]), ask=float(row["ask"]),
                        last=float(row.get("last", (row["bid"] + row["ask"]) / 2)),
                        volume=float(row.get("volume", 0.0)), oi=float(row.get("oi", 0.0)))

    def basket_margin(self, legs: list[OptionLeg], as_of: datetime) -> float | None:
        return self._margin_path.get(as_of.date())
