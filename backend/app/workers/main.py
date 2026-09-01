"""Background worker process entry point.

Runs the strategy-evaluation loop (app.workers.runner.DeploymentWorker) for
every RUNNING paper/simulation deployment: maintain a strategy instance per
deployment, feed it newly-closed candles, and route its order intents
through the paper/simulation executors.

Kept as its own process (the `worker` service in docker-compose.yml) so a
strategy-evaluation crash can never take the API process down with it.
"""

import signal

from app.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.workers.runner import DeploymentWorker

configure_logging()
logger = get_logger(__name__)


def main() -> None:
    worker = DeploymentWorker(SessionLocal, get_settings())

    def _handle_signal(signum, _frame):
        logger.info("worker_signal_received", signum=signum)
        worker.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    worker.run_forever()


if __name__ == "__main__":
    main()
