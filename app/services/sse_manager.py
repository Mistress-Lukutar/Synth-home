"""Server-Sent Events manager for pushing real-time updates to clients."""

import asyncio
from typing import List, Any, Dict


class SSEManager:
    """Broadcast JSON events to all connected HTTP SSE clients."""

    def __init__(self) -> None:
        self._queues: List[asyncio.Queue[Dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        """Create and register a new queue for an SSE consumer."""
        q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Dict[str, Any]]) -> None:
        """Remove a queue from the broadcast list."""
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Enqueue an event to all active consumers."""
        message = {"type": event_type, **payload}
        for q in self._queues:
            await q.put(message)


sse_manager = SSEManager()
