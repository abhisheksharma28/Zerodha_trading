"""Sector Seasonality — a research-grade engine.

A staged pipeline, deliberately separated:

    RAW DATA -> DATA-QUALITY AUDIT -> RESEARCH (edges, multi-horizon)
      -> STATISTICAL VALIDATION (t-stat, bootstrap, FDR)
      -> BACKTEST (walk-forward OOS, rank IC, long/short spread)
      -> MODEL FREEZE + VERSION -> PAPER TRADING -> HEALTH MONITORING

Modules:
  data       — load maximum available history per sector + a quality audit
  returns    — completed-month returns + three seasonal-edge measures
  stats      — per (sector, month) descriptive + inferential stats, bootstrap
  fdr        — Benjamini-Hochberg across the whole sector x month grid
  horizons   — recompute across 3/5/10/15/20/max windows + stability score
  regime     — bull / bear / high-vol conditioning
  scoring    — independent long-score and short-score + master confidence
  engine     — orchestrates the above into a report + per-month rankings
"""

SECTOR_UNIVERSE = [
    "NIFTY IT", "NIFTY BANK", "NIFTY PVT BANK", "NIFTY PSU BANK",
    "NIFTY FIN SERVICE", "NIFTY AUTO", "NIFTY PHARMA", "NIFTY HEALTHCARE",
    "NIFTY FMCG", "NIFTY CONSUMPTION", "NIFTY CONSR DURBL", "NIFTY METAL",
    "NIFTY ENERGY", "NIFTY OIL AND GAS", "NIFTY COMMODITIES", "NIFTY INFRA",
    "NIFTY REALTY", "NIFTY MEDIA",
]

MARKET_INDEX = "NIFTY 50"
VIX_INDEX = "INDIA VIX"

# Approx NSE index base year (back-computed series) vs the live launch year.
# Provider history often runs to the base year; research commonly uses it but
# the audit flags the pre-launch stretch so it is never treated as "live".
INDEX_TIMELINE: dict[str, tuple[int, int]] = {
    "NIFTY IT": (1996, 1999),
    "NIFTY BANK": (2000, 2003),
    "NIFTY PVT BANK": (2016, 2016),
    "NIFTY PSU BANK": (2004, 2011),
    "NIFTY FIN SERVICE": (2004, 2011),
    "NIFTY AUTO": (2004, 2011),
    "NIFTY PHARMA": (2001, 2011),
    "NIFTY HEALTHCARE": (2005, 2020),
    "NIFTY FMCG": (1996, 2011),
    "NIFTY CONSUMPTION": (2005, 2011),
    "NIFTY CONSR DURBL": (2005, 2020),
    "NIFTY METAL": (2004, 2011),
    "NIFTY ENERGY": (2004, 2011),
    "NIFTY OIL AND GAS": (2005, 2020),
    "NIFTY COMMODITIES": (2004, 2011),
    "NIFTY INFRA": (2004, 2011),
    "NIFTY REALTY": (2007, 2007),
    "NIFTY MEDIA": (2005, 2011),
    "NIFTY 50": (1996, 1996),
}

__all__ = ["SECTOR_UNIVERSE", "MARKET_INDEX", "VIX_INDEX", "INDEX_TIMELINE"]
