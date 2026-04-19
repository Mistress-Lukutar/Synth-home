"""Tests for trigger nodes, flow-control nodes, and PanelTriggerService."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.models.db_models import GraphNode
from app.services.event_bus import EventBus
from app.services.graph_executor import GraphExecutor
from app.services.node_executors.logic import FlowIfExecutor, FlowDelayExecutor
from app.services.node_executors.trigger import TriggerScheduleExecutor, TriggerDeviceEventExecutor
from app.services.panel_trigger_service import PanelTriggerService


class TestFlowIfExecutor:
    async def test_true_branch(self):
        ex = FlowIfExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_if", data={})
        result = await ex.execute(None, node, {"trigger": True, "condition": True})
        assert result == {"true": True, "false": False}

    async def test_false_branch(self):
        ex = FlowIfExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_if", data={})
        result = await ex.execute(None, node, {"trigger": True, "condition": False})
        assert result == {"true": False, "false": True}

    async def test_default_false_when_missing(self):
        ex = FlowIfExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_if", data={})
        result = await ex.execute(None, node, {})
        assert result == {"true": False, "false": False}


class TestFlowDelayExecutor:
    async def test_no_trigger_no_delay(self):
        ex = FlowDelayExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_delay", data={"seconds": 0.05})
        result = await ex.execute(None, node, {"trigger": False})
        assert result == {"done": False}

    async def test_trigger_delays(self):
        ex = FlowDelayExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_delay", data={"seconds": 0.1})
        start = asyncio.get_event_loop().time()
        result = await ex.execute(None, node, {"trigger": True})
        elapsed = asyncio.get_event_loop().time() - start
        assert result == {"done": True}
        assert elapsed >= 0.08

    async def test_invalid_seconds_fallback(self):
        ex = FlowDelayExecutor()
        node = GraphNode(id="n1", graph_id=1, type="flow_delay", data={"seconds": "bad"})
        result = await ex.execute(None, node, {"trigger": True})
        assert result == {"done": True}


class TestTriggerScheduleExecutor:
    async def test_emits_trigger(self):
        ex = TriggerScheduleExecutor()
        node = GraphNode(id="n1", graph_id=1, type="trigger_schedule", data={})
        result = await ex.execute(None, node, {})
        assert result == {"trigger": True}


class TestTriggerDeviceEventExecutor:
    async def test_emits_trigger_with_device(self):
        ex = TriggerDeviceEventExecutor()
        node = GraphNode(id="n1", graph_id=1, type="trigger_device_event", data={"ieee": "aa:bb"})
        result = await ex.execute(None, node, {})
        assert result["trigger"] is True
        assert result["device"]["ieee"] == "aa:bb"

    async def test_default_empty_ieee(self):
        ex = TriggerDeviceEventExecutor()
        node = GraphNode(id="n1", graph_id=1, type="trigger_device_event", data={})
        result = await ex.execute(None, node, {})
        assert result["trigger"] is True
        assert result["device"]["ieee"] == ""


class TestReadExecutors:
    async def test_read_on_off_no_device(self):
        from app.services.node_executors.device import ReadOnOffExecutor
        ex = ReadOnOffExecutor()
        node = GraphNode(id="r1", graph_id=1, type="read_on_off", data={"endpoint": 1})
        result = await ex.execute(None, node, {})
        assert result == {"device": None, "on": False}

    async def test_read_level_no_hub(self):
        from app.services.node_executors.device import ReadLevelExecutor
        ex = ReadLevelExecutor()
        node = GraphNode(id="r1", graph_id=1, type="read_level", data={"endpoint": 1})
        result = await ex.execute(None, node, {"device": {"ieee": "aa"}})
        assert result == {"device": {"ieee": "aa"}, "level": 0}

    async def test_read_color_with_mock_hub(self):
        from app.services.node_executors.device import ReadColorExecutor
        from app.services.node_executors.base import ExecutionContext
        from unittest.mock import MagicMock

        ex = ReadColorExecutor()
        node = GraphNode(id="r1", graph_id=1, type="read_color", data={"endpoint": 1})
        hub = MagicMock()
        hub.get_cached_devices.return_value = [
            {"ieee": "aa", "state": {"1": {"color": "#ff0000"}}}
        ]
        ctx = ExecutionContext(panel_id=1, graph_id=1, hub_service=hub, panel_state_service=None)
        result = await ex.execute(ctx, node, {"device": {"ieee": "aa"}})
        assert result == {"device": {"ieee": "aa"}, "color": "#ff0000"}


class TestPanelTriggerService:
    async def test_register_and_unregister_schedule(self):
        scheduler = AsyncIOScheduler()
        scheduler.start()
        try:
            graph_executor = MagicMock(spec=GraphExecutor)
            graph_executor.run = AsyncMock()
            event_bus = EventBus()

            svc = PanelTriggerService(scheduler, graph_executor, event_bus)

            node = GraphNode(
                id="t1",
                graph_id=1,
                type="trigger_schedule",
                data={"cron": "0 0 * * *"},
            )
            job_id = svc._register_schedule_trigger(42, node)
            assert job_id is not None
            # _register_schedule_trigger itself does not populate _panel_jobs;
            # that is done by _register_for_panel. We simulate it here.
            svc._panel_jobs.setdefault(42, []).append(job_id)

            # Unregister should remove job
            svc.remove_panel(42)
            assert 42 not in svc._panel_jobs
        finally:
            scheduler.shutdown()

    async def test_register_and_unregister_device_event(self):
        scheduler = AsyncIOScheduler()
        scheduler.start()
        try:
            graph_executor = MagicMock(spec=GraphExecutor)
            graph_executor.run = AsyncMock()
            event_bus = EventBus()

            svc = PanelTriggerService(scheduler, graph_executor, event_bus)

            node = GraphNode(
                id="t1",
                graph_id=1,
                type="trigger_device_event",
                data={"event": "state_change", "ieee": "aa:bb"},
            )
            handler_info = svc._register_device_event_trigger(42, node)
            assert handler_info is not None
            svc._panel_handlers.setdefault(42, []).append(handler_info)
            assert len(svc._panel_handlers.get(42, [])) == 1

            # Publish matching event
            await event_bus.publish("device_event", {"event": "state_change", "data": {"ieee": "aa:bb"}})
            await asyncio.sleep(0.05)
            graph_executor.run.assert_awaited_once()

            # Unregister
            svc.remove_panel(42)
            assert 42 not in svc._panel_handlers
        finally:
            scheduler.shutdown()

    async def test_device_event_filter_mismatch(self):
        scheduler = AsyncIOScheduler()
        scheduler.start()
        try:
            graph_executor = MagicMock(spec=GraphExecutor)
            graph_executor.run = AsyncMock()
            event_bus = EventBus()

            svc = PanelTriggerService(scheduler, graph_executor, event_bus)

            node = GraphNode(
                id="t1",
                graph_id=1,
                type="trigger_device_event",
                data={"event": "state_change", "ieee": "aa:bb"},
            )
            svc._register_device_event_trigger(42, node)

            # Publish non-matching event
            await event_bus.publish("device_event", {"event": "device_joined", "data": {"ieee": "aa:bb"}})
            await asyncio.sleep(0.05)
            graph_executor.run.assert_not_awaited()
        finally:
            scheduler.shutdown()
