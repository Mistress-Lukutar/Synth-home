"""DeviceAlias repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import DeviceAlias
from app.repositories.base import BaseRepository


class DeviceAliasRepository(BaseRepository[DeviceAlias]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DeviceAlias)

    async def get_by_ieee(self, ieee_addr: str) -> DeviceAlias | None:
        return await self._session.get(DeviceAlias, ieee_addr)

    async def get_many_by_ieee(self, ieee_addrs: list[str]) -> dict[str, str]:
        """Return a mapping ieee -> name for the given addresses."""
        if not ieee_addrs:
            return {}
        result = await self._session.execute(
            select(DeviceAlias).where(DeviceAlias.ieee_addr.in_(ieee_addrs))
        )
        return {a.ieee_addr: a.name for a in result.scalars().all()}

    async def upsert(self, ieee_addr: str, name: str) -> DeviceAlias:
        alias = await self.get_by_ieee(ieee_addr)
        if alias:
            alias.name = name
        else:
            alias = DeviceAlias(ieee_addr=ieee_addr, name=name)
            self.add(alias)
        return alias
