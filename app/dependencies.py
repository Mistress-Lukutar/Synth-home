"""FastAPI dependency injection helpers."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.services.event_bus import EventBus
from app.services.hub_service import HubService
from app.services.scenario_service import ScenarioService


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


def get_event_bus(request: Request) -> EventBus:
    """Retrieve the global EventBus from application state."""
    return request.app.state.event_bus


def get_hub_service(request: Request) -> HubService:
    """Retrieve the shared HubService from application state."""
    return request.app.state.hub_service


def get_scenario_service(request: Request) -> ScenarioService:
    """Retrieve the shared ScenarioService from application state."""
    return request.app.state.scenario_service


def require_connection(service: Annotated[HubService, Depends(get_hub_service)]) -> HubService:
    """Dependency that raises HTTP 400 if the hub is not connected."""
    if not service.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to hub")
    return service
