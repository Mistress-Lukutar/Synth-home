"""Pydantic request/response models for the ZigbeeHUB WebUI."""

from typing import Optional
from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    port: str = Field(..., min_length=1, description="COM port name (e.g. COM3)")


class CommandRequest(BaseModel):
    action: str = Field(default="toggle", description="Command action: on, off, toggle, level, color")
    params: dict = Field(default_factory=dict, description="Additional command parameters")


class PermitJoinRequest(BaseModel):
    duration: int = Field(default=180, ge=1, le=255, description="Permit join duration in seconds")


class DeviceResponse(BaseModel):
    ieee: str
    name: Optional[str] = None
    endpoint: Optional[int] = None
    online: bool = True


class StatusResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    data: Optional[dict] = None
