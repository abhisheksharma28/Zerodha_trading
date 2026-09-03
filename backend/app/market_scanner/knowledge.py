"""Runtime knowledge config for the Trading Ideas engine.

Every weight, threshold and on/off switch the scorer uses is read from here
at import time, so the engine can be re-tuned by editing
``knowledge.yaml`` (next to this file) or the file pointed at by
``MARKET_SCANNER_KNOWLEDGE_FILE`` - no code change, no redeploy of the
Python. ``docs/TRADING_KNOWLEDGE_BASE.md`` is the human-readable companion;
this module is its machine-readable form.

The YAML file is a partial override: whatever keys it sets are deep-merged
over :data:`DEFAULTS`, so it only needs to carry the values being changed.
Call :func:`reload` to pick up edits without restarting the process.
"""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

_YAML_PATH = Path(os.getenv("MARKET_SCANNER_KNOWLEDGE_FILE", str(Path(__file__).with_name("knowledge.yaml"))))

# --------------------------------------------------------------------------
# defaults - these mirror what was previously hard-coded in signals.py
# --------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # which factor groups the scorer is allowed to use at all
    "enabled": {
        "candlesticks": True,
        "chart_patterns": True,
        "force_index": True,
        "reflexivity": True,
        "news": True,
        "sector": True,
        "calendar": True,
        "graham": True,
        "fundamentals": True,
    },
    # strict-score assembly
    "score": {
        "grade_a": 74.0,
        "grade_b": 58.0,
        "ceiling": 90.0,
        "min_confidence": 45.0,     # emission gate
        # 8 weighted sub-scores (should sum ~1.0)
        "quality_weights": {
            "alignment": 0.24, "trend": 0.16, "structure": 0.16, "location": 0.14,
            "momentum": 0.12, "rr": 0.08, "volume": 0.06, "risk_fit": 0.04,
        },
    },
    # candlestick pattern base weights (× shape strength × timeframe scale)
    "candle_weights": {
        "morning_star": 11, "evening_star": 11,
        "bullish_engulfing": 10, "bearish_engulfing": 10,
        "bull_marubozu": 10, "bear_marubozu": 10,
        "hammer": 9, "hanging_man": 9, "shooting_star": 9,
        "bullish_piercing": 8, "bearish_piercing": 8,
        "bullish_harami": 6, "bearish_harami": 6, "bullish_doji": 6, "bearish_doji": 6,
        "spinning_top": 4,
        "_default": 5,
    },
    # multi-swing chart pattern base weights (confirmed breakouts only)
    "chart_weights": {
        "head_shoulders_top": 13, "head_shoulders_bottom": 13,
        "triple_top": 12, "triple_bottom": 12,
        "double_top": 11, "double_bottom": 11,
        "ascending_triangle": 10, "descending_triangle": 10, "symmetrical_triangle": 9,
        "rectangle": 8,
        "_default": 7,
    },
    # Elder Force Index (features.force_index_13, price-normalised)
    "force_index": {"eps": 2.0e-4, "weight_gaining": 6.0, "weight_flat": 4.0},
    # Soros reflexivity nudge
    "reflexivity": {"extended_pct": 0.30, "boost": 4.0, "late_stage_penalty": 5.0,
                    "aligned_max_ext": 0.18},
    # news-headline heuristic
    "news": {"min_abs_score": 0.3, "weight": 7.0},
    # sector strength
    "sector": {"weight": 6.0, "lead_percentile": 0.75, "lag_percentile": 0.25, "nudge": 0.6},
    # Indian calendar effect (Karmakar & Chakraborty 2000)
    "calendar": {"turn_of_month": 0.7, "first_half": 0.35, "deep_second_half": -0.3, "weight": 4.0},
    # Graham defensive-investor screen (The Intelligent Investor, ch. 14)
    "graham": {"blend_value_max": 22.5, "blend_expensive_min": 45.0,
               "current_ratio_min": 2.0, "de_max": 1.0,
               "weight_value": 5.0, "weight_balance_sheet": 3.0, "weight_expensive": -4.0},
}

# --------------------------------------------------------------------------

def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load() -> dict[str, Any]:
    if not _YAML_PATH.exists():
        return deepcopy(DEFAULTS)
    try:
        import yaml

        with _YAML_PATH.open("r", encoding="utf-8") as fh:
            override = yaml.safe_load(fh) or {}
        if not isinstance(override, dict):
            raise ValueError("knowledge YAML must be a mapping at the top level")
        merged = _deep_merge(DEFAULTS, override)
        logger.info("scanner_knowledge_loaded", path=str(_YAML_PATH), keys=sorted(override))
        return merged
    except Exception as exc:  # noqa: BLE001 - a bad file must not break the engine
        logger.warning("scanner_knowledge_load_failed", path=str(_YAML_PATH), error=str(exc))
        return deepcopy(DEFAULTS)


KB: dict[str, Any] = _load()


def reload() -> dict[str, Any]:
    """Re-read the YAML override and swap :data:`KB` in place."""
    fresh = _load()
    KB.clear()
    KB.update(fresh)
    return KB


def enabled(group: str) -> bool:
    return bool(KB.get("enabled", {}).get(group, True))


def get(*path: str, default: Any = None) -> Any:
    node: Any = KB
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node
