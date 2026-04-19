"""Panel trigger service — manages APScheduler jobs and EventBus subscriptions
for trigger_* nodes inside panel graphs.

Whenever a panel graph is saved, enabled, or deleted, this service re-scans the
graph and registers / unregisters the corresponding runtime triggers.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session
from app.models.db_models import GraphNode, Panel
from app.repositories.graph import GraphNodeRepository, NodeGraphRepository
from app.services.event_bus import EventBus
from app.services.graph_executor import GraphExecutor

logger = structlog.get_logger(__name__)

EventHandlerInfo = tuple[str, Callable[[dict[str, Any]], Any]]


class PanelTriggerService:
    """Lifecycle manager for panel trigger nodes.

    Keeps track of APScheduler job IDs and EventBus handler references per
    panel so they can be cleanly removed when the panel or its graph changes.
    """

    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        graph_executor: GraphExecutor,
        event_bus: EventBus,
    ) -> None:
        self._scheduler = scheduler
        self._graph_executor = graph_executor
        self._event_bus = event_bus
        self._panel_jobs: dict[int, list[str]] = {}
        self._panel_handlers: dict[int, list[EventHandlerInfo]] = {}

    async def load_all(self, db: AsyncSession) -> None:
        """Scan all enabled panels and register their triggers (used at startup)."""
        result = await db.execute(select(Panel).where(Panel.is_enabled.is_(True)))
        panels = result.scalars().all()
        for panel in panels:
            await self._register_for_panel(panel.id, db)
        logger.info("panel_triggers_loaded", count=len(panels))

    async def update_panel(self, panel_id: int, db: AsyncSession) -> None:
        """Re-register triggers after a graph change or panel enable/disable."""
        self._unregister_panel(panel_id)
        panel = await db.get(Panel, panel_id)
        if panel is None or not panel.is_enabled:
            return
        await self._register_for_panel(panel_id, db)

    def remove_panel(self, panel_id: int) -> None:
        """Remove all triggers for a panel (called on panel deletion)."""
        self._unregister_panel(panel_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _register_for_panel(self, panel_id: int, db: AsyncSession) -> None:
        graph_repo = NodeGraphRepository(db)
        graph = await graph_repo.get_by_panel_id(panel_id)
        if graph is None:
            return

        node_repo = GraphNodeRepository(db)
        nodes = await node_repo.get_for_graph(graph.id)
        for node in nodes:
            if node.type == "trigger_schedule":
                job_id = self._register_schedule_trigger(panel_id, node)
                if job_id:
                    self._panel_jobs.setdefault(panel_id, []).append(job_id)
            elif node.type == "trigger_device_event":
                handler_info = self._register_device_event_trigger(panel_id, node)
                if handler_info:
                    self._panel_handlers.setdefault(panel_id, []).append(handler_info)

    def _unregister_panel(self, panel_id: int) -> None:
        for job_id in self._panel_jobs.pop(panel_id, []):
            try:
                self._scheduler.remove_job(job_id)
                logger.debug("panel_trigger_job_removed", panel_id=panel_id, job_id=job_id)
            except Exception:
                pass

        for event_type, handler in self._panel_handlers.pop(panel_id, []):
            try:
                self._event_bus.unsubscribe(event_type, handler)
                logger.debug("panel_trigger_handler_removed", panel_id=panel_id, event=event_type)
            except Exception:
                pass

    def _register_schedule_trigger(self, panel_id: int, node: GraphNode) -> str | None:
        cron_str = "0 8 * * *"
        if node.data:
            cron_str = node.data.get("cron", "0 8 * * *")

        try:
            parts = cron_str.split()
            if len(parts) != 5:
                logger.warning(
                    "invalid_cron_expression",
                    panel_id=panel_id,
                    node_id=node.id,
                    cron=cron_str,
                )
                return None
            trigger = CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
            )
        except Exception as exc:
            logger.warning(
                "cron_parse_failed",
                panel_id=panel_id,
                node_id=node.id,
                error=str(exc),
            )
            return None

        job_id = f"panel_trigger_{panel_id}_{node.id}"

        async def _run() -> None:
            async with async_session() as session:
                await self._graph_executor.run(panel_id, session, triggered_node_id=node.id)

        def _wrapper() -> None:
            asyncio.create_task(_run())

        try:
            self._scheduler.add_job(
                _wrapper,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
            )
            logger.info(
                "schedule_trigger_registered",
                panel_id=panel_id,
                node_id=node.id,
                cron=cron_str,
                job_id=job_id,
            )
            return job_id
        except Exception as exc:
            logger.warning(
                "schedule_trigger_registration_failed",
                panel_id=panel_id,
                node_id=node.id,
                error=str(exc),
            )
            return None

    def _register_device_event_trigger(
        self, panel_id: int, node: GraphNode
    ) -> EventHandlerInfo | None:
        event_filter = "state_change"
        ieee_filter: str | None = None
        if node.data:
            event_filter = node.data.get("event", "state_change")
            ieee_filter = node.data.get("ieee") or None

        async def _run() -> None:
            async with async_session() as session:
                await self._graph_executor.run(panel_id, session, triggered_node_id=node.id)

        def _handler(payload: dict[str, Any]) -> None:
            evt = payload.get("event")
            data = payload.get("data", {})
            if evt != event_filter:
                return
            if ieee_filter:
                payload_ieee = data.get("ieee") if isinstance(data, dict) else None
                if payload_ieee != ieee_filter:
                    return
            asyncio.create_task(_run())

        event_type = "device_event"
        self._event_bus.subscribe(event_type, _handler)
        logger.info(
            "device_event_trigger_registered",
            panel_id=panel_id,
            node_id=node.id,
            trigger_event=event_filter,
            ieee=ieee_filter,
        )
        return (event_type, _handler)
