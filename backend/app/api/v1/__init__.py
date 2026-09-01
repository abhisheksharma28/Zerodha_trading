from fastapi import APIRouter

from app.api.v1 import audit, backtests, broker, deployments, health, orders, strategies

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(deployments.router)
api_router.include_router(broker.router)
api_router.include_router(audit.router)
api_router.include_router(orders.router)
