"""Starter basket definitions — a curated catalog the user can clone and
edit, organised into categories. Each ``spec`` validates against
``app.baskets.spec``.

The groupings follow how model-portfolio / wealth-management shops actually
build allocations:

* **Multi-asset**   — all-weather / risk-parity / permanent-portfolio style
                      buckets that balance equity, gold, silver and debt.
* **Single asset**  — one asset class only (commodities, debt, metals).
* **Factor**        — momentum / low-volatility / quality sleeves.
* **Sector rotation** — rule-driven rotation across sectors or a sector
                      complex, built from liquid stocks (long history).
* **Income**        — dividend / yield tilt.
* **Core-satellite** — a passive index core plus tactical satellites.

ETF-based baskets can only be backtested as far as their youngest ETF has
history (several sector / factor / bond ETFs listed only in 2022-2024);
the backtest reports the real window it used. Rotation baskets use stocks
so they backtest a full decade.
"""

from __future__ import annotations

from typing import Any

# --- stock pools (NSE, liquid, long history) -----------------------------

_LARGE_CAPS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS", "LT", "ITC", "AXISBANK",
    "SBIN", "BHARTIARTL", "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI",
    "SUNPHARMA", "TITAN", "ULTRACEMCO", "NTPC", "POWERGRID", "TATAMOTORS",
    "M&M", "ADANIPORTS", "ASIANPAINT", "HCLTECH", "TATASTEEL", "JSWSTEEL",
    "COALINDIA", "GRASIM", "NESTLEIND", "WIPRO",
]

_SECTOR_BELLWETHERS = [
    "HDFCBANK", "INFY", "RELIANCE", "SUNPHARMA", "MARUTI", "TATASTEEL",
    "HINDUNILVR", "LT", "DLF", "BHARTIARTL", "NTPC", "TITAN",
]

_FINANCIALS = [
    "HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK",
    "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "SHRIRAMFIN", "SBILIFE", "HDFCLIFE",
    "BANKBARODA", "PNB",
]

_CONSUMPTION = [
    "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA", "DABUR", "MARICO", "GODREJCP",
    "TATACONSUM", "COLPAL", "VBL", "TITAN", "MARUTI", "M&M", "TATAMOTORS",
    "TRENT", "JUBLFOOD",
]

_QUALITY = [
    "HINDUNILVR", "NESTLEIND", "TCS", "INFY", "ASIANPAINT", "PIDILITIND",
    "BAJAJ-AUTO", "HEROMOTOCO", "MARICO", "DABUR", "COLPAL", "BRITANNIA",
    "TITAN", "HAVELLS", "KOTAKBANK",
]

_LOW_VOL = [
    "HINDUNILVR", "NESTLEIND", "ITC", "BRITANNIA", "DABUR", "MARICO",
    "POWERGRID", "NTPC", "SUNPHARMA", "CIPLA", "DRREDDY", "ASIANPAINT",
    "PIDILITIND", "COLPAL", "BAJAJ-AUTO",
]

_HIGH_YIELD = [
    "ITC", "COALINDIA", "POWERGRID", "NTPC", "ONGC", "IOC", "BPCL", "HINDPETRO",
    "GAIL", "OIL", "HINDZINC", "VEDL",
]

_MOMENTUM_POOL = _LARGE_CAPS + [
    "TRENT", "BEL", "HAL", "BAJAJ-AUTO", "DIVISLAB", "CIPLA", "DRREDDY",
    "SIEMENS", "ABB", "HAVELLS", "PERSISTENT", "COFORGE", "DIXON",
]

# --- template catalog --------------------------------------------------------

TEMPLATE_CATEGORIES = [
    "Multi-asset",
    "Single asset class",
    "Factor",
    "Sector rotation",
    "Income",
    "Core-satellite",
]

_NONE = {"type": "none"}

# a light default regime gate: de-risk to 50% equity when the Nifty closes
# below its 200-day average
_REGIME = {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.5}


def _mom(lookback: int = 126, top_k: int = 8, trend_ma: int = 200, min_roc_pct: float = 0.0,
         hold_k: int = 0):
    return {
        "type": "momentum_top_k", "lookback": lookback, "top_k": top_k,
        "trend_ma": trend_ma, "min_roc_pct": min_roc_pct, "hold_k": hold_k,
    }


def _composite(lookback: int, top_k: int, factor_weights: dict, *, hold_k: int = 0,
               trend_ma: int = 200, min_roc_pct: float = 0.0):
    return {
        "type": "composite_score", "lookback": lookback, "top_k": top_k, "hold_k": hold_k,
        "trend_ma": trend_ma, "min_roc_pct": min_roc_pct, "factor_weights": factor_weights,
    }


# blended factor weights. In a historical backtest only momentum/trend/low_vol
# apply (the fundamental factors are renormalised away); live / paper signals
# add quality / value / growth from present-day fundamentals.
_FW_CORE = {"momentum": 0.30, "trend": 0.20, "low_vol": 0.15,
            "quality": 0.20, "growth": 0.10, "value": 0.05}
_FW_MOM_QUALITY = {"momentum": 0.40, "trend": 0.10, "quality": 0.35, "growth": 0.15}
_FW_ALPHA = {"momentum": 0.40, "trend": 0.20, "low_vol": 0.10,
             "quality": 0.20, "value": 0.10}
_FW_DEFENSIVE = {"low_vol": 0.45, "trend": 0.15, "quality": 0.30, "value": 0.10}

_MIDCAPS = [
    "PERSISTENT", "COFORGE", "DIXON", "POLYCAB", "CUMMINSIND", "ASHOKLEY", "BALKRISIND",
    "MPHASIS", "AUROPHARMA", "LUPIN", "ALKEM", "TORNTPHARM", "OBEROIRLTY", "PRESTIGE",
    "PHOENIXLTD", "APLAPOLLO", "SUPREMEIND", "PIIND", "BHARATFORG", "SRF", "TATACHEM",
    "GODREJPROP", "MUTHOOTFIN", "ABCAPITAL", "FEDERALBNK",
]


TEMPLATES: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ Multi-asset
    {
        "key": "all-weather",
        "name": "All-Weather (Equity / Gold / Silver)",
        "category": "Multi-asset",
        "tags": ["all-weather", "gold", "silver", "ETF"],
        "description": (
            "A static 50 / 30 / 20 split across a Nifty index ETF, gold and silver — "
            "the precious-metals sleeves cushion equity drawdowns. No rotation; "
            "rebalanced monthly back to the fixed weights."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "equity", "name": "Equity (Nifty ETF)", "weight_pct": 50.0,
                 "weighting": "equal", "members": ["NIFTYBEES"], "rule": _NONE},
                {"id": "gold", "name": "Gold", "weight_pct": 30.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE},
                {"id": "silver", "name": "Silver", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["SILVERBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "permanent-portfolio",
        "name": "Permanent Portfolio",
        "category": "Multi-asset",
        "tags": ["Harry Browne", "equal-weight", "defensive", "ETF"],
        "description": (
            "Harry Browne's four-quadrant portfolio adapted to NSE: 25% each in a "
            "Nifty ETF (prosperity), a 10-year G-Sec ETF (deflation), gold "
            "(inflation) and liquid/overnight (recession). One asset always works."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "equity", "name": "Equity", "weight_pct": 25.0, "weighting": "equal",
                 "members": ["NIFTYBEES"], "rule": _NONE},
                {"id": "gsec", "name": "Long G-Sec", "weight_pct": 25.0, "weighting": "equal",
                 "members": ["GSEC10IETF"], "rule": _NONE},
                {"id": "gold", "name": "Gold", "weight_pct": 25.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE},
                {"id": "cash", "name": "Liquid / cash", "weight_pct": 25.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "golden-butterfly",
        "name": "Golden Butterfly",
        "category": "Multi-asset",
        "tags": ["Tyler / Portfolio Charts", "small-cap tilt", "gold", "ETF"],
        "description": (
            "Five equal 20% slices — large-cap equity, mid-cap equity, a long "
            "G-Sec ETF, liquid/short duration and gold. A small growth tilt on top "
            "of the Permanent Portfolio's balance."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "large", "name": "Large-cap", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["NIFTYBEES"], "rule": _NONE},
                {"id": "mid", "name": "Mid-cap", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["MID150BEES"], "rule": _NONE},
                {"id": "gsec", "name": "Long G-Sec", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["GSEC10IETF"], "rule": _NONE},
                {"id": "cash", "name": "Liquid", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE},
                {"id": "gold", "name": "Gold", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "balanced-60-40",
        "name": "Balanced 60 / 40",
        "category": "Multi-asset",
        "tags": ["classic", "equity/debt", "ETF"],
        "description": (
            "The textbook balanced allocation: 60% equity (Nifty ETF), 30% a "
            "target-maturity bond ETF, 10% liquid. Rebalanced monthly."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "equity", "name": "Equity", "weight_pct": 60.0, "weighting": "equal",
                 "members": ["NIFTYBEES"], "rule": _NONE},
                {"id": "bonds", "name": "Bonds", "weight_pct": 30.0, "weighting": "equal",
                 "members": ["EBBETF0433"], "rule": _NONE},
                {"id": "cash", "name": "Liquid", "weight_pct": 10.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "risk-parity-lite",
        "name": "Risk-Parity Lite",
        "category": "Multi-asset",
        "tags": ["risk parity", "inverse-vol", "ETF"],
        "description": (
            "Equity, gold and a G-Sec ETF, weighted by inverse volatility so each "
            "contributes roughly equal risk instead of equal rupees — a retail "
            "approximation of risk parity. A 50% single-name cap stops the "
            "lowest-vol sleeve from swallowing the book, plus a small cash buffer."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "rp", "name": "Risk-parity blend", "weight_pct": 90.0,
                 "weighting": "inverse_vol", "max_weight_pct": 50.0,
                 "members": ["NIFTYBEES", "GOLDBEES", "GSEC10IETF"],
                 "rule": _NONE},
                {"id": "cash", "name": "Cash buffer", "weight_pct": 10.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ]
        },
    },
    {
        "key": "momentum-gold-ballast",
        "name": "Momentum core + Gold ballast",
        "category": "Multi-asset",
        "tags": ["momentum", "gold", "trend filter"],
        "description": (
            "A 65% equity sleeve that each month holds the 8 strongest large caps "
            "(6-month momentum, above the 200-day average), balanced by 25% gold + "
            "10% silver. Inverse-vol weighted so no single name dominates."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "equity-core", "name": "Momentum core", "weight_pct": 65.0,
                 "weighting": "inverse_vol", "members": _LARGE_CAPS, "rule": _mom(126, 8, 200, hold_k=12)},
                {"id": "gold", "name": "Gold", "weight_pct": 25.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE},
                {"id": "silver", "name": "Silver", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["SILVERBEES"], "rule": _NONE},
            ]
        },
    },
    # ------------------------------------------------------------ Single asset class
    {
        "key": "commodities-only",
        "name": "Commodities Only",
        "category": "Single asset class",
        "tags": ["gold", "silver", "commodities", "ETF"],
        "description": (
            "A pure hard-asset basket — 55% gold, 35% silver, 10% a broad "
            "commodities ETF. An inflation / crisis hedge with no equity or debt."
        ),
        "benchmark": "GOLDBEES",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "gold", "name": "Gold", "weight_pct": 55.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE},
                {"id": "silver", "name": "Silver", "weight_pct": 35.0, "weighting": "equal",
                 "members": ["SILVERBEES"], "rule": _NONE},
                {"id": "broad", "name": "Broad commodities", "weight_pct": 10.0,
                 "weighting": "equal", "members": ["COMMOIETF"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "precious-metals",
        "name": "Precious Metals (Gold + Silver)",
        "category": "Single asset class",
        "tags": ["gold", "silver", "ETF", "long history"],
        "description": (
            "The simplest metals basket — 60% gold, 40% silver, rebalanced monthly "
            "so you keep selling the one that ran and buying the laggard."
        ),
        "benchmark": "GOLDBEES",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "gold", "name": "Gold", "weight_pct": 60.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE},
                {"id": "silver", "name": "Silver", "weight_pct": 40.0, "weighting": "equal",
                 "members": ["SILVERBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "debt-only",
        "name": "Debt Only (Liquid + G-Sec + Bonds)",
        "category": "Single asset class",
        "tags": ["debt", "G-Sec", "target maturity", "ETF", "short history"],
        "description": (
            "A fixed-income-only parking basket: 40% liquid/overnight, 35% a "
            "10-year G-Sec ETF, 25% a target-maturity bond ETF. Note the G-Sec and "
            "bond ETFs only listed in 2022, so the backtest window is short."
        ),
        "benchmark": "LIQUIDBEES",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "liquid", "name": "Liquid / overnight", "weight_pct": 40.0,
                 "weighting": "equal", "members": ["LIQUIDBEES"], "rule": _NONE},
                {"id": "gsec", "name": "10-year G-Sec", "weight_pct": 35.0,
                 "weighting": "equal", "members": ["GSEC10IETF"], "rule": _NONE},
                {"id": "bonds", "name": "Target-maturity bonds", "weight_pct": 25.0,
                 "weighting": "equal", "members": ["EBBETF0433"], "rule": _NONE},
            ]
        },
    },
    # ---------------------------------------------------------------------- Factor
    {
        "key": "momentum-leaders",
        "name": "Momentum Leaders",
        "category": "Factor",
        "tags": ["momentum", "trend filter", "monthly rotation"],
        "description": (
            "Pure price momentum: each month hold the 10 strongest names from a "
            "large/mid-cap pool (6-month return, must be above the 200-day "
            "average), equal weighted. Fully invested, no ballast."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "mom", "name": "Momentum", "weight_pct": 100.0, "weighting": "equal",
                 "members": _MOMENTUM_POOL, "rule": _mom(126, 10, 200, hold_k=15)},
            ]
        },
    },
    {
        "key": "low-volatility-defensive",
        "name": "Low-Volatility Defensive",
        "category": "Factor",
        "tags": ["low vol", "defensive", "inverse-vol"],
        "description": (
            "A basket of classic low-beta compounders (staples, pharma, utilities) "
            "held inverse-volatility weighted, so the calmest names carry the most "
            "weight. Aims for equity-like returns with smaller drawdowns."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "lowvol", "name": "Low volatility", "weight_pct": 100.0,
                 "weighting": "inverse_vol", "members": _LOW_VOL, "rule": _NONE},
            ]
        },
    },
    {
        "key": "quality-compounders",
        "name": "Quality Compounders",
        "category": "Factor",
        "tags": ["quality", "high ROE", "buy and hold"],
        "description": (
            "Equal-weight hold of 15 high-return-on-equity, low-leverage franchises "
            "with long compounding records. Rebalanced quarterly — a low-turnover "
            "quality sleeve."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "quality", "name": "Quality", "weight_pct": 100.0, "weighting": "equal",
                 "members": _QUALITY, "rule": _NONE},
            ]
        },
    },
    # -------------------------------------------------------------- Sector rotation
    {
        "key": "sector-leaders-gold",
        "name": "Sector leaders + Gold",
        "category": "Sector rotation",
        "tags": ["sector rotation", "momentum", "gold ballast"],
        "description": (
            "Rotates quarterly into the 5 strongest sector bellwethers (one liquid "
            "name per major sector, 6-month momentum, above the 200-day average), "
            "equal weighted, with a 20% gold sleeve for balance."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "sector-leaders", "name": "Sector leaders", "weight_pct": 80.0,
                 "weighting": "equal", "members": _SECTOR_BELLWETHERS, "rule": _mom(126, 5, 200, hold_k=8)},
                {"id": "gold", "name": "Gold", "weight_pct": 20.0,
                 "weighting": "equal", "members": ["GOLDBEES"], "rule": _NONE},
            ]
        },
    },
    {
        "key": "sector-momentum-rotation",
        "name": "Sector Momentum Rotation",
        "category": "Sector rotation",
        "tags": ["sector rotation", "momentum", "fully invested"],
        "description": (
            "A pure sector-rotation sleeve — each month hold the 4 strongest sector "
            "bellwethers by 6-month momentum (trend filter on), equal weighted. No "
            "ballast; this is the aggressive rotation engine."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "sectors", "name": "Sector rotation", "weight_pct": 100.0,
                 "weighting": "equal", "members": _SECTOR_BELLWETHERS, "rule": _mom(126, 4, 200, hold_k=6)},
            ]
        },
    },
    {
        "key": "financials-complex",
        "name": "Financials Complex",
        "category": "Sector rotation",
        "tags": ["banks", "NBFC", "insurance", "momentum"],
        "description": (
            "A single-sector rotation across the financials stack — private and PSU "
            "banks, NBFCs and insurers. Holds the 6 strongest by 6-month momentum "
            "(trend filter on, an 18% single-name cap and a hold buffer); a regime "
            "gate cuts exposure to 40% when the Nifty is below its 200-day average, "
            "since a concentrated bank book falls hard in a sell-off."
        ),
        "benchmark": "NIFTY BANK",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "fin", "name": "Financials", "weight_pct": 100.0, "weighting": "equal",
                 "members": _FINANCIALS, "max_weight_pct": 18.0,
                 "rule": _mom(126, 6, 200, hold_k=9)},
            ],
            "risk": {"regime": {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.4}},
        },
    },
    {
        "key": "consumption-basket",
        "name": "Consumption Basket",
        "category": "Sector rotation",
        "tags": ["FMCG", "discretionary", "auto", "momentum"],
        "description": (
            "The India-consumption theme — staples, discretionary, autos, retail. "
            "Holds the 6 strongest by 6-month momentum above their 200-day average, "
            "equal weighted, rebalanced monthly."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "consum", "name": "Consumption", "weight_pct": 100.0, "weighting": "equal",
                 "members": _CONSUMPTION, "rule": _mom(126, 6, 200, hold_k=9)},
            ]
        },
    },
    # ---------------------------------------------------------------------- Income
    {
        "key": "dividend-income",
        "name": "Dividend & Income",
        "category": "Income",
        "tags": ["dividend yield", "PSU", "defensive"],
        "description": (
            "A yield tilt: 50% a Nifty Dividend Opportunities ETF, 35% an "
            "equal-weight sleeve of high-payout PSU energy / metals names, 15% "
            "liquid. Rebalanced quarterly."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "divetf", "name": "Dividend ETF", "weight_pct": 50.0, "weighting": "equal",
                 "members": ["DIVOPPBEES"], "rule": _NONE},
                {"id": "yield", "name": "High-yield stocks", "weight_pct": 35.0,
                 "weighting": "equal", "members": _HIGH_YIELD, "rule": _NONE},
                {"id": "cash", "name": "Liquid", "weight_pct": 15.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE},
            ]
        },
    },
    # -------------------------------------------------------------- Core-satellite
    {
        "key": "core-satellite-sectors",
        "name": "Core + Sector Satellites",
        "category": "Core-satellite",
        "tags": ["core-satellite", "index core", "sector tilt"],
        "description": (
            "A 60% passive Nifty ETF core, then two 20% tactical satellites that "
            "each rotate into the single strongest sector bellwether by 6-month "
            "momentum. The core anchors the portfolio; the satellites chase "
            "leadership."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "core", "name": "Index core", "weight_pct": 60.0, "weighting": "equal",
                 "members": ["NIFTYBEES"], "rule": _NONE},
                {"id": "sat1", "name": "Sector satellite A", "weight_pct": 20.0,
                 "weighting": "equal", "members": _SECTOR_BELLWETHERS, "rule": _mom(126, 1, 200)},
                {"id": "sat2", "name": "Sector satellite B", "weight_pct": 20.0,
                 "weighting": "equal", "members": _SECTOR_BELLWETHERS, "rule": _mom(63, 1, 200)},
            ]
        },
    },
    # ------------------------------------------------------------- Factor (multi)
    {
        "key": "ai-dynamic-core",
        "name": "AI Dynamic Core",
        "category": "Factor",
        "tags": ["multi-factor", "composite score", "regime gate", "flagship"],
        "description": (
            "The flagship: an 80% multi-factor core that each month holds the top "
            "15 of a 30-name large-cap pool by a blended score (momentum + trend + "
            "low-vol in the backtest; quality / growth / value added on the live "
            "signal), score-weighted with a 10% single-name cap and a 15-name hold "
            "buffer to curb churn. A Nifty regime gate cuts equity to half when the "
            "index is below its 200-day average; 20% gold ballast."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "core", "name": "Multi-factor core", "weight_pct": 80.0,
                 "weighting": "score_weighted", "members": _LARGE_CAPS, "max_weight_pct": 10.0,
                 "rule": _composite(126, 15, _FW_CORE, hold_k=20, trend_ma=200)},
                {"id": "gold", "name": "Gold ballast", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"max_position_pct": 12.0, "regime": _REGIME},
        },
    },
    {
        "key": "momentum-quality",
        "name": "Momentum + Quality",
        "category": "Factor",
        "tags": ["momentum", "quality", "composite score", "trend filter"],
        "description": (
            "Owns companies where the business and the tape are both strong — a "
            "blended momentum + quality score over a large-cap pool, top 12, "
            "score-weighted, with a hold buffer and the 200-day trend filter on. "
            "Avoids weak-quality momentum names and strong companies stuck in a "
            "downtrend."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "mq", "name": "Momentum + Quality", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": _LARGE_CAPS, "max_weight_pct": 12.0,
                 "rule": _composite(126, 12, _FW_MOM_QUALITY, hold_k=18, trend_ma=200)},
            ],
        },
    },
    {
        "key": "ai-alpha-opportunities",
        "name": "AI Alpha Opportunities",
        "category": "Factor",
        "tags": ["high conviction", "multi-factor", "aggressive"],
        "description": (
            "The highest-conviction multi-factor sleeve — top 12 of a broad "
            "large/mid pool by a momentum-tilted composite, score-weighted, fully "
            "invested, no ballast. Higher turnover and higher risk; a regime gate "
            "still halves exposure in a downtrend."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "alpha", "name": "Alpha", "weight_pct": 100.0, "weighting": "score_weighted",
                 "members": _MOMENTUM_POOL, "max_weight_pct": 12.0,
                 "rule": _composite(126, 12, _FW_ALPHA, hold_k=16, trend_ma=200)},
            ],
            "risk": {"regime": _REGIME},
        },
    },
    {
        "key": "growth-accelerators",
        "name": "Growth Accelerators",
        "category": "Factor",
        "tags": ["growth", "momentum proxy", "trend filter"],
        "description": (
            "Targets accelerating businesses. Without point-in-time estimate data "
            "the backtest proxies acceleration with 3- and 6-month price momentum "
            "on a growth-tilted pool (top 10, trend filter on); the live signal "
            "adds fundamental growth + earnings direction."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "growth", "name": "Growth", "weight_pct": 100.0, "weighting": "score_weighted",
                 "members": _MOMENTUM_POOL, "max_weight_pct": 14.0,
                 "rule": _composite(63, 10, {"momentum": 0.55, "trend": 0.25, "growth": 0.20},
                                    hold_k=15, trend_ma=200)},
            ],
        },
    },
    {
        "key": "smallmid-smart-alpha",
        "name": "Small & Midcap Smart Alpha",
        "category": "Factor",
        "tags": ["midcap", "multi-factor", "strict risk limits"],
        "description": (
            "Higher-growth mid-cap opportunities with tight risk controls — top 15 "
            "of a 25-name liquid mid-cap pool by a momentum + quality composite, "
            "score-weighted, a strict 8% single-name cap, an 18-name hold buffer, "
            "and a regime gate. Mid-caps fall harder, so the de-risk matters."
        ),
        "benchmark": "NIFTY MIDCAP 100",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "mid", "name": "Midcap alpha", "weight_pct": 100.0,
                 "weighting": "score_weighted", "members": _MIDCAPS, "max_weight_pct": 8.0,
                 "rule": _composite(126, 15, _FW_MOM_QUALITY, hold_k=18, trend_ma=200)},
            ],
            "risk": {"max_position_pct": 9.0,
                     "regime": {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.4}},
        },
    },
    {
        "key": "defensive-leaders",
        "name": "Defensive Leaders",
        "category": "Factor",
        "tags": ["defensive", "low vol", "quality", "capital protection"],
        "description": (
            "Capital-protection sleeve — a low-volatility + quality composite over "
            "a pool of stable, low-debt franchises (top 12, inverse-vol style "
            "score), a hold buffer, a 20% gold ballast and a regime gate. Aims to "
            "lose less when the market turns."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 4.0,
        "spec": {
            "sleeves": [
                {"id": "def", "name": "Defensive leaders", "weight_pct": 80.0,
                 "weighting": "score_weighted", "members": _LOW_VOL + _QUALITY,
                 "max_weight_pct": 12.0,
                 "rule": _composite(126, 12, _FW_DEFENSIVE, hold_k=18, trend_ma=0)},
                {"id": "gold", "name": "Gold ballast", "weight_pct": 20.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    },
    # ----------------------------------------------------------------- Multi-asset
    {
        "key": "all-weather-factor",
        "name": "All-Weather (Factor)",
        "category": "Multi-asset",
        "tags": ["all-weather", "factor sleeves", "regime gate"],
        "description": (
            "A factor take on all-weather: a 45% momentum-core sleeve and a 30% "
            "low-volatility sleeve of stocks, 15% gold and 10% liquid, with a "
            "regime gate that halves the two equity sleeves when the Nifty is "
            "below its 200-day average. Prioritises smooth risk-adjusted returns."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "monthly",
        "drift_band_pct": 3.0,
        "spec": {
            "sleeves": [
                {"id": "mom", "name": "Momentum core", "weight_pct": 45.0,
                 "weighting": "score_weighted", "members": _LARGE_CAPS, "max_weight_pct": 8.0,
                 "rule": _composite(126, 12, {"momentum": 0.6, "trend": 0.4}, hold_k=16)},
                {"id": "lowvol", "name": "Low-vol core", "weight_pct": 30.0,
                 "weighting": "inverse_vol", "members": _LOW_VOL, "rule": _NONE},
                {"id": "gold", "name": "Gold", "weight_pct": 15.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
                {"id": "cash", "name": "Liquid", "weight_pct": 10.0, "weighting": "equal",
                 "members": ["LIQUIDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": _REGIME},
        },
    },
    {
        "key": "tactical-regime",
        "name": "Tactical Market Regime",
        "category": "Multi-asset",
        "tags": ["regime rotation", "risk-managed", "gold"],
        "description": (
            "Rotates aggressively with the market regime: a momentum-tilted "
            "composite core plus gold, but the regime gate cuts the equity core to "
            "just 30% when the Nifty is below its 200-day average, parking the rest "
            "in cash. Quarterly, so it commits to a stance."
        ),
        "benchmark": "NIFTY 50",
        "rebalance_frequency": "quarterly",
        "drift_band_pct": 5.0,
        "spec": {
            "sleeves": [
                {"id": "core", "name": "Regime core", "weight_pct": 75.0,
                 "weighting": "score_weighted", "members": _LARGE_CAPS, "max_weight_pct": 10.0,
                 "rule": _composite(126, 12, {"momentum": 0.5, "trend": 0.3, "low_vol": 0.2},
                                    hold_k=16, trend_ma=200)},
                {"id": "gold", "name": "Gold", "weight_pct": 25.0, "weighting": "equal",
                 "members": ["GOLDBEES"], "rule": _NONE, "risk_asset": False},
            ],
            "risk": {"regime": {"benchmark": "NIFTY 50", "ma": 200, "risk_off_scale": 0.3}},
        },
    },
]


def templates() -> list[dict[str, Any]]:
    return [dict(t) for t in TEMPLATES]


def categories() -> list[str]:
    return list(TEMPLATE_CATEGORIES)
