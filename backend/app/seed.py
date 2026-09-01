"""Seed the database with the strategy library.

Run with ``python -m app.seed`` (or ``make seed``). Idempotent — existing
strategies are left untouched.
"""

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.strategies.library.seeding import seed_strategy_library

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    db = SessionLocal()
    try:
        result = seed_strategy_library(db)
        logger.info("strategy_library_seeded", created=result["created"], skipped=result["skipped"])
        print(f"Seeded strategy library: created={result['created']} skipped={result['skipped']}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
