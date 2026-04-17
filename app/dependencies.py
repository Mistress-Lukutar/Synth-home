"""FastAPI dependency injection helpers."""

from typing import Annotated

from fastapi import Depends, HTTPException

from app.services.hub_service import HubService, get_hub_service


def require_connection(service: Annotated[HubService, Depends(get_hub_service)]) -> HubService:
    """Dependency that raises HTTP 400 if the hub is not connected."""
    if not service.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to hub")
    return service
