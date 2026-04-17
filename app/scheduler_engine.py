"""APScheduler-based scheduling engine."""

import asyncio
import json
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import async_session
from app.models.db_models import Scenario
from app.services.hub_service import get_hub_service
from app.services.sse_manager import sse_manager

logger = structlog.get_logger(__name__)

scheduler: Optional[AsyncIOScheduler] = None


def get_scheduler() -> AsyncIOScheduler:
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": 300,
                "coalesce": True,
                "max_instances": 1,
            }
        )
    return scheduler


def start_scheduler() -> None:
    s = get_scheduler()
    if not s.running:
        s.start()
        logger.info("scheduler_started")


def stop_scheduler() -> None:
    s = get_scheduler()
    if s.running:
        s.shutdown()
        logger.info("scheduler_stopped")


def _day_of_week_map(days_str: str) -> str:
    mapping = {
        "mon": "mon",
        "tue": "tue",
        "wed": "wed",
        "thu": "thu",
        "fri": "fri",
        "sat": "sat",
        "sun": "sun",
    }
    parts = [p.strip().lower() for p in days_str.split(",") if p.strip()]
    valid = [mapping.get(p, p) for p in parts if mapping.get(p, p) in mapping.values()]
    return ",".join(valid) if valid else "*"


def update_scenario_job(scenario: Scenario) -> None:
    s = get_scheduler()
    job_id = f"scenario_{scenario.id}"
    try:
        s.remove_job(job_id)
    except Exception:
        pass
    if not scenario.is_enabled:
        return
    if scenario.trigger_type == "schedule" and scenario.schedule_days is not None:
        day_of_week = _day_of_week_map(scenario.schedule_days)
        trigger = CronTrigger(
            hour=scenario.schedule_hour or 0,
            minute=scenario.schedule_minute or 0,
            day_of_week=day_of_week,
        )
        s.add_job(
            _execute_scenario_wrapper,
            trigger=trigger,
            id=job_id,
            args=[scenario.id],
            replace_existing=True,
        )
    elif scenario.trigger_type == "schedule" and scenario.trigger_config:
        try:
            cfg = json.loads(scenario.trigger_config)
            cron = cfg.get("cron")
            if cron:
                parts = cron.split()
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
                s.add_job(
                    _execute_scenario_wrapper,
                    trigger=trigger,
                    id=job_id,
                    args=[scenario.id],
                    replace_existing=True,
                )
        except Exception:
            pass


def remove_scenario_job(scenario_id: int) -> None:
    s = get_scheduler()
    job_id = f"scenario_{scenario_id}"
    try:
        s.remove_job(job_id)
    except Exception:
        pass


async def _execute_scenario_wrapper(scenario_id: int) -> None:
    try:
        async with asyncio.timeout(30):
            await _execute_scenario(scenario_id)
    except asyncio.TimeoutError:
        logger.warning("scenario_execution_timeout", scenario_id=scenario_id)
    except Exception:
        logger.exception("scenario_execution_error", scenario_id=scenario_id)


def _get_next_run_time(scenario_id: int) -> Optional[str]:
    job = get_scheduler().get_job(f"scenario_{scenario_id}")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


async def _execute_scenario(scenario_id: int) -> None:
    logger.info("executing_scenario", scenario_id=scenario_id)
    async with async_session() as session:
        scenario = await session.get(Scenario, scenario_id)
        if not scenario or not scenario.is_enabled:
            return
        await sse_manager.broadcast(
            "scenario_triggered",
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "next_run_time": _get_next_run_time(scenario.id),
            },
        )
        await _run_scenario_action(scenario)


async def _run_scenario_action(scenario: Scenario) -> None:
    service = get_hub_service()
    if not service.is_connected():
        logger.warning("scenario_skipped_not_connected", scenario_id=scenario.id)
        await sse_manager.broadcast(
            "scenario_skipped",
            {
                "scenario_id": scenario.id,
                "scenario_name": scenario.name,
                "reason": "not_connected",
                "next_run_time": _get_next_run_time(scenario.id),
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
            await service.send_command(ieee, action, params if params else None)
            logger.info("scenario_executed", scenario_id=scenario.id)
            await sse_manager.broadcast(
                "scenario_executed",
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "action": action,
                    "ieee": ieee,
                    "next_run_time": _get_next_run_time(scenario.id),
                },
            )
        except Exception as exc:
            logger.warning("scenario_execution_failed", scenario_id=scenario.id, error=str(exc))
            await sse_manager.broadcast(
                "scenario_execution_failed",
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "error": str(exc),
                    "next_run_time": _get_next_run_time(scenario.id),
                },
            )


async def evaluate_device_event(event_data: dict) -> None:
    """Check scenarios with trigger_type=='device_event' against incoming event."""
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Scenario).where(
                Scenario.is_enabled.is_(True),
                Scenario.trigger_type == "device_event",
            )
        )
        scenarios = result.scalars().all()
        for scenario in scenarios:
            config = {}
            if scenario.trigger_config:
                try:
                    config = json.loads(scenario.trigger_config)
                except Exception:
                    continue
            evt = event_data.get("evt") or event_data.get("event")
            if config.get("event") and config.get("event") != evt:
                continue
            if config.get("ieee"):
                event_ieee = event_data.get("ieee") or event_data.get("ieee_addr")
                if event_ieee != config.get("ieee"):
                    continue
            logger.info("scenario_triggered_by_event", scenario_id=scenario.id, event=evt)
            await sse_manager.broadcast(
                "scenario_triggered",
                {
                    "scenario_id": scenario.id,
                    "scenario_name": scenario.name,
                    "event": evt,
                    "next_run_time": _get_next_run_time(scenario.id),
                },
            )
            await _run_scenario_action(scenario)


async def load_scheduler_jobs() -> None:
    """Load enabled schedule-based scenarios from DB on startup."""
    logger.info("loading_scheduler_jobs")
    async with async_session() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Scenario).where(
                Scenario.is_enabled.is_(True),
                Scenario.trigger_type == "schedule",
            )
        )
        for scenario in result.scalars().all():
            update_scenario_job(scenario)
    logger.info("scheduler_jobs_loaded")
