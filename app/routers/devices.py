"""Devices router: list devices and send commands."""

from typing import Annotated, List

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import require_connection, get_db
from app.models.schemas import CommandRequest, DevicesResponse, RenameRequest, RenameResponse, StatusResponse
from app.repositories.device_alias import DeviceAliasRepository
from app.services.hub_service import HubService

router = APIRouter()


async def _apply_aliases(devices: List[dict], db: AsyncSession) -> List[dict]:
    if not devices:
        return devices
    repo = DeviceAliasRepository(db)
    aliases = await repo.get_many_by_ieee([d["ieee"] for d in devices])
    for d in devices:
        if d["ieee"] in aliases:
            d["name"] = aliases[d["ieee"]]
    return devices


@router.get("/api/devices", response_model=DevicesResponse)
async def list_devices(
    service: Annotated[HubService, Depends(require_connection)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Fetch and return the list of Zigbee devices."""
    devices = await service.fetch_devices()
    devices = await _apply_aliases(devices, db)
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


@router.patch("/api/devices/{ieee}/rename", response_model=RenameResponse)
async def rename_device(
    ieee: str,
    req: RenameRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    repo = DeviceAliasRepository(db)
    await repo.upsert(ieee, req.name)
    await db.commit()
    return {"success": True, "ieee": ieee, "name": req.name}
