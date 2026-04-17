"""Devices router: list devices and send commands."""

from typing import Annotated, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import require_connection
from app.db import async_session
from app.models.db_models import DeviceAlias
from app.models.schemas import CommandRequest, StatusResponse
from app.services.hub_service import HubService

router = APIRouter()


async def _apply_aliases(devices: List[dict]) -> List[dict]:
    if not devices:
        return devices
    async with async_session() as session:
        result = await session.execute(
            select(DeviceAlias).where(
                DeviceAlias.ieee_addr.in_([d["ieee"] for d in devices])
            )
        )
        aliases = {a.ieee_addr: a.name for a in result.scalars().all()}
    for d in devices:
        if d["ieee"] in aliases:
            d["name"] = aliases[d["ieee"]]
    return devices


@router.get("/api/devices")
async def list_devices(
    service: Annotated[HubService, Depends(require_connection)],
) -> dict:
    """Fetch and return the list of Zigbee devices."""
    devices = await service.fetch_devices()
    devices = await _apply_aliases(devices)
    return {"success": True, "devices": devices}


@router.post("/api/devices/{ieee}/command")
async def device_command(
    ieee: str,
    req: CommandRequest,
    service: Annotated[HubService, Depends(require_connection)],
) -> StatusResponse:
    """Send a command to a specific Zigbee device."""
    result = await service.send_command(ieee, req.action, req.params)
    return StatusResponse(success=True, data=result)


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1)


@router.patch("/api/devices/{ieee}/rename")
async def rename_device(
    ieee: str,
    req: RenameRequest,
) -> dict:
    async with async_session() as session:
        alias = await session.get(DeviceAlias, ieee)
        if alias:
            alias.name = req.name
        else:
            alias = DeviceAlias(ieee_addr=ieee, name=req.name)
            session.add(alias)
        await session.commit()
    return {"success": True, "ieee": ieee, "name": req.name}
