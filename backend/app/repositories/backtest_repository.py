from app.models.backtest import Backtest
from app.repositories.base import BaseRepository


class BacktestRepository(BaseRepository[Backtest]):
    model = Backtest
