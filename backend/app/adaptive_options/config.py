"""AdaptiveConfig — every tunable threshold and weight in one validated place.

Nothing trading-relevant is hard-coded in the engines; they all read from
here. Three beginner presets plus arbitrary field overrides. A resolved
config is persisted with each analysis / backtest / paper run so a result
is always reproducible.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass
class AdaptiveConfig:
    # --- identity -----------------------------------------------------
    risk_profile: str = "balanced"           # conservative | balanced | aggressive
    analysis_profile: str = "full"           # full | oi_levels_pcr  (baseline: OI + levels + PCR only)
    allow_naked: bool = False                # unlimited-risk selling stays off unless set
    naked_risk_acknowledged: bool = False

    # --- PCR engine -------------------------------------------------
    pcr_bull_threshold: float = 1.10
    pcr_bear_threshold: float = 0.85
    pcr_strong_bull: float = 1.30
    pcr_strong_bear: float = 0.65
    pcr_extreme_bull: float = 1.60
    pcr_extreme_bear: float = 0.50
    pcr_near_atm_strikes: int = 5
    pcr_weighted_halflife_strikes: float = 4.0     # OI weight halves every N strikes from ATM
    pcr_transition_lookback: int = 6              # snapshots
    pcr_transition_min_slope: float = 0.015       # per-snapshot slope to call a transition
    pcr_transition_confirm: int = 3              # consecutive same-direction snapshots

    # --- volatility engine ---------------------------------------
    iv_low_rank: float = 25.0
    iv_high_rank: float = 65.0
    iv_extreme_rank: float = 85.0
    rv_lookback_days: int = 20
    vol_selling_favourable_min: float = 55.0
    vol_selling_unfavourable_max: float = 40.0

    # --- market intelligence / indicators ----------------------
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    adx_period: int = 14
    atr_period: int = 14
    adx_trend_min: float = 22.0
    adx_strong_min: float = 35.0
    structure_lookback: int = 20
    vwap_band_pct: float = 0.15
    rel_volume_lookback: int = 20

    # --- regime engine ------------------------------------------
    regime_confidence_min: float = 50.0          # below this the engine leans NO_TRADE
    regime_high_vol_iv_rank: float = 70.0
    regime_low_vol_iv_rank: float = 25.0
    regime_price_group_weight: float = 1.0       # scales the trend/EMA/VWAP price group in the
    #                                             directional score; the OI+PCR baseline drops it low

    # --- confidence weights (need not sum to 1; normalised internally)
    w_trend: float = 0.20
    w_positioning: float = 0.20
    w_pcr: float = 0.15
    w_price_action: float = 0.15
    w_volatility: float = 0.10
    w_volume: float = 0.10
    w_futures: float = 0.05
    w_liquidity: float = 0.05

    # --- expected move ----------------------------------------
    expected_move_band_sd: float = 1.0

    # --- strike selection -------------------------------------
    strike_method: str = "delta"                 # delta | expected_move | oi_wall | support_resistance | premium
    strike_short_delta: float = 0.20             # target |delta| for short legs
    strike_wing_delta: float = 0.08              # target |delta| for protective wings
    strike_wing_width_pts: float = 300.0         # wing = short strike +/- this many points; 0 = use wing_delta
    strike_em_mult: float = 1.0                  # short strike at spot +/- this * expected move
    strike_min_leg_oi: float = 0.0               # skip a candidate strike with less OI than this
    strike_target_premium: float = 0.0           # premium method: target per-unit premium for the short leg

    # --- strategy selection ---------------------------------
    suitability_min: float = 45.0                # below this a strategy is 'avoid'
    no_trade_confidence_min: float = 45.0        # engine-level confidence floor for any entry
    w_regime_match: float = 0.25
    w_positioning_match: float = 0.20
    w_volatility_match: float = 0.15
    w_pcr_confirm: float = 0.10
    w_price_action_confirm: float = 0.10
    w_risk_reward: float = 0.10
    w_liquidity_match: float = 0.05
    w_dte_match: float = 0.05

    # --- sizing + risk ------------------------------------
    account_capital: float = 1_000_000.0
    max_loss_per_trade_pct: float = 3.0          # % of account_capital risked on one structure
    max_capital_allocation_pct: float = 60.0
    max_margin_usage_pct: float = 50.0
    max_lots_per_trade: int = 20
    max_portfolio_delta_pct: float = 0.5         # |delta| * spot as % of capital
    max_daily_loss_pct: float = 3.0
    max_trades_per_day: int = 4
    max_adjustments_per_day: int = 6
    expiry_reduce_dte: int = 2                   # from this DTE, halve size + require hedges

    # --- data quality ---------------------------------------
    dq_min_strikes: int = 8
    dq_max_missing_iv_pct: float = 35.0
    dq_max_missing_oi_pct: float = 20.0
    dq_stale_seconds: float = 240.0
    dq_max_zero_oi_pct: float = 60.0

    # --------------------------------------------------------------

    @classmethod
    def field_names(cls) -> set[str]:
        return {f.name for f in fields(cls)}

    @classmethod
    def from_dict(
        cls, data: dict[str, Any] | None, *,
        preset: str | None = None, profile: str | None = None,
    ) -> AdaptiveConfig:
        base: dict[str, Any] = {}
        if preset:
            if preset not in PRESETS:
                raise ValueError(f"Unknown preset '{preset}' — {sorted(PRESETS)}")
            base.update(PRESETS[preset])
            base["risk_profile"] = preset
        eff_profile = profile or (data or {}).get("analysis_profile")
        if eff_profile and eff_profile != "full":
            if eff_profile not in ANALYSIS_PROFILES:
                raise ValueError(f"Unknown analysis_profile '{eff_profile}' — {sorted(ANALYSIS_PROFILES)}")
            base.update(ANALYSIS_PROFILES[eff_profile])
            base["analysis_profile"] = eff_profile
        known = cls.field_names()
        for k, v in (data or {}).items():
            if k not in known:
                raise ValueError(f"Unknown AdaptiveConfig field: {k!r}")
            base[k] = v
        cfg = cls(**base)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not (self.pcr_extreme_bear < self.pcr_strong_bear < self.pcr_bear_threshold
                < self.pcr_bull_threshold < self.pcr_strong_bull < self.pcr_extreme_bull):
            raise ValueError("PCR thresholds must be strictly increasing "
                             "(extreme_bear < strong_bear < bear < bull < strong_bull < extreme_bull).")
        if not (0 < self.iv_low_rank < self.iv_high_rank < self.iv_extreme_rank <= 100):
            raise ValueError("IV-rank thresholds must satisfy 0 < low < high < extreme <= 100.")
        for f in ("w_trend", "w_positioning", "w_pcr", "w_price_action",
                  "w_volatility", "w_volume", "w_futures", "w_liquidity"):
            if getattr(self, f) < 0:
                raise ValueError(f"{f} must be >= 0.")
        if self.regime_price_group_weight < 0:
            raise ValueError("regime_price_group_weight must be >= 0.")
        if (sum((self.w_positioning, self.w_pcr, self.w_price_action, self.w_trend,
                 self.w_volatility, self.w_volume, self.w_futures, self.w_liquidity)) <= 0):
            raise ValueError("at least one confidence weight must be > 0.")

    def confidence_weights(self) -> dict[str, float]:
        raw = {
            "trend": self.w_trend, "positioning": self.w_positioning, "pcr": self.w_pcr,
            "price_action": self.w_price_action, "volatility": self.w_volatility,
            "volume": self.w_volume, "futures": self.w_futures, "liquidity": self.w_liquidity,
        }
        tot = sum(raw.values()) or 1.0
        return {k: v / tot for k, v in raw.items()}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Analysis profiles change *which signals* drive the decision (orthogonal to the
# risk presets, which change thresholds). ``oi_levels_pcr`` is the clean
# baseline demanded by the OI+Levels+PCR research brief: only Open Interest
# positioning, OI-derived / price levels, and PCR feed confidence, the regime
# and strategy suitability. Trend/EMA/VWAP/RSI, IV/volatility and raw volume
# are switched off (weight 0) so they can be re-added one at a time and
# measured against this baseline.
ANALYSIS_PROFILES: dict[str, dict[str, Any]] = {
    "oi_levels_pcr": {
        # confidence: positioning (OI) + PCR + a little liquidity only
        "w_trend": 0.0, "w_positioning": 0.55, "w_pcr": 0.35, "w_price_action": 0.0,
        "w_volatility": 0.0, "w_volume": 0.0, "w_futures": 0.0, "w_liquidity": 0.10,
        # regime: let OI + PCR carry it; keep only a light touch of price structure
        "regime_price_group_weight": 0.30,
        # strategy suitability: regime + OI positioning + PCR + R:R + liquidity
        "w_regime_match": 0.28, "w_positioning_match": 0.34, "w_volatility_match": 0.0,
        "w_pcr_confirm": 0.22, "w_price_action_confirm": 0.0, "w_risk_reward": 0.11,
        "w_liquidity_match": 0.05, "w_dte_match": 0.0,
    },
}


PRESETS: dict[str, dict[str, Any]] = {
    "conservative": {
        "pcr_bull_threshold": 1.15, "pcr_bear_threshold": 0.80,
        "pcr_transition_confirm": 4, "pcr_transition_min_slope": 0.020,
        "iv_high_rank": 60.0, "vol_selling_favourable_min": 62.0,
        "adx_trend_min": 25.0, "regime_confidence_min": 60.0,
        "allow_naked": False,
    },
    "balanced": {},   # dataclass defaults
    "aggressive": {
        "pcr_bull_threshold": 1.05, "pcr_bear_threshold": 0.92,
        "pcr_transition_confirm": 2, "pcr_transition_min_slope": 0.010,
        "iv_high_rank": 55.0, "vol_selling_favourable_min": 48.0,
        "adx_trend_min": 18.0, "regime_confidence_min": 42.0,
    },
}
