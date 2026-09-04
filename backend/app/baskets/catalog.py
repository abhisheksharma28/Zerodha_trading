"""The 12 flagship investment products — the only baskets the catalog
shows users.

Philosophy: internally the platform can run many strategies, factors and
models; externally there are exactly twelve understandable products. The
other ~14 template specs stay in ``templates.py`` as internal models
(served only with ``?include_internal=true``), not deleted.

Each product carries the quant ``spec`` (validates against
``app.baskets.spec``) plus the presentation metadata a professional
product surface needs: a plain-English objective, a 1-5 risk level, a
recommended horizon, an investment style, the goal-journeys it belongs to,
a "how it works" list and the differentiators that make it distinct from
its siblings.

Fundamentals note: the quality / growth / value factors are computed from
*latest* fundamentals only and feed the live/paper rebalance signal. In a
historical backtest they are renormalised away and the ranking runs on the
price-based factors (momentum / trend / low-vol). This is stated in each
product's "how it works".
"""

from __future__ import annotations

from typing import Any

from app.baskets import universes as U

# --- new user-facing taxonomy -----------------------------------------------

CATEGORIES = [
    "Core",
    "Smart Alpha",
    "Growth",
    "Defensive & Quality",
    "Thematic & Sector",
    "Income",
    "Multi-Asset",
]

RISK_LABELS = {
    1: "Conservative",
    2: "Moderate",
    3: "Balanced Growth",
    4: "Aggressive",
    5: "Very Aggressive",
}

# goal-based marketplace grouping
JOURNEYS: dict[str, list[str]] = {
    "I'm new to investing": ["core-growth", "all-weather-wealth", "golden-wealth"],
    "I want higher growth": ["momentum-leaders", "adaptive-alpha", "growth-accelerators"],
    "I believe in India's growth story": [
        "india-consumption-growth", "smallmid-smart-alpha", "dynamic-sector-rotation",
    ],
    "I want stability or income": [
        "quality-compounders", "defensive-leaders", "dividend-income",
    ],
}

# --- spec helpers ---------------------------------------------------------

_NONE = {"type": "none"}
_REGIME = {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.5}
# hard_cut: high-beta baskets drop straight to the floor in any non-bull
# regime rather than riding pullbacks down at partial weight
_REGIME_TIGHT = {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.4, "hard_cut": True}


def _mom(lookback: int, top_k: int, *, trend_ma: int = 200, hold_k: int = 0,
         min_roc_pct: float = 0.0) -> dict[str, Any]:
    return {
        "type": "momentum_top_k", "lookback": lookback, "top_k": top_k,
        "trend_ma": trend_ma, "hold_k": hold_k, "min_roc_pct": min_roc_pct,
    }


def _composite(lookback: int, top_k: int, factor_weights: dict[str, float], *,
               hold_k: int = 0, trend_ma: int = 200,
               min_roc_pct: float = 0.0) -> dict[str, Any]:
    return {
        "type": "composite_score", "lookback": lookback, "top_k": top_k, "hold_k": hold_k,
        "trend_ma": trend_ma, "min_roc_pct": min_roc_pct, "factor_weights": factor_weights,
    }


# blended factor profiles. Price factors (momentum / trend / low_vol / rs /
# volume) apply in a backtest; quality / growth / value are added on the
# live signal only. rs (relative strength vs the benchmark) needs the
# benchmark bar series — supplied on both the backtest and live paths.
FW_QUALITY_MOMENTUM = {"momentum": 0.30, "trend": 0.15, "rs": 0.10,
                       "quality": 0.35, "growth": 0.10}
# momentum stays clearly primary; rs / volume confirm rather than dilute it
# (they add signal across regimes and once fundamentals are live, but are
# collinear with 6m momentum in a price-only backtest)
FW_MOMENTUM = {"momentum": 0.50, "trend": 0.20, "rs": 0.10, "low_vol": 0.10, "quality": 0.10}
FW_ADAPTIVE = {"momentum": 0.35, "trend": 0.15, "rs": 0.10, "low_vol": 0.10,
               "volume": 0.05, "quality": 0.15, "value": 0.10}
FW_GROWTH = {"momentum": 0.35, "trend": 0.20, "rs": 0.10, "growth": 0.25, "quality": 0.10}
FW_QUALITY = {"low_vol": 0.20, "trend": 0.15, "quality": 0.45, "growth": 0.10, "value": 0.10}
FW_DEFENSIVE = {"low_vol": 0.50, "trend": 0.15, "quality": 0.30, "value": 0.05}
FW_CONSUMPTION = {"momentum": 0.30, "trend": 0.15, "rs": 0.10, "growth": 0.30,
                  "quality": 0.10, "value": 0.05}
FW_SECTOR = {"momentum": 0.40, "trend": 0.25, "rs": 0.20, "volume": 0.15}


def _p(**kw: Any) -> dict[str, Any]:
    """Build a flagship product record with sane defaults."""
    kw.setdefault("investor_profile", "Moderate to Aggressive")
    kw.setdefault("investment_style", "Rules-based")
    kw.setdefault("differentiators", [])
    kw.setdefault("how_it_works", [])
    return kw


CATALOG: list[dict[str, Any]] = [
    # ============================================================ CORE
    _p(
        key="core-growth",
        name="Core Growth",
        category="Core",
        risk_level=3,
        objective=(
            "Long-term wealth creation through high-quality Indian companies, "
            "combined with market momentum and a diversifying gold sleeve."
        ),
        investor_profile="Moderate to Aggressive",
        horizon="5+ years",
        investment_style="Multi-factor core + gold",
        holdings="20-30 stocks + gold",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 50",
        differentiators=[
            "Blends a quality sleeve and a momentum sleeve rather than picking one style",
            "Fixed strategic weights with dynamic stock selection inside each equity sleeve",
            "10% gold + 5% liquid to soften equity drawdowns",
        ],
        how_it_works=[
            "35% quality leaders, 25% momentum leaders, 25% large-cap core, 10% gold, 5% liquid.",
            "Each quarter the quality and momentum sleeves re-rank the large-cap universe and hold the strongest names.",
            "Quality/growth signals come from latest fundamentals on the live book; the backtest uses price factors only.",
            "A regime gate trims the equity sleeves when the Nifty is below its 200-day average.",
        ],
        spec={
            "sleeves": [
                {"id": "quality", "name": "Quality Leaders", "weight_pct": 35.0,
                 "weighting": "score_weighted", "members": U.QUALITY, "max_weight_pct": 8.0,
                 "rule": _composite(126, 12, FW_QUALITY, hold_k=16, trend_ma=0)},
                {"id": "momentum", "name": "Momentum Leaders", "weight_pct": 25.0,
                 "weighting": "score_weighted", "members": U.LARGE_CAP_CORE, "max_weight_pct": 8.0,
                 "rule": _composite(126, 10, FW_MOMENTUM, hold_k=14, trend_ma=200)},
                {"id": "core", "name": "Large-Cap Core", "weight_pct": 25.0,
                 "weighting": "equal", "members": ["NIFTYBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "gold", "name": "Gold", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 5.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    _p(
        key="all-weather-wealth",
        name="All Weather Wealth",
        category="Multi-Asset",
        risk_level=2,
        objective=(
            "Long-term growth with real diversification across equity, precious "
            "metals and liquidity, so no single environment sinks the portfolio."
        ),
        investor_profile="Conservative to Moderate",
        horizon="5+ years",
        investment_style="Strategic multi-asset",
        holdings="Equity sleeves + gold + silver + liquid",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 50",
        differentiators=[
            "55% equity / 25% gold / 10% silver / 10% liquid strategic mix",
            "Equity split 60% large-cap core, 25% quality-momentum, 15% midcap",
            "Metals sleeves are sized to cushion equity drawdowns, not chase returns",
        ],
        how_it_works=[
            "Strategic weights: 33% large-cap core, 14% quality & momentum stocks, 8% midcap, 25% gold, 10% silver, 10% liquid.",
            "The stock sleeves re-rank their universes each quarter; the ETF and metals sleeves just rebalance to weight.",
            "Rebalanced quarterly or when a sleeve drifts past its band.",
        ],
        spec={
            "sleeves": [
                {"id": "core", "name": "Large-Cap Core", "weight_pct": 33.0,
                 "weighting": "equal", "members": ["NIFTYBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "qm", "name": "Quality & Momentum", "weight_pct": 14.0,
                 "weighting": "score_weighted", "members": U.LARGE_MID_ALPHA, "max_weight_pct": 3.0,
                 "rule": _composite(126, 12, FW_QUALITY_MOMENTUM, hold_k=16, trend_ma=200)},
                {"id": "mid", "name": "Midcap", "weight_pct": 8.0,
                 "weighting": "score_weighted", "members": U.MIDCAP_LIQUID, "max_weight_pct": 2.0,
                 "rule": _composite(126, 10, FW_QUALITY_MOMENTUM, hold_k=14, trend_ma=200)},
                {"id": "gold", "name": "Gold", "weight_pct": 25.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "silver", "name": "Silver", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["SILVERBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    # ====================================================== SMART ALPHA
    _p(
        key="momentum-leaders",
        name="Momentum Leaders",
        category="Smart Alpha",
        risk_level=4,
        objective=(
            "Hold India's strongest market leaders, identified by multi-horizon "
            "price momentum with a trend confirmation filter."
        ),
        investor_profile="Aggressive",
        horizon="3-5 years",
        investment_style="Price momentum",
        holdings="10-15 stocks",
        rebalance_frequency="monthly",
        benchmark="NIFTY 50",
        differentiators=[
            "Pure market-leadership signal — what is working now, not what is cheap or growing",
            "Monthly rotation with a hold buffer to curb churn",
            "Trend filter keeps it out of names below their 200-day average",
        ],
        how_it_works=[
            "Ranks a large + liquid-mid universe by a multi-horizon momentum composite (12-1 month, 6 month and 3 month returns) plus a multi-MA trend check, with a low-vol and quality tilt on the live signal.",
            "Holds the top 12, score-weighted, single-name cap 12%.",
            "A held name is only dropped once it falls past rank 16 (hysteresis).",
            "Regime gate: equity is trimmed when the Nifty is below its 200-day average.",
        ],
        spec={
            "sleeves": [
                {"id": "mom", "name": "Momentum", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": U.LARGE_MID_ALPHA, "max_weight_pct": 12.0,
                 "rule": _composite(126, 12, FW_MOMENTUM, hold_k=16, trend_ma=200)},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    _p(
        key="adaptive-alpha",
        name="Adaptive Alpha",
        category="Smart Alpha",
        risk_level=5,
        objective=(
            "A dynamic multi-factor engine that ranks the broad market on "
            "momentum, growth, quality, participation and value, and adapts "
            "which factors matter as the market regime changes."
        ),
        investor_profile="Very Aggressive",
        horizon="3-5 years",
        investment_style="Adaptive multi-factor",
        holdings="12-15 stocks",
        rebalance_frequency="monthly",
        benchmark="NIFTY 500",
        differentiators=[
            "Factor weights shift with the regime — momentum in strong bulls, quality and low-vol in volatile tape",
            "Broadest universe of the alpha products (large + liquid mid)",
            "Distinct from Momentum Leaders (one factor) and Growth Accelerators (business growth)",
        ],
        how_it_works=[
            "Scores the universe on a blended factor model — multi-horizon momentum, relative strength vs NIFTY 500, multi-MA trend, volume participation, low volatility, plus quality and value on the live signal.",
            "Holds the top 12, score-weighted, single-name cap 10%, monthly.",
            "Regime-adaptive factor weighting (emphasise momentum in strong bulls, quality / low-vol in volatile tape) lands with the shared regime engine in Phase 3.",
            "Regime gate halves equity exposure when the Nifty is below its 200-day average.",
        ],
        spec={
            "sleeves": [
                {"id": "alpha", "name": "Adaptive Alpha", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": U.LARGE_MID_ALPHA, "max_weight_pct": 10.0,
                 "rule": _composite(126, 12, FW_ADAPTIVE, hold_k=16, trend_ma=200)},
            ],
            "risk": {"max_position_pct": 12.0, "regime": _REGIME},
        },
    ),
    # =========================================================== GROWTH
    _p(
        key="growth-accelerators",
        name="Growth Accelerators",
        category="Growth",
        risk_level=4,
        objective=(
            "Own companies whose business is accelerating — rising revenue and "
            "earnings growth, improving margins, confirmed by price."
        ),
        investor_profile="Aggressive",
        horizon="3-5 years",
        investment_style="Business growth",
        holdings="12-15 stocks",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 500",
        differentiators=[
            "Selects on earnings and revenue acceleration, not just price strength",
            "Quarterly rebalance unless a holding materially deteriorates — lower turnover than Momentum Leaders",
            "Momentum = market leadership; this = the underlying business inflecting",
        ],
        how_it_works=[
            "Ranks a large + mid universe on a growth composite (fundamental growth on the live signal; 3- and 6-month price acceleration as the backtest proxy).",
            "Holds the top 12, score-weighted, single-name cap 14%, rebalanced quarterly.",
            "Trend filter keeps it in names above their 200-day average.",
        ],
        spec={
            "sleeves": [
                {"id": "growth", "name": "Growth", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": U.LARGE_MID_ALPHA, "max_weight_pct": 14.0,
                 "rule": _composite(63, 12, FW_GROWTH, hold_k=16, trend_ma=200)},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    _p(
        key="smallmid-smart-alpha",
        name="Small & Midcap Smart Alpha",
        category="Growth",
        risk_level=5,
        objective=(
            "Capture high-growth opportunities beyond large caps, with strict "
            "liquidity and drawdown controls."
        ),
        investor_profile="Very Aggressive",
        horizon="5+ years",
        investment_style="Midcap multi-factor",
        holdings="~15 stocks",
        rebalance_frequency="monthly",
        benchmark="NIFTY MIDCAP 150",
        differentiators=[
            "Midcap universe with a strict 8% single-name cap and an 18-name hold buffer",
            "Mandatory regime filter cuts equity to ~40% in a risk-off tape",
            "10% liquid sleeve as a permanent shock absorber",
        ],
        how_it_works=[
            "Ranks a 25-name liquid midcap universe on a momentum + quality composite.",
            "Holds the top 15 at 90% weight, score-weighted, cap 8%; 10% liquid.",
            "Regime gate (risk-off scale 0.4) plus a global 9% position cap.",
            "Monthly rebalance with a wide hold buffer to limit turnover.",
        ],
        spec={
            "sleeves": [
                {"id": "mid", "name": "Midcap Alpha", "weight_pct": 90.0,
                 "weighting": "score_weighted", "members": U.MIDCAP_LIQUID, "max_weight_pct": 8.0,
                 "rule": _composite(126, 15, FW_QUALITY_MOMENTUM, hold_k=18, trend_ma=200)},
                {"id": "cash", "name": "Liquid / Defensive", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"max_position_pct": 9.0, "regime": _REGIME_TIGHT},
        },
    ),
    # ============================================== DEFENSIVE & QUALITY
    _p(
        key="quality-compounders",
        name="Quality Compounders",
        category="Defensive & Quality",
        risk_level=3,
        objective=(
            "Own exceptional Indian businesses — high return on capital, low "
            "leverage, stable earnings — and let them compound."
        ),
        investor_profile="Moderate",
        horizon="5+ years",
        investment_style="Quality, low turnover",
        holdings="~15 stocks",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 100",
        differentiators=[
            "Quality-first ranking (ROCE, earnings stability, margins) — not a price screen",
            "Quarterly, wide hold buffer: designed for low turnover and long compounding",
            "No regime gate — this sleeve is meant to be held through the cycle",
        ],
        how_it_works=[
            "Ranks a 20-name quality universe on a quality composite (fundamental quality on the live signal; low-vol + trend proxy in the backtest).",
            "Holds the top 15, score-weighted, rebalanced quarterly with a 20-name hold buffer.",
            "Turnover is deliberately low; positions change only on real deterioration.",
        ],
        spec={
            "sleeves": [
                {"id": "quality", "name": "Quality", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": U.QUALITY, "max_weight_pct": 10.0,
                 "rule": _composite(126, 15, FW_QUALITY, hold_k=20, trend_ma=0)},
            ],
        },
    ),
    _p(
        key="defensive-leaders",
        name="Defensive Leaders",
        category="Defensive & Quality",
        risk_level=2,
        objective=(
            "Reduce volatility and protect capital in uncertain markets, while "
            "staying invested in stable, cash-generative businesses."
        ),
        investor_profile="Conservative to Moderate",
        horizon="3+ years",
        investment_style="Low volatility + quality",
        holdings="Low-vol + quality sleeves + gold + liquid",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 50",
        differentiators=[
            "50% low-volatility / 30% quality / 10% gold / 10% liquid — capital protection first",
            "Inverse-volatility weighting so the calmest names carry the most weight",
            "De-duplicated universes: every holding is a unique security",
        ],
        how_it_works=[
            "50% low-volatility stocks (inverse-vol weighted), 30% quality stocks (composite), 10% gold, 10% liquid.",
            "The two stock sleeves draw from separate, de-duplicated universes.",
            "Quarterly rebalance; a regime gate trims the equity sleeves in a downtrend.",
        ],
        spec={
            "sleeves": [
                {"id": "lowvol", "name": "Low Volatility", "weight_pct": 50.0,
                 "weighting": "inverse_vol", "members": U.LOW_VOL, "max_weight_pct": 8.0,
                 "rule": _NONE},
                {"id": "quality", "name": "Quality", "weight_pct": 30.0,
                 "weighting": "score_weighted", "members": U.QUALITY, "max_weight_pct": 6.0,
                 "rule": _composite(126, 12, FW_DEFENSIVE, hold_k=16, trend_ma=0)},
                {"id": "gold", "name": "Gold", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    # ============================================== THEMATIC & SECTOR
    _p(
        key="dynamic-sector-rotation",
        name="Dynamic Sector Rotation",
        category="Thematic & Sector",
        risk_level=4,
        objective=(
            "Rotate into the sectors showing the strongest trend and momentum, "
            "holding several liquid names from each — not one stock as a proxy "
            "for a whole sector."
        ),
        investor_profile="Aggressive",
        horizon="3-5 years",
        investment_style="Sector momentum",
        holdings="10-12 stocks across leading sectors + gold",
        rebalance_frequency="monthly",
        benchmark="NIFTY 50",
        differentiators=[
            "Built on real sector universes (5-12 names each), not single bellwethers",
            "Concentrates naturally in whatever sectors are leading",
            "10% gold sleeve as ballast",
        ],
        how_it_works=[
            "Ranks a combined universe of nine sector books (Financials, IT, Pharma, Auto, FMCG, Metals, Energy, Infra, Realty) on a momentum + relative-strength + trend + volume composite.",
            "Holds the top 10 at 90% weight, equal weighted, monthly.",
            "An explicit sector score → top-3-sector allocation on top of this lands in Phase 4.",
            "10% gold.",
        ],
        spec={
            "sleeves": [
                {"id": "sectors", "name": "Leading Sectors", "weight_pct": 90.0,
                 "weighting": "equal", "members": U.SECTOR_ALL, "max_weight_pct": 12.0,
                 "rule": _composite(126, 10, FW_SECTOR, hold_k=15, trend_ma=200)},
                {"id": "gold", "name": "Gold", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    ),
    _p(
        key="india-consumption-growth",
        name="India Consumption Growth",
        category="Thematic & Sector",
        risk_level=4,
        objective=(
            "Own India's long-term consumption story — staples, discretionary, "
            "autos, retail and branded consumption — selected for structural "
            "growth, not just price."
        ),
        investor_profile="Aggressive",
        horizon="5+ years",
        investment_style="Structural theme",
        holdings="10-12 stocks",
        rebalance_frequency="monthly",
        benchmark="NIFTY 50",
        differentiators=[
            "A structural thematic basket, not another momentum portfolio",
            "Weights structural growth (35%) above momentum (35%) and earnings growth (20%)",
            "Universe spans FMCG, discretionary, autos, retail and lifestyle",
        ],
        how_it_works=[
            "Ranks a 20-name consumption universe on a structural-growth composite (fundamental growth on the live signal; long-horizon momentum as the proxy in the backtest).",
            "Holds the top 11, score-weighted, monthly.",
            "Trend filter keeps it in names above their 200-day average.",
        ],
        spec={
            "sleeves": [
                {"id": "consum", "name": "Consumption", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": U.CONSUMPTION, "max_weight_pct": 14.0,
                 "rule": _composite(126, 11, FW_CONSUMPTION, hold_k=15, trend_ma=200)},
            ],
        },
    ),
    # =========================================================== INCOME
    _p(
        key="dividend-income",
        name="Dividend & Income",
        category="Income",
        risk_level=2,
        objective=(
            "Generate income from dividends and yield instruments while avoiding "
            "low-quality dividend traps."
        ),
        investor_profile="Conservative to Moderate",
        horizon="3+ years",
        investment_style="Yield with quality screen",
        holdings="Dividend ETF + high-yield stocks + REITs + liquid",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 50",
        differentiators=[
            "35% dividend ETF / 35% high-dividend-quality stocks / 15% REITs & InvITs / 15% liquid",
            "Yield is screened for sustainability — never selected on headline yield alone",
            "REIT / InvIT sleeve degrades to cash where instrument coverage is thin",
        ],
        how_it_works=[
            "35% a Nifty dividend-opportunities ETF, 35% high-payout stocks (energy / metals / utilities), 15% REITs & InvITs, 15% liquid.",
            "The stock sleeve is inverse-vol weighted; the live signal adds a dividend-sustainability score (Phase 2).",
            "Rebalanced quarterly.",
        ],
        spec={
            "sleeves": [
                {"id": "divetf", "name": "Dividend ETF", "weight_pct": 35.0,
                 "weighting": "equal", "members": ["DIVOPPBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "yield", "name": "High-Yield Stocks", "weight_pct": 35.0,
                 "weighting": "inverse_vol", "members": U.HIGH_YIELD, "max_weight_pct": 6.0,
                 "rule": _NONE},
                {"id": "reits", "name": "REITs & InvITs", "weight_pct": 15.0,
                 "weighting": "equal", "members": U.REITS_INVITS, "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 15.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
        },
    ),
    # ====================================================== MULTI-ASSET
    _p(
        key="golden-wealth",
        name="Golden Wealth",
        category="Multi-Asset",
        risk_level=1,
        objective=(
            "A diversified portfolio designed for long-term wealth preservation "
            "and steady growth across equity, bonds and gold."
        ),
        investor_profile="Conservative",
        horizon="5+ years",
        investment_style="Strategic allocation",
        holdings="Equity / midcap / G-Sec / gold / liquid ETFs",
        rebalance_frequency="quarterly",
        benchmark="NIFTY 50",
        differentiators=[
            "Consolidates permanent-portfolio / 60-40 / risk-parity ideas into one product",
            "Strategic 40 / 10 / 20 / 20 / 10 with defined dynamic ranges",
            "Lowest risk level in the catalog",
        ],
        how_it_works=[
            "Strategic weights: 40% Indian equity, 10% midcap, 20% government bonds, 20% gold, 10% liquid.",
            "Held via broad ETFs and rebalanced quarterly or on drift.",
            "The internal engine may tilt within ranges (equity 35-60, bonds 15-30, gold 10-30, liquid 5-20) — Phase 2.",
        ],
        spec={
            "sleeves": [
                {"id": "equity", "name": "Indian Equity", "weight_pct": 40.0,
                 "weighting": "equal", "members": ["NIFTYBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "mid", "name": "Midcap Equity", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["MID150BEES"], "rule": _NONE, "risk_asset": False},
                {"id": "gsec", "name": "Government Bonds", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["GSEC10IETF"], "rule": _NONE, "risk_asset": False},
                {"id": "gold", "name": "Gold", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
        },
    ),
]


def flagship() -> list[dict[str, Any]]:
    """The 12 user-facing products (deep-copied dicts)."""
    import copy

    return [copy.deepcopy(p) for p in CATALOG]


def by_key(key: str) -> dict[str, Any] | None:
    for p in CATALOG:
        if p["key"] == key:
            import copy

            return copy.deepcopy(p)
    return None


def categories() -> list[str]:
    return list(CATEGORIES)


def journeys() -> dict[str, list[str]]:
    return {k: list(v) for k, v in JOURNEYS.items()}


def risk_labels() -> dict[int, str]:
    return dict(RISK_LABELS)
