"""Refresh the canonical instrument master from Zerodha's instrument dumps.

Run with ``python -m app.sync_instruments`` (optionally
``python -m app.sync_instruments NSE NFO``). Idempotent; safe to schedule.
"""

import sys

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.services import instrument_service

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    exchanges = tuple(a.upper() for a in sys.argv[1:]) or instrument_service.DEFAULT_EXCHANGES
    db = SessionLocal()
    try:
        result = instrument_service.sync(db, exchanges)
        logger.info("instrument_sync_done", **result)
        print(
            f"Instrument master synced ({result['synced_at']}): "
            f"{result['total']} rows across {', '.join(result['by_exchange'])}"
        )
        for ex, counts in result["by_exchange"].items():
            print(f"  {ex}: {counts['rows']} rows, {counts['deactivated']} deactivated")
    finally:
        db.close()


if __name__ == "__main__":
    main()
