from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings

settings = get_settings()

# connect_timeout stops a boot from hanging forever if the database is
# unreachable (e.g. a paused Supabase project or a blocked egress) — it
# surfaces a clear OperationalError instead.
_connect_args = {}
if settings.database_url.startswith(("postgresql", "postgres")):
    _connect_args["connect_timeout"] = 10

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    future=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, future=True
)
