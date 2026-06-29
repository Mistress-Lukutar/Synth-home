"""APScheduler-based scheduling engine — thin orchestration layer."""

from typing import Optional

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

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
