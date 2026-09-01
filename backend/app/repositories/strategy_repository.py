from app.models.strategy import Strategy, StrategyVersion
from app.repositories.base import BaseRepository


class StrategyRepository(BaseRepository[Strategy]):
    model = Strategy


class StrategyVersionRepository(BaseRepository[StrategyVersion]):
    model = StrategyVersion

    def next_version_number(self, strategy_id) -> int:
        from sqlalchemy import func, select

        stmt = select(func.coalesce(func.max(StrategyVersion.version_number), 0)).where(
            StrategyVersion.strategy_id == strategy_id
        )
        return self.db.execute(stmt).scalar_one() + 1
