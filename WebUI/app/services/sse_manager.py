"""Server-Sent Events manager for pushing real-time updates to clients."""

import asyncio
from typing import List, Any, Dict

import structlog

logger = structlog.get_logger(__name__)

_MAX_QUEUE_SIZE = 100


class SSEManager:
    """Broadcast JSON events to all connected HTTP SSE clients."""

    def __init__(self, max_queue_size: int = _MAX_QUEUE_SIZE) -> None:
        self._queues: List[asyncio.Queue[Dict[str, Any]]] = []
        self._max_queue_size = max_queue_size
        self._lock = asyncio.Lock()

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        """Create and register a new queue for an SSE consumer."""
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=self._max_queue_size)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Dict[str, Any]]) -> None:
        """Remove a queue from the broadcast list."""
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Enqueue an event to all active consumers (non-blocking)."""
        message = {"type": event_type, **payload}
        dropped = 0
        async with self._lock:
            queues = list(self._queues)
        for q in queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            logger.warning("sse_broadcast_dropped_messages", dropped=dropped, event_type=event_type)


sse_manager = SSEManager()
