"""Scenario execution business logic — isolated from transport and scheduling."""

import asyncio
import json
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.exceptions import HubConnectionError
from app.models.db_models import Scenario
from app.repositories.scenario import ScenarioRepository
from app.services.event_bus import EventBus
from app.services.hub_service import HubService

logger = structlog.get_logger(__name__)


def _get_next_run_time(scheduler, scenario_id: int) -> Optional[str]:
    job = scheduler.get_job(f"scenario_{scenario_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


class ScenarioService:
    """Handles CRUD-like execution of scenario actions."""

    def __init__(
        self,
        event_bus: EventBus,
        hub_service: HubService,
        scheduler=None,
    ) -> None:
        self._event_bus = event_bus
        self._hub_service = hub_service
        self._scheduler = scheduler

    async def execute(self, scenario_id: int) -> None:
        logger.info("executing_scenario", scenario_id=scenario_id)
        async with async_session() as session:
            scenario = await session.get(Scenario, scenario_id)
            if not scenario or not scenario.is_enabled:
                return
            await self._publish(
                "scenario_triggered",
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "next_run_time": self._next_run(scenario.id),
                },
            )
            await self._run_action(session, scenario)

    async def evaluate_device_event(self, event_data: dict) -> None:
        """Check scenarios with trigger_type=='device_event' against incoming event."""
        async with async_session() as session:
            repo = ScenarioRepository(session)
            scenarios = await repo.get_enabled_device_events()
            for scenario in scenarios:
                if not self._match_event(scenario, event_data):
                    continue
                logger.info(
                    "scenario_triggered_by_event",
                    scenario_id=scenario.id,
                    event=event_data.get("event"),
                )
                await self._publish(
                    "scenario_triggered",
                    {
                        "scenario_id": scenario.id,
                        "scenario_name": scenario.name,
                        "event": event_data.get("event"),
                        "next_run_time": self._next_run(scenario.id),
                    },
                )
                await self._run_action(session, scenario)

    def _match_event(self, scenario: Scenario, event_data: dict) -> bool:
        config = {}
        if scenario.trigger_config:
            try:
                config = json.loads(scenario.trigger_config)
            except Exception:
                return False
        evt = event_data.get("evt") or event_data.get("event")
        if config.get("event") and config.get("event") != evt:
            return False
        if config.get("ieee"):
            event_ieee = event_data.get("ieee") or event_data.get("ieee_addr")
            if event_ieee != config.get("ieee"):
                return False
        return True

    async def _run_action(self, session: AsyncSession, scenario: Scenario) -> None:
        if not self._hub_service.is_connected():
            logger.warning("scenario_skipped_not_connected", scenario_id=scenario.id)
            await self._publish(
                "scenario_skipped",
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "reason": "not_connected",
                    "next_run_time": self._next_run(scenario.id),
                },
            )
            return

        config = {}
        if scenario.action_config:
            try:
                config = json.loads(scenario.action_config)
            except Exception:
                pass

        if scenario.action_type == "command":
            ieee = config.get("ieee", "")
            action = config.get("action", "toggle")
            params = config.get("params", {})
            try:
                await self._hub_service.send_command(
                    ieee, action, params if params else None
                )
                logger.info("scenario_executed", scenario_id=scenario.id)
                await self._publish(
                    "scenario_executed",
                    {
                        "scenario_id": scenario.id,
                        "scenario_name": scenario.name,
                        "action": action,
                        "ieee": ieee,
                        "next_run_time": self._next_run(scenario.id),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "scenario_execution_failed", scenario_id=scenario.id, error=str(exc)
                )
                await self._publish(
                    "scenario_execution_failed",
                    {
                        "scenario_id": scenario.id,
                        "scenario_name": scenario.name,
                        "error": str(exc),
                        "next_run_time": self._next_run(scenario.id),
                    },
                )

    async def _publish(self, event_type: str, payload: dict) -> None:
        await self._event_bus.publish(event_type, payload)

    def _next_run(self, scenario_id: int) -> Optional[str]:
        if self._scheduler is None:
            return None
        return _get_next_run_time(self._scheduler, scenario_id)
