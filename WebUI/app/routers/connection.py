"""Connection router: COM-port discovery and connect/disconnect."""

import asyncio

import serial.tools.list_ports
from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.db import async_session
from app.models.db_models import SystemSetting
from app.models.schemas import ConnectRequest, ConnectionStatusResponse, PortsResponse, StatusResponse
from app.dependencies import get_hub_service
from app.services.hub_service import HubService

router = APIRouter()


async def _save_last_port(port: str) -> None:
    async with async_session() as db:
        result = await db.execute(
            select(SystemSetting).where(SystemSetting.key == "last_connected_port")
        )
        setting = result.scalar_one_or_none()
        if setting:
            setting.value = port
        else:
            db.add(SystemSetting(key="last_connected_port", value=port))
        await db.commit()


@router.get("/api/ports", response_model=PortsResponse)
async def list_ports() -> dict:
    """List available COM ports."""
    ports = await asyncio.to_thread(
        lambda: [port.device for port in serial.tools.list_ports.comports()]
    )
    return {"ports": ports}


@router.post("/api/connect")
async def connect_port(
    req: ConnectRequest,
    service: HubService = Depends(get_hub_service),
) -> StatusResponse:
    """Connect to the hub on the selected COM port."""
    ok = await service.connect(req.port)
    if ok:
        await _save_last_port(req.port)
        return StatusResponse(success=True, data={"port": req.port})
    return StatusResponse(success=False, error=f"Failed to connect to {req.port}")


@router.post("/api/disconnect")
async def disconnect_port(
    service: HubService = Depends(get_hub_service),
) -> StatusResponse:
    """Disconnect from the hub."""
    await service.disconnect()
    return StatusResponse(success=True)


@router.get("/api/status", response_model=ConnectionStatusResponse)
async def get_status(
    service: HubService = Depends(get_hub_service),
) -> dict:
    """Return current hub connection status."""
    return {
        "connected": service.is_connected(),
        "port": service.get_port(),
    }


@router.post("/api/debug/hub-raw")
async def debug_hub_raw(
    payload: dict,
    service: HubService = Depends(get_hub_service),
) -> StatusResponse:
    """Send a raw JSON payload directly to the hub serial port."""
    if not service.is_connected():
        return StatusResponse(success=False, error="Hub not connected")
    await service._client.send_raw(payload)
    return StatusResponse(success=True)
