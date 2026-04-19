"""FastAPI dependency injection helpers."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
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


def get_panel_state_service(request: Request):
    """Retrieve the PanelStateService from application state."""
    return request.app.state.panel_state_service


def get_graph_executor(request: Request):
    """Retrieve the GraphExecutor from application state."""
    return request.app.state.graph_executor


def get_panel_trigger_service(request: Request):
    """Retrieve the PanelTriggerService from application state."""
    return request.app.state.panel_trigger_service


def require_connection(service: Annotated[HubService, Depends(get_hub_service)]) -> HubService:
    """Dependency that raises HTTP 400 if the hub is not connected."""
    if not service.is_connected():
        raise HTTPException(status_code=400, detail="Not connected to hub")
    return service


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    """Reject request if an API key is configured and the header is missing or invalid."""
    settings = get_settings()
    expected = settings.api_key
    if expected is None:
        return
    if not api_key or api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
