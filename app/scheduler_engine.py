"""APScheduler-based scheduling engine — thin orchestration layer."""

import asyncio
import json
from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db import async_session
from app.repositories.scenario import ScenarioRepository
from app.services.scenario_service import ScenarioService

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


def update_scenario_job(scenario) -> None:
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
            # scenario_service is injected via a module-level reference set at startup
            if _scenario_service is None:
                logger.warning("scenario_service_not_initialized", scenario_id=scenario_id)
                return
            await _scenario_service.execute(scenario_id)
    except asyncio.TimeoutError:
        logger.warning("scenario_execution_timeout", scenario_id=scenario_id)
    except Exception:
        logger.exception("scenario_execution_error", scenario_id=scenario_id)


_scenario_service: Optional[ScenarioService] = None


def set_scenario_service(service: ScenarioService) -> None:
    global _scenario_service
    _scenario_service = service


async def load_scheduler_jobs() -> None:
    """Load enabled schedule-based scenarios from DB on startup."""
    logger.info("loading_scheduler_jobs")
    async with async_session() as session:
        repo = ScenarioRepository(session)
        scenarios = await repo.get_enabled_schedules()
        for scenario in scenarios:
            update_scenario_job(scenario)
    logger.info("scheduler_jobs_loaded")
