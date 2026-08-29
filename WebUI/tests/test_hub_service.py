"""Tests for HubService state_change processing."""

import asyncio

import pytest
from sqlalchemy import delete

from app.db import async_session
from app.models.db_models import Device, DeviceAlias
from app.repositories.device import DeviceRepository
from app.services.event_bus import EventBus
from app.services.hub_service import HubService

IEEE = "00:11:22:33:44:55:66:77"


async def _seed_device():
    async with async_session() as session:
        await session.execute(delete(DeviceAlias).where(DeviceAlias.ieee_addr == IEEE))
        await session.execute(delete(Device).where(Device.ieee_addr == IEEE))
        session.add(
            Device(
                ieee_addr=IEEE,
                network_addr="0x1234",
                online=True,
                endpoints=[{"id": 1}],
            )
        )
        await session.commit()


def _level_report(level: int) -> dict:
    """A firmware state_change for CurrentLevel, as parsed from serial."""
    return {
        "evt": "state_change",
        "ieee_addr": IEEE,
        "changes": [
            {
                "cluster": "0x0008",
                "attribute": "0x0000",
                "endpoint": 1,
                "value": level,
            }
        ],
    }


@pytest.mark.asyncio
async def test_state_changes_applied_in_arrival_order():
    """Regression: a dimming ramp's reports must be applied in order.

    Each state_change used to spawn its own task, so rapid reports (e.g.
    110 then 128 during a ramp) could race for the per-device lock and
    persist the older intermediate value last, leaving the UI stuck on it.
    """
    await _seed_device()
    hub = HubService(event_bus=EventBus())

    # Feed the whole ramp at once, exactly as one serial read chunk would.
    for level in (0, 40, 85, 110, 128):
        hub._on_hub_message(_level_report(level))

    # Poll with a fresh session each time: the worker commits in its own
    # sessions, and a cached identity-map row would never see the updates.
    device = None
    for _ in range(100):  # up to ~2 s for the ordered worker to drain
        async with async_session() as session:
            device = await DeviceRepository(session).get_by_ieee(IEEE)
            state = device.state
        if state == {"1": {"level": 128}}:
            break
        await asyncio.sleep(0.02)
    assert state == {"1": {"level": 128}}

    await hub.disconnect()
