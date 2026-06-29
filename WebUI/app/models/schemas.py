"""Pydantic request/response models for the ZigbeeHUB WebUI."""

from typing import List, Optional
from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    port: str = Field(..., min_length=1, description="COM port name (e.g. COM3)")


class CommandRequest(BaseModel):
    action: str = Field(default="toggle", description="Command action: on, off, toggle, level, color")
    endpoint: Optional[int] = Field(default=None, description="Target endpoint ID (auto-selected if omitted)")
    params: dict = Field(default_factory=dict, description="Additional command parameters")


class PermitJoinRequest(BaseModel):
    duration: int = Field(default=180, ge=1, le=255, description="Permit join duration in seconds")


class RenameRequest(BaseModel):
    name: str = Field(..., min_length=1)


class DeviceResponse(BaseModel):
    ieee: str
    name: Optional[str] = None
    endpoints: Optional[list] = None
    state: Optional[dict] = None
    online: bool = True


class PortsResponse(BaseModel):
    ports: List[str]


class ConnectionStatusResponse(BaseModel):
    connected: bool
    port: Optional[str] = None


class DevicesResponse(BaseModel):
    success: bool
    devices: List[DeviceResponse]


class RenameResponse(BaseModel):
    success: bool
    ieee: str
    name: str


class ReadAttrRequest(BaseModel):
    endpoint: Optional[int] = None
    cluster: str = Field(..., description="Cluster ID in hex, e.g. 0x0006")
    attribute: str = Field(..., description="Attribute ID in hex, e.g. 0x0000")


class ReadAttrBatchItem(BaseModel):
    ieee: str
    endpoint: Optional[int] = None
    cluster: str
    attribute: str


class CommandResponse(BaseModel):
    correlation_id: str
    status: str = "pending"


class StatusResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    data: Optional[dict] = None
