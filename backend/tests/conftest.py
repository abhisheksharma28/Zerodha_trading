import os
import uuid

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://trading:trading@localhost:5432/trading_platform_test"
)
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-not-for-production-use-0000000000")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 ensure all models are registered on Base.metadata
from app.config import get_settings
from app.db.base import Base


@pytest.fixture(scope="session", autouse=True)
def _create_test_database():
    settings = get_settings()
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    db_name = settings.database_url.rsplit("/", 1)[1]
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()
    yield


@pytest.fixture()
def db() -> Session:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    connection = engine.connect()
    transaction = connection.begin()
    SessionLocal = sessionmaker(bind=connection)
    session = SessionLocal()

    yield session

    session.close()
    transaction.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture()
def sample_strategy_source() -> str:
    return (
        "from app.strategies.base import BaseStrategy\n\n"
        "class Strategy(BaseStrategy):\n"
        "    def on_bar(self, bar):\n"
        "        pass\n"
    )


@pytest.fixture()
def new_uuid() -> uuid.UUID:
    return uuid.uuid4()
