"""Device repository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Device
from app.repositories.base import BaseRepository


class DeviceRepository(BaseRepository[Device]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Device)

    async def get_by_ieee(self, ieee_addr: str) -> Device | None:
        return await self._session.get(Device, ieee_addr)

    async def upsert(self, ieee_addr: str, **kwargs) -> Device:
        device = await self.get_by_ieee(ieee_addr)
        if device:
            for key, value in kwargs.items():
                setattr(device, key, value)
        else:
            device = Device(ieee_addr=ieee_addr, **kwargs)
            self.add(device)
        return device

    async def list_with_aliases(self) -> list[dict]:
        """Return devices joined with their aliases."""
        from app.models.db_models import DeviceAlias

        result = await self._session.execute(
            select(Device, DeviceAlias.name)
            .outerjoin(DeviceAlias, Device.ieee_addr == DeviceAlias.ieee_addr)
        )
        rows = []
        for device, alias_name in result.all():
            rows.append(
                {
                    "ieee": device.ieee_addr,
                    "name": alias_name or "Zigbee Device",
                    "network_addr": device.network_addr,
                    "endpoint": device.endpoint,
                    "supports_hs": device.supports_hs,
                    "supports_xy": device.supports_xy,
                    "supports_ct": device.supports_ct,
                    "online": device.online,
                    "last_command": device.last_command,
                }
            )
        return rows
