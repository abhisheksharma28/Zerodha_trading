import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import api_router
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.live.latency import LATENCY
from app.websocket.routes import router as ws_router

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", environment=settings.environment)
    from app.live import engine as live_engine
    from app.market_scanner import scheduler as scanner_scheduler

    try:
        await live_engine.start(settings)
    except Exception:  # noqa: BLE001 - the ticker is optional, never block startup
        logger.exception("live_engine_start_failed")
    try:
        await scanner_scheduler.start()
    except Exception:  # noqa: BLE001 - the scanner loop is optional, never block startup
        logger.exception("market_scanner_start_failed")
    yield
    try:
        await scanner_scheduler.stop()
    except Exception:  # noqa: BLE001
        logger.exception("market_scanner_stop_failed")
    try:
        await live_engine.stop()
    except Exception:  # noqa: BLE001
        logger.exception("live_engine_stop_failed")
    logger.info("shutdown")


app = FastAPI(
    title="Trading Strategy Platform",
    version="0.1.0",
    lifespan=lifespan,
)

class ServerTimingMiddleware(BaseHTTPMiddleware):
    """Time every request's handler and expose it two ways:

    * ``Server-Timing: app;dur=<ms>`` response header — the browser reads
      this to split "server time" from "network time" in the ⚡ widget.
    * a sample in the process-local latency registry under
      ``api:<METHOD> <path>`` and the rollup stage ``api`` — so
      /monitoring/latency shows real backend numbers even with no ticker or
      deployment running.
    """

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter_ns()
        response = await call_next(request)
        elapsed_ns = time.perf_counter_ns() - start
        ms = elapsed_ns / 1_000_000.0
        response.headers["Server-Timing"] = f"app;dur={ms:.3f}"
        if request.url.path.startswith("/api/"):
            route = request.scope.get("route")
            name = getattr(route, "path", request.url.path)
            LATENCY.record_ns(f"api:{request.method} {name}", elapsed_ns)
            LATENCY.record_ns("api", elapsed_ns)
        return response


app.add_middleware(ServerTimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_origin_regex=settings.cors_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Server-Timing"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger.warning("app_error", code=exc.code, message=exc.message, path=str(request.url))
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )


app.include_router(api_router)
app.include_router(ws_router)
