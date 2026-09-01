from sqlalchemy import select

from app.models.broker_session import BrokerSession
from app.repositories.base import BaseRepository


class BrokerSessionRepository(BaseRepository[BrokerSession]):
    model = BrokerSession

    def get_latest(self, broker: str = "zerodha") -> BrokerSession | None:
        stmt = (
            select(BrokerSession)
            .where(BrokerSession.broker == broker)
            .order_by(BrokerSession.created_at.desc())
            .limit(1)
        )
        return self.db.execute(stmt).scalars().first()
