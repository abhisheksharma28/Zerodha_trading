"""Per-strategy test plans for the leaderboard.

Every strategy is backtested on the universe, timeframe and window it is
*designed for*, not one fixed basket. A ``TestPlan`` names a market screen
(see ``app.leaderboard.universe``) that picks the fitting names at run time
and records a plain-English rationale for the choice; the resolved list is
frozen to a sidecar so robustness / tuning reuse exactly the same names.

Changing a plan changes its ``config_hash``, which invalidates that
strategy's cached run. The hash covers the *plan* (screen + params + window
+ preset), not the day's screened list, so a re-screen that picks slightly
different names still lands in the same cache slot.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.market_data.nse_universe import NIFTY_50, NIFTY_200

_CAPITAL = 1_000_000.0
_NIFTY_50_SYMS = sorted(s for s, _n, _s in NIFTY_50)
_SIDECAR_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "leaderboard_universe"

_SCREEN_LABEL = {
    "mean_reverting": "Dynamic — mean-reverting names (screened)",
    "trend_persistent": "Dynamic — trend-persistent names (screened)",
    "broad_cross_section": "Dynamic — liquid cross-section (screened)",
    "high_volatility": "Dynamic — high-volatility names (screened)",
    "low_volatility": "Dynamic — low-volatility names (screened)",
    "sector_index_basket": "NSE sector indices",
    "index_proxy": "Broad index proxy",
    "cointegrated_pair": "Dynamic — most cointegrated pair (screened)",
    "liquid_base": "Dynamic — most liquid names (screened)",
}


@dataclass(frozen=True)
class TestPlan:
    slug: str
    screen: str
    screen_params: dict[str, Any] = field(default_factory=dict)
    timeframe: str = "1d"
    years: float = 5.0
    preset: str = "balanced"
    capital: float = _CAPITAL
    max_gross_exposure: float = 1.0
    design_note: str = ""
    pool_scope: str = "full"          # "full" = liquid equities + indices; "indices" = indices only


@dataclass(frozen=True)
class CanonicalConfig:
    slug: str
    universe: list[str]
    universe_name: str
    timeframe: str
    preset: str
    years: float
    screen: str = "liquid_base"
    screen_params: dict[str, Any] = field(default_factory=dict)
    design_note: str = ""
    universe_rationale: str = ""
    capital: float = _CAPITAL
    max_gross_exposure: float = 1.0

    @property
    def note(self) -> str:
        return self.design_note

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "screen": self.screen, "sp": self.screen_params, "t": self.timeframe,
                "p": self.preset, "y": self.years, "c": self.capital,
                "x": self.max_gross_exposure,
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
            "screen": self.screen,
            "screen_params": self.screen_params,
            "design_note": self.design_note,
            "universe_rationale": self.universe_rationale,
            "capital": self.capital,
            "max_gross_exposure": self.max_gross_exposure,
            "config_hash": self.config_hash,
            "note": self.design_note,
        }


# --------------------------------------------------------------------------
# frozen-universe sidecar (written by service.run_canonical after a screen)
# --------------------------------------------------------------------------

def _sidecar(slug: str) -> Path:
    return _SIDECAR_DIR / f"{slug}.json"


def load_frozen_universe(slug: str) -> dict[str, Any] | None:
    p = _sidecar(slug)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def save_frozen_universe(slug: str, payload: dict[str, Any]) -> None:
    _SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    _sidecar(slug).write_text(json.dumps(payload, indent=2))


# --------------------------------------------------------------------------
# the plans
# --------------------------------------------------------------------------

def _mr(slug: str) -> TestPlan:
    return TestPlan(slug, "mean_reverting", {"n": 40, "base_n": 150}, "1d", 5.0,
                    design_note="5-year daily window so the sample spans at least one "
                                "real drawdown, not just a bull run.")


def _trend(slug: str) -> TestPlan:
    return TestPlan(slug, "trend_persistent", {"n": 40, "base_n": 150}, "1d", 5.0,
                    design_note="Trend systems need a multi-year window with both a "
                                "sustained trend and a correction in it.")


def _xsec(slug: str) -> TestPlan:
    return TestPlan(slug, "broad_cross_section", {"n": 120}, "1d", 5.0,
                    design_note="Needs the whole liquid cross-section to rank within.")


def _intraday(slug: str) -> TestPlan:
    return TestPlan(slug, "high_volatility", {"n": 30, "base_n": 120, "vol_window": 90},
                    "5m", 1.0, max_gross_exposure=4.0,
                    design_note="Intraday: high-volatility names and a 1-year 5-minute "
                                "window to keep the data volume bounded.")


TEST_PLANS: dict[str, TestPlan] = {
    # mean reversion
    "mean-reversion": _mr("mean-reversion"),
    "zscore-regime-mr": _mr("zscore-regime-mr"),
    "rsi2-reversion": _mr("rsi2-reversion"),
    "bollinger-reversion": _mr("bollinger-reversion"),
    # trend / breakout
    "trend-following": _trend("trend-following"),
    "donchian-breakout": _trend("donchian-breakout"),
    "supertrend": _trend("supertrend"),
    "golden-cross": _trend("golden-cross"),
    "fiftytwo-week-high": _trend("fiftytwo-week-high"),
    "macd-grid": _trend("macd-grid"),
    "weapon-candle": _trend("weapon-candle"),
    "elder-force-index": _trend("elder-force-index"),
    "triple-screen": _trend("triple-screen"),
    # cross-sectional rank
    "cross-sectional-momentum": _xsec("cross-sectional-momentum"),
    "multi-factor": _xsec("multi-factor"),
    "dual-momentum": _xsec("dual-momentum"),
    "chinese-transformer": _xsec("chinese-transformer"),
    # regime switchers — give them the broad liquid set so they can see both regimes
    "volatility-regime": TestPlan("volatility-regime", "broad_cross_section", {"n": 60},
                                  "1d", 5.0,
                                  design_note="A regime switch should be judged on a mixed "
                                              "bag of names, not a pre-sorted one."),
    "regime-adaptive": TestPlan("regime-adaptive", "broad_cross_section", {"n": 60}, "1d", 5.0,
                                design_note="A regime switch should be judged on a mixed "
                                            "bag of names, not a pre-sorted one."),
    # new — dynamic-universe showcases
    "low-volatility-anomaly": TestPlan("low-volatility-anomaly", "low_volatility",
                                       {"n": 40, "base_n": 200, "vol_window": 120}, "1d", 5.0,
                                       design_note="The anomaly is defined by the screen: "
                                                   "buy the calmest decile, monthly."),
    "sector-momentum-rotation": TestPlan("sector-momentum-rotation", "sector_index_basket",
                                         {}, "1d", 5.0, pool_scope="indices",
                                         design_note="Trades sector indices so single-stock "
                                                     "noise does not drown the signal."),
    "seasonal-sector-rotation": TestPlan("seasonal-sector-rotation", "sector_index_basket",
                                         {}, "1d", 10.0, pool_scope="indices",
                                         design_note="Needs ~10 years of sector-index history to "
                                                     "build a reliable month-by-month table."),
    "volatility-contraction-breakout": TestPlan(
        "volatility-contraction-breakout", "consolidation_prone",
        {"n": 40, "base_n": 150, "window": 25, "tight_pct": 15.0}, "1d", 5.0,
        design_note="Only fires on names that actually build tight multi-week bases."),
    "pairs-trading": TestPlan("pairs-trading", "cointegrated_pair",
                              {"base_n": 30, "window": 252, "max_half_life": 60.0}, "1d", 3.0,
                              design_note="The tool picks the pair: the most stationary "
                                          "spread among the 30 most liquid names."),
    # new — classic retail systems
    "ttm-squeeze": TestPlan("ttm-squeeze", "trend_persistent", {"n": 40, "base_n": 150}, "1d", 5.0,
                            design_note="A squeeze marks potential energy; it only pays on names "
                                        "that then actually trend."),
    "turn-of-month": TestPlan("turn-of-month", "index_proxy", {"which": ("NIFTY 50",)}, "1d", 5.0,
                              design_note="A calendar effect measured at the index level, so it "
                                          "runs on the index as one instrument."),
    "rs-line-high": TestPlan("rs-line-high", "leaders_with_benchmark",
                             {"n": 60, "benchmark": "NIFTY 50"}, "1d", 5.0,
                             design_note="Relative strength needs the stock plus the index it is "
                                         "measured against, on every bar."),
    "vwap-reversion": TestPlan("vwap-reversion", "high_volatility",
                               {"n": 30, "base_n": 120, "vol_window": 90}, "5m", 1.0,
                               max_gross_exposure=4.0,
                               design_note="Intraday fade needs range: high-volatility names, "
                                           "1-year 5-minute window."),
    # intraday
    "opening-range-breakout": _intraday("opening-range-breakout"),
}


def _default_universe(plan: TestPlan) -> tuple[list[str], str]:
    if plan.timeframe == "1d":
        return list(NIFTY_200), "NIFTY 200 (default, not yet screened)"
    return list(_NIFTY_50_SYMS), "NIFTY 50 (default, not yet screened)"


def canonical_for(slug: str) -> CanonicalConfig | None:
    plan = TEST_PLANS.get(slug)
    if plan is None:
        return None
    frozen = load_frozen_universe(slug)
    if frozen and frozen.get("config_hash") == _plan_hash(plan) and frozen.get("symbols"):
        universe = list(frozen["symbols"])
        uni_name = _SCREEN_LABEL.get(plan.screen, plan.screen)
        rationale = frozen.get("rationale", "")
    else:
        universe, uni_name = _default_universe(plan)
        rationale = ""
    return CanonicalConfig(
        slug=slug, universe=universe, universe_name=uni_name,
        timeframe=plan.timeframe, preset=plan.preset, years=plan.years,
        screen=plan.screen, screen_params=plan.screen_params,
        design_note=plan.design_note, universe_rationale=rationale,
        capital=plan.capital, max_gross_exposure=plan.max_gross_exposure,
    )


def _plan_hash(plan: TestPlan) -> str:
    payload = json.dumps(
        {
            "screen": plan.screen, "sp": plan.screen_params, "t": plan.timeframe,
            "p": plan.preset, "y": plan.years, "c": plan.capital,
            "x": plan.max_gross_exposure,
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:12]  # noqa: S324 - not security


CANONICAL: dict[str, CanonicalConfig] = {
    slug: cfg for slug in TEST_PLANS if (cfg := canonical_for(slug)) is not None
}

# Templates outside the screen suite.
UNSUITED: dict[str, str] = {
    "latency-arbitrage": "Needs a correlated lead/lag instrument pair.",
    "index-futures-arbitrage": "Needs an index future + its spot.",
    "opening-breakout-us": (
        "Models US-market-open microstructure (RVOL 'stocks in play', session mechanics); "
        "not comparable on the NSE screen suite. Use opening-range-breakout for NSE."
    ),
}
