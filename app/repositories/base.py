"""Base repository with common CRUD operations."""

from typing import Generic, TypeVar, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Generic base repository implementing common patterns."""

    def __init__(self, session: AsyncSession, model_cls: type[ModelT]) -> None:
        self._session = session
        self._model_cls = model_cls

    async def get(self, pk: int) -> ModelT | None:
        return await self._session.get(self._model_cls, pk)

    async def get_all(self) -> Sequence[ModelT]:
        result = await self._session.execute(select(self._model_cls))
        return result.scalars().all()

    def add(self, obj: ModelT) -> None:
        self._session.add(obj)

    async def delete(self, obj: ModelT) -> None:
        await self._session.delete(obj)
