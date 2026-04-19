"""Runtime state storage for panel UI controls."""

import asyncio
from typing import Any

import structlog

from app.services.event_bus import EventBus

logger = structlog.get_logger(__name__)


class PanelStateService:
    """Holds the current values of all panel UI input/output nodes in memory.

    When a control value changes, the service can optionally invoke a
    callback to trigger graph re-execution.
    Output changes are broadcast via EventBus for SSE delivery.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._states: dict[int, dict[str, Any]] = {}
        self._on_change: dict[int, list] = {}
        self._global_callbacks: list = []
        self._event_bus = event_bus

    def set_input_value(self, panel_id: int, node_id: str, value: Any) -> None:
        """Update the value of a panel input node (no broadcast)."""
        if panel_id not in self._states:
            self._states[panel_id] = {}
        old = self._states[panel_id].get(node_id)
        self._states[panel_id][node_id] = value
        logger.info("panel_input_changed", panel_id=panel_id, node_id=node_id, old=old, new=value)
        self._notify(panel_id, node_id, value)

    def set_output_value(self, panel_id: int, node_id: str, value: Any) -> None:
        """Update the value of a panel output node and broadcast via SSE."""
        if panel_id not in self._states:
            self._states[panel_id] = {}
        old = self._states[panel_id].get(node_id)
        self._states[panel_id][node_id] = value
        logger.info("panel_output_changed", panel_id=panel_id, node_id=node_id, old=old, new=value)
        # Broadcast to SSE
        if self._event_bus is not None:
            try:
                asyncio.create_task(
                    self._event_bus.publish(
                        "panel_output",
                        {"panel_id": panel_id, "node_id": node_id, "value": value},
                    )
                )
            except Exception:
                logger.exception("panel_output_publish_failed")

    def _notify(self, panel_id: int, node_id: str, value: Any) -> None:
        """Invoke registered callbacks for input changes."""
        for cb in self._on_change.get(panel_id, []):
            try:
                result = cb(node_id, value)
                if result is not None and hasattr(result, "__await__"):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("panel_input_callback_failed", panel_id=panel_id)
        for cb in self._global_callbacks:
            try:
                result = cb(panel_id, node_id, value)
                if result is not None and hasattr(result, "__await__"):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("panel_global_callback_failed", panel_id=panel_id)

    def subscribe_global(self, callback) -> None:
        """Register a callback(panel_id, node_id, value) for any input change."""
        self._global_callbacks.append(callback)

    def get_input_value(self, panel_id: int, node_id: str, default: Any = None) -> Any:
        """Retrieve the current value of a panel input node."""
        return self._states.get(panel_id, {}).get(node_id, default)

    def get_all_inputs(self, panel_id: int) -> dict[str, Any]:
        """Return all input values for a panel."""
        return dict(self._states.get(panel_id, {}))

    def subscribe(self, panel_id: int, callback) -> None:
        """Register a callback(panel_id, node_id, value) for input changes."""
        self._on_change.setdefault(panel_id, []).append(callback)

    def unsubscribe(self, panel_id: int, callback) -> None:
        """Remove a previously registered callback."""
        cbs = self._on_change.get(panel_id, [])
        if callback in cbs:
            cbs.remove(callback)
