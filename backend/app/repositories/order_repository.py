from sqlalchemy import select

from app.models.order import Order, Trade
from app.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    def list_for_deployment(self, deployment_id, *, limit: int = 200) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.deployment_id == deployment_id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def list_for_backtest(self, backtest_id, *, limit: int = 5000) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.backtest_id == backtest_id)
            .order_by(Order.created_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


class TradeRepository(BaseRepository[Trade]):
    model = Trade
