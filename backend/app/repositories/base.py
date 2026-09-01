import uuid
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, id_: uuid.UUID | str) -> ModelT | None:
        return self.db.get(self.model, id_)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        # Every concrete model used with this base has a created_at column
        # (via TimestampMixin or its own column) — not expressible on the
        # ModelT bound without a protocol, hence the ignore.
        order_col = self.model.created_at  # type: ignore[attr-defined]
        stmt = select(self.model).order_by(order_col.desc()).limit(limit).offset(offset)
        return list(self.db.execute(stmt).scalars().all())

    def add(self, obj: ModelT) -> ModelT:
        self.db.add(obj)
        self.db.flush()
        return obj
