"""Scenario router: CRUD and manual trigger for rule-based scenarios."""

from typing import Annotated, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.db_models import Scenario
from app.scheduler_engine import (
    update_scenario_job,
    remove_scenario_job,
    _execute_scenario,
)

router = APIRouter()


async def get_db() -> AsyncSession:
    async with async_session() as session:
        yield session


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1)
    trigger_type: str = Field(default="manual")
    trigger_config: str | None = None
    action_type: str = Field(default="command")
    action_config: str | None = None
    schedule_days: str | None = None
    schedule_hour: int | None = Field(default=None, ge=0, le=23)
    schedule_minute: int | None = Field(default=None, ge=0, le=59)
    is_enabled: bool = True


class ScenarioUpdate(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    trigger_config: str | None = None
    action_type: str | None = None
    action_config: str | None = None
    schedule_days: str | None = None
    schedule_hour: int | None = Field(default=None, ge=0, le=23)
    schedule_minute: int | None = Field(default=None, ge=0, le=59)
    is_enabled: bool | None = None


class ScenarioOut(BaseModel):
    id: int
    name: str
    is_enabled: bool
    trigger_type: str
    trigger_config: str | None
    action_type: str
    action_config: str | None
    schedule_days: str | None
    schedule_hour: int | None
    schedule_minute: int | None

    class Config:
        from_attributes = True


@router.get("/api/scenarios", response_model=List[ScenarioOut])
async def list_scenarios(db: Annotated[AsyncSession, Depends(get_db)]) -> List[Scenario]:
    result = await db.execute(select(Scenario).order_by(Scenario.id.desc()))
    return list(result.scalars().all())


@router.post("/api/scenarios", response_model=ScenarioOut)
async def create_scenario(
    req: ScenarioCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Scenario:
    scenario = Scenario(
        name=req.name,
        trigger_type=req.trigger_type,
        trigger_config=req.trigger_config,
        action_type=req.action_type,
        action_config=req.action_config,
        schedule_days=req.schedule_days,
        schedule_hour=req.schedule_hour,
        schedule_minute=req.schedule_minute,
        is_enabled=req.is_enabled,
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    if scenario.is_enabled and scenario.trigger_type == "schedule":
        update_scenario_job(scenario)
    return scenario


@router.patch("/api/scenarios/{scenario_id}", response_model=ScenarioOut)
async def update_scenario(
    scenario_id: int,
    req: ScenarioUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Scenario:
    scenario = await db.get(Scenario, scenario_id)
    if not scenario:
        raise Exception("Scenario not found")
    for key, value in req.model_dump(exclude_unset=True).items():
        setattr(scenario, key, value)
    await db.commit()
    await db.refresh(scenario)
    remove_scenario_job(scenario.id)
    if scenario.is_enabled and scenario.trigger_type == "schedule":
        update_scenario_job(scenario)
    return scenario


@router.delete("/api/scenarios/{scenario_id}")
async def delete_scenario(
    scenario_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    scenario = await db.get(Scenario, scenario_id)
    if scenario:
        await db.delete(scenario)
        await db.commit()
    remove_scenario_job(scenario_id)
    return {"success": True}


@router.post("/api/scenarios/{scenario_id}/trigger")
async def trigger_scenario(
    scenario_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    scenario = await db.get(Scenario, scenario_id)
    if not scenario:
        return {"success": False, "error": "Scenario not found"}
    await _execute_scenario(scenario.id)
    return {"success": True}
