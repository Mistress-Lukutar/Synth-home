"""In-memory domain event bus for decoupled communication between layers."""

import asyncio
from typing import Callable, Any

import structlog

logger = structlog.get_logger(__name__)

EventHandler = Callable[[dict[str, Any]], Any]


class EventBus:
    """Lightweight async event bus using topic-based subscriptions."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Remove a previously registered handler."""
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(event_type, None)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Publish an event to all subscribed handlers (fire-and-forget)."""
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            return
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.isfuture(result) or asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception:
                logger.exception("event_handler_failed", event_type=event_type)


event_bus = EventBus()
