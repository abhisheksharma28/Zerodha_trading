"""Phase 13 + 16 driver — one worker tick for Adaptive Options.

* records a fresh option-chain snapshot for the tracked underlyings (this is
  what makes IV rank / PCR percentile / OI migration improve over time and
  seeds the intraday backtest), and
* advances every ACTIVE paper run through the decision engine.

Safe to call from an HTTP endpoint or the background worker; it never
raises (a failure on one underlying / run is logged in the result).
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy.orm import Session

from app.adaptive_options import paper
from app.adaptive_options.config import AdaptiveConfig
from app.adaptive_options.service import _analyse
from app.config import Settings

_RECORD_UNDERLYINGS = ("NIFTY", "BANKNIFTY")
_MKT_OPEN, _MKT_CLOSE = time(9, 15), time(15, 30)


def _market_hours(now: datetime) -> bool:
    return now.weekday() < 5 and _MKT_OPEN <= now.time() <= _MKT_CLOSE


def run_once(
    db: Session, settings: Settings, *, now: datetime | None = None, force: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now()
    result: dict[str, Any] = {"recorded": {}, "paper": None, "skipped": None}

    if not force and not _market_hours(now):
        result["skipped"] = "outside market hours"
        return result

    for u in _RECORD_UNDERLYINGS:
        try:
            cfg = AdaptiveConfig.from_dict(None, preset="balanced")
            b = _analyse(db, settings, underlying=u, expiry=None, cfg=cfg, record=True)
            result["recorded"][u] = b.recorded if not isinstance(b, dict) else b.get("reason")
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            result["recorded"][u] = f"error: {exc}"

    try:
        result["paper"] = paper.tick_all(db, settings)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        result["paper"] = {"error": str(exc)}

    return result
