from fastapi import APIRouter

from app.api.v1 import (
    adaptive_options,
    arbitrage,
    audit,
    backtests,
    broker,
    chinese_transformer,
    deployments,
    health,
    instruments,
    leaderboard,
    market,
    market_scanner,
    monitoring,
    options_strategies,
    orderflow,
    orders,
    stocks,
    strategies,
    strategy_library,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(adaptive_options.router)
api_router.include_router(arbitrage.router)
api_router.include_router(chinese_transformer.router)
api_router.include_router(strategies.router)
api_router.include_router(strategy_library.router)
api_router.include_router(options_strategies.router)
api_router.include_router(backtests.router)
api_router.include_router(deployments.router)
api_router.include_router(broker.router)
api_router.include_router(instruments.router)
api_router.include_router(market.router)
api_router.include_router(market_scanner.router)
api_router.include_router(leaderboard.router)
api_router.include_router(orderflow.router)
api_router.include_router(monitoring.router)
api_router.include_router(audit.router)
api_router.include_router(orders.router)
api_router.include_router(stocks.router)
