"""Panel router: CRUD for dashboard panels."""

from typing import Annotated, Any, List

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_panel_state_service, get_graph_executor
from app.models.db_models import Panel
from app.models.panel_schemas import (
    PanelCreate,
    PanelOut,
    PanelUpdate,
    ReorderItem,
    PanelExport,
)
from app.models.schemas import StatusResponse
from app.repositories.panel import PanelRepository
from app.repositories.graph import NodeGraphRepository

router = APIRouter()


@router.get("/api/panels", response_model=List[PanelOut])
async def list_panels(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> List[Panel]:
    repo = PanelRepository(db)
    return await repo.list_ordered()


@router.post("/api/panels", response_model=PanelOut)
async def create_panel(
    req: PanelCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Panel:
    panel = Panel(
        name=req.name,
        is_enabled=req.is_enabled,
        sort_order=req.sort_order,
        layout=req.layout.model_dump(),
    )
    db.add(panel)
    await db.commit()
    await db.refresh(panel)
    # Create empty graph automatically
    graph_repo = NodeGraphRepository(db)
    await graph_repo.create_for_panel(panel.id)
    await db.commit()
    return panel


@router.patch("/api/panels/reorder", response_model=StatusResponse)
async def reorder_panels(
    items: Annotated[List[ReorderItem], Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    for item in items:
        panel = await db.get(Panel, item.id)
        if panel:
            panel.sort_order = item.sort_order
    await db.commit()
    return StatusResponse(success=True)


@router.patch("/api/panels/{panel_id}", response_model=PanelOut)
async def update_panel(
    panel_id: int,
    req: PanelUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> Panel:
    panel = await db.get(Panel, panel_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    for key, value in req.model_dump(exclude_unset=True).items():
        if key == "layout" and value is not None:
            value = value.model_dump()
        setattr(panel, key, value)
    await db.commit()
    await db.refresh(panel)

    # Re-register triggers when panel is enabled/disabled or otherwise changed
    panel_trigger_service = request.app.state.panel_trigger_service
    await panel_trigger_service.update_panel(panel_id, db)

    return panel


@router.delete("/api/panels/{panel_id}", response_model=StatusResponse)
async def delete_panel(
    panel_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
) -> StatusResponse:
    panel = await db.get(Panel, panel_id)
    if panel:
        # Remove triggers before deleting the panel
        panel_trigger_service = request.app.state.panel_trigger_service
        panel_trigger_service.remove_panel(panel_id)

        await db.delete(panel)
        await db.commit()
    return StatusResponse(success=True)


@router.get("/api/panels/{panel_id}/export")
async def export_panel(
    panel_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Export panel with its graph as JSON (placeholder for Phase 8)."""
    panel = await db.get(Panel, panel_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    # TODO: serialize graph when graph router is fully wired
    return {
        "_format": "zigbeehub_panel",
        "_version": "1.0.0",
        "panel": {
            "name": panel.name,
            "is_enabled": panel.is_enabled,
            "sort_order": panel.sort_order,
            "layout": panel.layout or {},
        },
    }


class PanelInputRequest(BaseModel):
    node_id: str
    value: Any


@router.post("/api/panels/{panel_id}/input")
async def set_panel_input(
    panel_id: int,
    req: PanelInputRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    panel_state=Depends(get_panel_state_service),
    graph_executor=Depends(get_graph_executor),
) -> dict:
    """Receive a value from a panel UI control, update state, and run the graph."""
    panel = await db.get(Panel, panel_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")

    panel_state.set_input_value(panel_id, req.node_id, req.value)
    result = await graph_executor.run(panel_id, db, triggered_node_id=req.node_id)
    return {"success": True, "execution": result}


@router.get("/api/panels/{panel_id}/state")
async def get_panel_state(
    panel_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    panel_state=Depends(get_panel_state_service),
) -> dict:
    """Return the current runtime state of a panel (input + output values)."""
    panel = await db.get(Panel, panel_id)
    if not panel:
        raise HTTPException(status_code=404, detail="Panel not found")
    return {
        "panel_id": panel_id,
        "inputs": panel_state.get_all_inputs(panel_id),
    }
