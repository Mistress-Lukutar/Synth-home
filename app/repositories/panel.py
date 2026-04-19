"""Panel repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Panel
from app.repositories.base import BaseRepository


class PanelRepository(BaseRepository[Panel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Panel)

    async def list_ordered(self) -> list[Panel]:
        result = await self._session.execute(
            select(Panel).order_by(Panel.sort_order.asc(), Panel.id.asc())
        )
        return list(result.scalars().all())
