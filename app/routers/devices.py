"""Devices router: list devices and send commands."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import require_connection, get_db
from app.models.schemas import CommandRequest, CommandResponse, DevicesResponse, RenameRequest, RenameResponse, StatusResponse
from app.repositories.device import DeviceRepository
from app.repositories.device_alias import DeviceAliasRepository
from app.services.hub_service import HubService

router = APIRouter()


@router.get("/api/devices", response_model=DevicesResponse)
async def list_devices(
    service: Annotated[HubService, Depends(require_connection)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Fetch devices from hub (syncs to DB) and return the persisted merged view."""
    await service.fetch_devices()
    repo = DeviceRepository(db)
    devices = await repo.list_with_aliases()
    return {"success": True, "devices": devices}


@router.post("/api/devices/{ieee}/command", status_code=status.HTTP_202_ACCEPTED, response_model=CommandResponse)
async def device_command(
    ieee: str,
    req: CommandRequest,
    service: Annotated[HubService, Depends(require_connection)],
) -> CommandResponse:
    """Send a command to a specific Zigbee device. Returns 202 with correlation_id."""
    params = dict(req.params)
    if req.endpoint is not None:
        params["endpoint"] = req.endpoint
    result = await service.send_command(ieee, req.action, params)
    return CommandResponse(correlation_id=result["correlation_id"], status=result["status"])


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
