"""Tests for the SSEManager."""

import asyncio

import pytest

from app.services.sse_manager import SSEManager


@pytest.fixture
def manager():
    return SSEManager(max_queue_size=5)


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe(manager):
    q = manager.subscribe()
    assert q in manager._queues
    manager.unsubscribe(q)
    assert q not in manager._queues


@pytest.mark.asyncio
async def test_broadcast_delivers_message(manager):
    q = manager.subscribe()
    await manager.broadcast("test_event", {"key": "value"})
    msg = await asyncio.wait_for(q.get(), timeout=1.0)
    assert msg["type"] == "test_event"
    assert msg["key"] == "value"
    manager.unsubscribe(q)


@pytest.mark.asyncio
async def test_broadcast_drops_for_full_queues(manager):
    q = manager.subscribe()
    # Fill the queue
    for i in range(5):
        q.put_nowait({"filler": i})

    # Broadcast should not block and should drop the message
    await manager.broadcast("overflow", {"data": "x"})

    # Queue still has only the original 5 items
    assert q.qsize() == 5
    manager.unsubscribe(q)


@pytest.mark.asyncio
async def test_broadcast_to_multiple_clients(manager):
    q1 = manager.subscribe()
    q2 = manager.subscribe()
    await manager.broadcast("multi", {"idx": 1})
    m1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    m2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert m1 == m2
    manager.unsubscribe(q1)
    manager.unsubscribe(q2)
