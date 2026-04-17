"""Scenario router: CRUD and manual trigger for rule-based scenarios."""

import asyncio
from typing import Annotated, List

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_scenario_service
from app.models.db_models import Scenario
from app.models.schemas import StatusResponse
from app.repositories.scenario import ScenarioRepository
from app.scheduler_engine import (
    update_scenario_job,
    remove_scenario_job,
)
from app.services.scenario_service import ScenarioService

router = APIRouter()


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1)
    trigger_type: str = Field(default="manual")
    trigger_data: dict | None = None
    action_type: str = Field(default="command")
    action_data: dict | None = None
    is_enabled: bool = True
    sort_order: int = 0


class ScenarioUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    trigger_data: dict | None = None
    action_type: str | None = None
    action_data: dict | None = None
    is_enabled: bool | None = None
    sort_order: int | None = None


class ScenarioOut(BaseModel):
    id: int
    name: str
    is_enabled: bool
    sort_order: int
    trigger_type: str
    trigger_data: dict | None
    action_type: str
    action_data: dict | None

    model_config = {"from_attributes": True}


@router.get("/api/scenarios", response_model=List[ScenarioOut])
async def list_scenarios(db: Annotated[AsyncSession, Depends(get_db)]) -> List[Scenario]:
    repo = ScenarioRepository(db)
    return await repo.list_ordered()


@router.post("/api/scenarios", response_model=ScenarioOut)
async def create_scenario(
    req: ScenarioCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Scenario:
    scenario = Scenario(
        name=req.name,
        trigger_type=req.trigger_type,
        trigger_data=req.trigger_data,
        action_type=req.action_type,
        action_data=req.action_data,
        is_enabled=req.is_enabled,
        sort_order=req.sort_order,
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    if scenario.is_enabled and scenario.trigger_type == "schedule":
        await asyncio.to_thread(update_scenario_job, scenario)
    return scenario


class ReorderItem(BaseModel):
    id: int
    sort_order: int


@router.patch("/api/scenarios/reorder", response_model=StatusResponse)
async def reorder_scenarios(
    items: Annotated[List[ReorderItem], Body()],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    for item in items:
        scenario = await db.get(Scenario, item.id)
        if scenario:
            scenario.sort_order = item.sort_order
    await db.commit()
    return StatusResponse(success=True)


@router.patch("/api/scenarios/{scenario_id}", response_model=ScenarioOut)
async def update_scenario(
    scenario_id: int,
    req: ScenarioUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Scenario:
    scenario = await db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    for key, value in req.model_dump(exclude_unset=True).items():
        setattr(scenario, key, value)
    await db.commit()
    await db.refresh(scenario)
    await asyncio.to_thread(remove_scenario_job, scenario.id)
    if scenario.is_enabled and scenario.trigger_type == "schedule":
        await asyncio.to_thread(update_scenario_job, scenario)
    return scenario


@router.delete("/api/scenarios/{scenario_id}", response_model=StatusResponse)
async def delete_scenario(
    scenario_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    scenario = await db.get(Scenario, scenario_id)
    if scenario:
        await db.delete(scenario)
        await db.commit()
    await asyncio.to_thread(remove_scenario_job, scenario_id)
    return StatusResponse(success=True)


@router.post("/api/scenarios/{scenario_id}/trigger", response_model=StatusResponse)
async def trigger_scenario(
    scenario_id: int,
    service: Annotated[ScenarioService, Depends(get_scenario_service)],
) -> StatusResponse:
    await service.execute(scenario_id)
    return StatusResponse(success=True)
