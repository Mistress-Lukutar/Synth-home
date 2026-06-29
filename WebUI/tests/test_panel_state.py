"""Tests for PanelStateService and SSE output broadcasting."""

import pytest
from unittest.mock import AsyncMock

from app.services.event_bus import EventBus
from app.services.panel_state_service import PanelStateService


@pytest.mark.asyncio
async def test_set_output_value_publishes_event():
    event_bus = EventBus()
    handler = AsyncMock()
    event_bus.subscribe("panel_output", handler)

    service = PanelStateService(event_bus=event_bus)
    service.set_output_value(1, "_out_n1", 42)

    # Give asyncio.create_task a chance to run
    import asyncio
    await asyncio.sleep(0.05)

    handler.assert_called_once()
    call_args = handler.call_args[0][0]
    assert call_args["panel_id"] == 1
    assert call_args["node_id"] == "_out_n1"
    assert call_args["value"] == 42


def test_set_input_value_does_not_publish():
    event_bus = EventBus()
    handler = AsyncMock()
    event_bus.subscribe("panel_output", handler)

    service = PanelStateService(event_bus=event_bus)
    service.set_input_value(1, "sw1", True)

    handler.assert_not_called()


def test_get_all_inputs_returns_state():
    service = PanelStateService()
    service.set_input_value(1, "a", 1)
    service.set_output_value(1, "_out_b", 2)

    assert service.get_all_inputs(1) == {"a": 1, "_out_b": 2}
