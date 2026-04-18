"""Devices router: list devices and send commands."""

from typing import Annotated, List

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import require_connection, get_db
from app.models.schemas import CommandRequest, CommandResponse, DevicesResponse, ReadAttrBatchItem, ReadAttrRequest, RenameRequest, RenameResponse, StatusResponse
from app.repositories.device import DeviceRepository
from app.repositories.device_alias import DeviceAliasRepository
from app.services.hub_service import HubService

router = APIRouter()


@router.get("/api/devices", response_model=DevicesResponse)
async def list_devices(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return cached devices from DB (fast, no hub call)."""
    repo = DeviceRepository(db)
    devices = await repo.list_with_aliases()
    import structlog
    logger = structlog.get_logger(__name__)
    for d in devices:
        logger.info(
            "api_devices_response_item",
            ieee=d["ieee"],
            endpoint_count=len(d.get("endpoints") or []),
            endpoints=d.get("endpoints"),
        )
    return {"success": True, "devices": devices}


@router.post("/api/devices/refresh", response_model=DevicesResponse)
async def refresh_devices(
    service: Annotated[HubService, Depends(require_connection)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Force refresh device list from hub and return updated devices."""
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


@router.post("/api/devices/{ieee}/read-attr", status_code=status.HTTP_202_ACCEPTED, response_model=CommandResponse)
async def read_device_attr(
    ieee: str,
    req: ReadAttrRequest,
    service: Annotated[HubService, Depends(require_connection)],
) -> CommandResponse:
    """Read a Zigbee cluster attribute from a device."""
    result = await service.read_attr(ieee, req.endpoint, req.cluster, req.attribute)
    return CommandResponse(correlation_id=result["correlation_id"], status=result["status"])


@router.post("/api/devices/read-attr-batch", response_model=List[CommandResponse])
async def read_attr_batch(
    items: List[ReadAttrBatchItem],
    service: Annotated[HubService, Depends(require_connection)],
) -> List[CommandResponse]:
    """Batch read attributes from multiple devices/endpoints in one request."""
    results: List[CommandResponse] = []
    for item in items:
        result = await service.read_attr(item.ieee, item.endpoint, item.cluster, item.attribute)
        results.append(CommandResponse(correlation_id=result["correlation_id"], status=result["status"]))
    return results


@router.delete("/api/devices/{ieee}", response_model=StatusResponse)
async def delete_device(
    ieee: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    """Remove a device and its alias from the database."""
    repo = DeviceRepository(db)
    deleted = await repo.delete(ieee)
    if deleted:
        alias_repo = DeviceAliasRepository(db)
        alias = await alias_repo.get_by_ieee(ieee)
        if alias:
            await db.delete(alias)
        await db.commit()
        return StatusResponse(success=True)
    return StatusResponse(success=False, error="Device not found")
