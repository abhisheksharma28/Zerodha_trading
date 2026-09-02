"""Canonical backtest configuration per strategy template.

Fixed so the leaderboard is a fair comparison: same universe, window,
capital and preset for every strategy, only the timeframe varies (each
strategy runs on the timeframe it is designed for). Change a value here and
the config hash changes, which invalidates that strategy's cached run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.market_data.nse_universe import NIFTY_50, NIFTY_100

_CAPITAL = 1_000_000.0
_NIFTY_50_SYMS = sorted(s for s, _n, _s in NIFTY_50)


@dataclass(frozen=True)
class CanonicalConfig:
    slug: str
    universe: list[str]
    universe_name: str
    timeframe: str
    preset: str
    years: float
    capital: float = _CAPITAL
    max_gross_exposure: float = 1.0
    note: str = ""

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "u": sorted(self.universe), "t": self.timeframe, "p": self.preset,
                "y": self.years, "c": self.capital, "x": self.max_gross_exposure,
            },
            sort_keys=True,
        )
        return hashlib.sha1(payload.encode()).hexdigest()[:12]  # noqa: S324 - not security

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "universe_name": self.universe_name,
            "universe_size": len(self.universe),
            "timeframe": self.timeframe,
            "preset": self.preset,
            "years": self.years,
            "capital": self.capital,
            "max_gross_exposure": self.max_gross_exposure,
            "config_hash": self.config_hash,
            "note": self.note,
        }


def _daily(slug: str) -> CanonicalConfig:
    return CanonicalConfig(
        slug=slug, universe=NIFTY_100, universe_name="NIFTY 100",
        timeframe="1d", preset="balanced", years=3.0, max_gross_exposure=1.0,
    )


def _intraday(slug: str) -> CanonicalConfig:
    return CanonicalConfig(
        slug=slug, universe=_NIFTY_50_SYMS, universe_name="NIFTY 50",
        timeframe="5m", preset="balanced", years=1.0, max_gross_exposure=4.0,
        note="Intraday: smaller universe / shorter window to keep the run bounded.",
    )


CANONICAL: dict[str, CanonicalConfig] = {
    "chinese-transformer": _daily("chinese-transformer"),
    "cross-sectional-momentum": _daily("cross-sectional-momentum"),
    "trend-following": _daily("trend-following"),
    "donchian-breakout": _daily("donchian-breakout"),
    "mean-reversion": _daily("mean-reversion"),
    "multi-factor": _daily("multi-factor"),
    "weapon-candle": _daily("weapon-candle"),
    "volatility-regime": _daily("volatility-regime"),
    "regime-adaptive": _daily("regime-adaptive"),
    "opening-range-breakout": _intraday("opening-range-breakout"),
    "opening-breakout-us": _intraday("opening-breakout-us"),
}

# Templates that need a bespoke instrument pair/basket and are not part of
# the standard single-universe suite.
UNSUITED: dict[str, str] = {
    "pairs-trading": "Needs a specific cointegrated pair, not a single universe.",
    "latency-arbitrage": "Needs a correlated lead/lag instrument pair.",
    "index-futures-arbitrage": "Needs an index future + its spot.",
}


def canonical_for(slug: str) -> CanonicalConfig | None:
    return CANONICAL.get(slug)
