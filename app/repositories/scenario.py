"""Scenario repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Scenario
from app.repositories.base import BaseRepository


class ScenarioRepository(BaseRepository[Scenario]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Scenario)

    async def list_ordered(self) -> list[Scenario]:
        result = await self._session.execute(
            select(Scenario).order_by(Scenario.id.desc())
        )
        return list(result.scalars().all())

    async def get_enabled_schedules(self) -> list[Scenario]:
        result = await self._session.execute(
            select(Scenario).where(
                Scenario.is_enabled.is_(True),
                Scenario.trigger_type == "schedule",
            )
        )
        return list(result.scalars().all())

    async def get_enabled_device_events(self) -> list[Scenario]:
        result = await self._session.execute(
            select(Scenario).where(
                Scenario.is_enabled.is_(True),
                Scenario.trigger_type == "device_event",
            )
        )
        return list(result.scalars().all())
