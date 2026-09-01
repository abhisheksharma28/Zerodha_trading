"""Background worker process entry point.

Placeholder for the deployment supervisor loop: for each RUNNING deployment,
maintain a market-data subscription, feed bars to the strategy instance, and
route resulting order intents through app.execution.router.OrderRouter.

This is intentionally not fleshed out yet — it's the next major piece of
work after the initial scaffold (running strategies continuously, market
data fan-out via Redis pub/sub per docs/ZERODHA_API_NOTES.md section 3, and
reconnect/reconciliation handling). Kept as its own process (started by the
`worker` service in docker-compose.yml) so a strategy-evaluation crash can
never take the API process down with it.
"""

import time

from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    logger.info("worker_started")
    while True:
        # TODO: poll RUNNING deployments, drive strategy evaluation loops.
        time.sleep(30)
        logger.debug("worker_heartbeat")


if __name__ == "__main__":
    main()
