"""Connection router: COM-port discovery and connect/disconnect."""

import asyncio

import serial.tools.list_ports
from fastapi import APIRouter, Depends

from app.models.schemas import ConnectRequest, ConnectionStatusResponse, PortsResponse, StatusResponse
from app.dependencies import get_hub_service
from app.services.hub_service import HubService

router = APIRouter()


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
