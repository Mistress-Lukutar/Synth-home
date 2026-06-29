"""Tests for the devices router with mocked HubService."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete

from app.db import async_session
from app.models.db_models import Device, DeviceAlias
from app.services.event_bus import EventBus
from app.services.hub_service import HubService


@pytest.fixture
def mock_hub():
    hub = MagicMock(spec=HubService)
    hub.is_connected.return_value = True
    hub.fetch_devices = AsyncMock(return_value=[
        {"ieee": "00:11:22:33:44:55:66:77", "name": "Lamp", "endpoint": 1, "online": True}
    ])
    hub.send_command = AsyncMock(return_value={"correlation_id": "abc-123", "status": "queued"})
    return hub


async def _seed_device():
    async with async_session() as session:
        await session.execute(
            delete(DeviceAlias).where(DeviceAlias.ieee_addr == "00:11:22:33:44:55:66:77")
        )
        await session.execute(
            delete(Device).where(Device.ieee_addr == "00:11:22:33:44:55:66:77")
        )
        device = Device(
            ieee_addr="00:11:22:33:44:55:66:77",
            network_addr="0x1234",
            online=True,
            endpoints=[{"id": 1}],
        )
        session.add(device)
        alias = DeviceAlias(ieee_addr="00:11:22:33:44:55:66:77", name="Lamp")
        session.add(alias)
        await session.commit()


def test_list_devices(mock_hub, client):
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(_seed_device())
    client.app.state.hub_service = mock_hub
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["devices"]) == 1
    assert data["devices"][0]["ieee"] == "00:11:22:33:44:55:66:77"
    assert data["devices"][0]["name"] == "Lamp"


def test_send_command(mock_hub, client):
    client.app.state.hub_service = mock_hub
    response = client.post(
        "/api/devices/00:11:22:33:44:55:66:77/command",
        json={"action": "on", "params": {}},
    )
    assert response.status_code == 202
    data = response.json()
    assert data["correlation_id"] == "abc-123"


def test_rename_device(client):
    asyncio = pytest.importorskip("asyncio")
    asyncio.run(_seed_device())
    response = client.patch(
        "/api/devices/00:11:22:33:44:55:66:77/rename",
        json={"name": "Living Room Lamp"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["name"] == "Living Room Lamp"


@pytest.mark.asyncio
async def test_update_device_state_caches_static_attrs_into_endpoints():
    """Static read_attr values should be written into endpoints JSON for frontend caching."""
    await _seed_device()
    event_bus = EventBus()
    hub = HubService(event_bus=event_bus)

    await hub._state_manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 8, 2, 10)
    await hub._state_manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 8, 3, 254)
    await hub._state_manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 768, 0x4002, 0x31)
    await hub._state_manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 768, 0x400B, 250)
    await hub._state_manager.apply_state_change("00:11:22:33:44:55:66:77", 1, 768, 0x400C, 454)

    async with async_session() as session:
        from app.repositories.device import DeviceRepository
        repo = DeviceRepository(session)
        device = await repo.get_by_ieee("00:11:22:33:44:55:66:77")
        assert device is not None
        ep = device.endpoints[0]
        assert ep["level_min"] == 10
        assert ep["level_max"] == 254
        assert ep["color_caps"] == {"hs": True, "xy": True, "ct": True, "color_loop": False}
        assert ep["ct_min"] == 250
        assert ep["ct_max"] == 454
